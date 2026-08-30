"""MCP 2026-07-28 stateless JSON-RPC handler for stdio and HTTP.

There is no initialize handshake. Every request carries protocol metadata and
server/discover is the protocol entry point.
"""

from __future__ import annotations

import asyncio
import json
import math
import sys
from typing import Any, TextIO

from isekai_memory.server.auth import Principal
from isekai_memory.server.errors import MemoryToolError
from isekai_memory.server.protocol import (
    ERR_INTERNAL_ERROR,
    ERR_INVALID_PARAMS,
    ERR_INVALID_REQUEST,
    ERR_METHOD_NOT_FOUND,
    ERR_PARSE_ERROR,
    discover_result,
    extract_request_meta,
    result_meta,
    validate_protocol_version,
)
from isekai_memory.server.tools import TOOL_NAMES, TOOLS

MAX_LINE_BYTES = 8 << 20


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Invalid JSON constant: {value}")


class McpProtocolHandler:
    """Stateless, modern-only MCP 2026-07-28 JSON-RPC handler."""

    def __init__(self, dispatch: Any):
        self._dispatch = dispatch

    async def handle(self, request: Any, *, principal: Principal) -> dict[str, Any] | None:
        if not isinstance(request, dict):
            return self.error_response(None, ERR_INVALID_REQUEST, "Invalid Request")

        method = request.get("method")
        has_identifier = "id" in request
        identifier = request.get("id")

        # A malformed envelope is not a notification merely because it has no id.
        if request.get("jsonrpc") != "2.0" or not isinstance(method, str):
            return self.error_response(None, ERR_INVALID_REQUEST, "Invalid Request")
        if has_identifier and not (
            isinstance(identifier, str)
            or (
                isinstance(identifier, (int, float))
                and not isinstance(identifier, bool)
                and (not isinstance(identifier, float) or math.isfinite(identifier))
            )
        ):
            return self.error_response(None, ERR_INVALID_REQUEST, "Invalid Request id")

        notification = not has_identifier
        params = request.get("params", {})
        if not isinstance(params, dict):
            return None if notification else self.error_response(identifier, ERR_INVALID_PARAMS, "params must be an object")

        try:
            result = await self._route(method, params, principal)
        except MemoryToolError as error:
            return None if notification else self.error_response(identifier, error.code, error.message, error.data)
        except Exception:
            return None if notification else self.error_response(identifier, ERR_INTERNAL_ERROR, "Internal error")

        return None if notification else {"jsonrpc": "2.0", "id": identifier, "result": result}

    async def _route(self, method: str, params: dict[str, Any], principal: Principal) -> dict[str, Any]:
        meta = extract_request_meta(params)
        validate_protocol_version(meta)

        if method == "server/discover":
            return discover_result()
        if method == "tools/list":
            return self._tools_list()
        if method == "tools/call":
            return await self._call_tool(params, principal)
        raise MemoryToolError("Method not found", code=ERR_METHOD_NOT_FOUND)

    def _tools_list(self) -> dict[str, Any]:
        return {
            "resultType": "complete",
            "tools": TOOLS,
            "ttlMs": 3_600_000,
            "cacheScope": "public",
            "_meta": result_meta(),
        }

    async def _call_tool(self, params: dict[str, Any], principal: Principal) -> dict[str, Any]:
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        if tool_name not in TOOL_NAMES:
            raise MemoryToolError(
                f"Unknown tool: {tool_name}",
                code=ERR_INVALID_PARAMS,
                data={"error_code": "MEM-TOOL-0001"},
            )
        if not isinstance(arguments, dict):
            raise MemoryToolError(
                "Tool arguments must be an object",
                code=ERR_INVALID_PARAMS,
                data={"error_code": "MEM-TOOL-0002"},
            )
        try:
            result = await self._dispatch(tool_name, arguments, principal)
            return {
                "resultType": "complete",
                "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, sort_keys=True)}],
                "structuredContent": result,
                "isError": False,
                "_meta": result_meta(),
            }
        except MemoryToolError as error:
            payload = {"message": error.message, **error.data}
            return {
                "resultType": "complete",
                "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, sort_keys=True)}],
                "structuredContent": {"error": payload},
                "isError": True,
                "_meta": result_meta(),
            }

    @staticmethod
    def error_response(
        identifier: Any,
        code: int,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        error: dict[str, Any] = {"code": code, "message": message}
        if data:
            error["data"] = data
        return {"jsonrpc": "2.0", "id": identifier, "error": error}


class McpStdioServer:
    """Modern-only MCP 2026-07-28 newline-delimited stdio server."""

    def __init__(self, dispatch: Any):
        self._protocol = McpProtocolHandler(dispatch)
        self._principal = Principal.local_stdio()

    async def serve(self, input_stream: TextIO = sys.stdin, output_stream: TextIO = sys.stdout) -> None:
        loop = asyncio.get_running_loop()
        while True:
            line = await loop.run_in_executor(None, input_stream.readline)
            if not line:
                break
            if len(line.encode("utf-8")) > MAX_LINE_BYTES:
                self._write(
                    output_stream,
                    McpProtocolHandler.error_response(None, ERR_INVALID_REQUEST, "Request frame exceeds size limit"),
                )
                continue
            try:
                request = json.loads(line, parse_constant=_reject_json_constant)
            except (json.JSONDecodeError, ValueError):
                self._write(output_stream, McpProtocolHandler.error_response(None, ERR_PARSE_ERROR, "Parse error"))
                continue
            response = await self._protocol.handle(request, principal=self._principal)
            if response is not None:
                self._write(output_stream, response)

    @staticmethod
    def _write(output_stream: TextIO, response: dict[str, Any]) -> None:
        output_stream.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
        output_stream.flush()
