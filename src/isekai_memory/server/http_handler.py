"""FastAPI server with authenticated REST and stateless MCP Streamable HTTP."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from isekai_memory.config import Settings
from isekai_memory.server.auth import Principal, verify_token
from isekai_memory.server.errors import MemoryToolError
from isekai_memory.server.mcp_handler import McpProtocolHandler
from isekai_memory.server.protocol import (
    _META_PROTOCOL_VERSION,
    ERR_HEADER_MISMATCH,
    ERR_INVALID_PARAMS,
    ERR_INVALID_REQUEST,
    ERR_METHOD_NOT_FOUND,
    ERR_PARSE_ERROR,
    ERR_UNSUPPORTED_PROTOCOL_VERSION,
    PROTOCOL_VERSION,
    SUPPORTED_VERSIONS,
)
from isekai_memory.server.tools import TOOL_NAMES, TOOLS
from isekai_memory.store.database import close_pool, health_check, init_pool


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Invalid JSON constant: {value}")


def create_app(settings: Settings, dispatch: Any) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await init_pool(settings)
        yield
        await close_pool()

    app = FastAPI(title="isekai-memory", version="0.2.0", lifespan=lifespan)
    mcp = McpProtocolHandler(dispatch)
    protocol_headers = {"MCP-Protocol-Version": PROTOCOL_VERSION}

    @app.middleware("http")
    async def reference_cache_policy(request: Request, call_next):
        response = await call_next(request)
        if request.url.path == "/mcp" or request.url.path.startswith("/tools"):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
        return response

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        if request.url.path in ("/health", "/ready", "/docs", "/openapi.json"):
            return await call_next(request)
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > settings.max_http_request_bytes:
            return JSONResponse(
                {"error": {"error_code": "MEM-HTTP-0001", "message": "Request body too large"}},
                status_code=413,
            )
        if not settings.auth_enabled:
            request.state.principal = Principal.local_stdio()
            return await call_next(request)
        authorization = request.headers.get("authorization", "")
        raw_token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else None
        raw_token = raw_token or request.headers.get(settings.auth_token_header)
        try:
            request.state.principal = await verify_token(raw_token)
        except MemoryToolError as error:
            return JSONResponse(
                {
                    "error": {
                        "error_code": error.data.get("error_code", "MEM-AUTH-0001"),
                        "message": error.message,
                    }
                },
                status_code=error.http_status,
            )
        return await call_next(request)

    async def json_body(request: Request) -> Any:
        body = await request.body()
        if len(body) > settings.max_http_request_bytes:
            raise MemoryToolError(
                "Request body too large",
                data={"error_code": "MEM-HTTP-0001"},
                http_status=413,
            )
        try:
            return json.loads(body, parse_constant=_reject_json_constant)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            raise MemoryToolError(
                "Invalid JSON body",
                code=ERR_PARSE_ERROR,
                data={"error_code": "MEM-TOOL-0002"},
            ) from error

    def mcp_error(
        identifier: Any,
        code: int,
        message: str,
        *,
        data: dict[str, Any] | None = None,
        status_code: int = 400,
    ) -> JSONResponse:
        return JSONResponse(
            mcp.error_response(identifier, code, message, data),
            status_code=status_code,
            headers=protocol_headers,
        )

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/ready")
    async def ready():
        try:
            return await health_check()
        except Exception as error:
            return JSONResponse({"database": "unavailable", "reason": str(error)}, status_code=503)

    @app.post("/mcp")
    async def mcp_endpoint(request: Request):
        client_version = request.headers.get("mcp-protocol-version")
        if client_version is None:
            return mcp_error(None, ERR_HEADER_MISMATCH, "Missing required MCP-Protocol-Version header")
        if client_version != PROTOCOL_VERSION:
            return mcp_error(
                None,
                ERR_UNSUPPORTED_PROTOCOL_VERSION,
                "Unsupported protocol version",
                data={"supportedVersions": SUPPORTED_VERSIONS},
            )

        try:
            payload = await json_body(request)
        except MemoryToolError as error:
            return mcp_error(None, error.code, error.message, data=error.data, status_code=error.http_status)

        if not isinstance(payload, dict):
            return mcp_error(None, ERR_INVALID_REQUEST, "Invalid Request")

        identifier = payload.get("id")
        body_method = payload.get("method")
        method_header = request.headers.get("mcp-method")
        if method_header is None:
            return mcp_error(identifier, ERR_HEADER_MISMATCH, "Missing required Mcp-Method header")
        if method_header != body_method:
            return mcp_error(
                identifier,
                ERR_HEADER_MISMATCH,
                "Mcp-Method header does not match request body method",
            )

        name_header = request.headers.get("mcp-name")
        params = payload.get("params")
        if body_method == "tools/call":
            if name_header is None:
                return mcp_error(identifier, ERR_HEADER_MISMATCH, "Missing required Mcp-Name header")
            body_name = params.get("name") if isinstance(params, dict) else None
            if not isinstance(body_name, str) or name_header != body_name:
                return mcp_error(
                    identifier,
                    ERR_HEADER_MISMATCH,
                    "Mcp-Name header does not match params.name",
                )
        elif name_header is not None:
            return mcp_error(
                identifier,
                ERR_HEADER_MISMATCH,
                "Mcp-Name header is only valid for tools/call",
            )

        if isinstance(params, dict):
            body_meta = params.get("_meta")
            body_version = body_meta.get(_META_PROTOCOL_VERSION) if isinstance(body_meta, dict) else None
            if body_version is not None and body_version != client_version:
                return mcp_error(
                    identifier,
                    ERR_HEADER_MISMATCH,
                    "MCP-Protocol-Version header does not match _meta protocolVersion",
                )

        try:
            response = await mcp.handle(payload, principal=request.state.principal)
        except MemoryToolError as error:
            response = mcp.error_response(None, error.code, error.message, error.data)
        if response is None:
            return Response(status_code=202, headers=protocol_headers)
        if isinstance(response.get("error"), dict) and response["error"].get("code") == ERR_METHOD_NOT_FOUND:
            return JSONResponse(response, status_code=404, headers=protocol_headers)
        return JSONResponse(response, headers=protocol_headers)

    @app.get("/tools")
    async def list_tools():
        return {"tools": TOOLS}

    @app.post("/tools/{tool_name}")
    async def call_tool(tool_name: str, request: Request):
        if tool_name not in TOOL_NAMES:
            return JSONResponse(
                {"error": {"error_code": "MEM-TOOL-0001", "message": f"Unknown tool: {tool_name}"}},
                status_code=404,
            )
        try:
            body = await json_body(request)
            if not isinstance(body, dict):
                raise MemoryToolError(
                    "Body must be a JSON object",
                    code=ERR_INVALID_PARAMS,
                    data={"error_code": "MEM-TOOL-0002"},
                )
            return await dispatch(tool_name, body, request.state.principal)
        except MemoryToolError as error:
            return JSONResponse(
                {
                    "error": {
                        "error_code": error.data.get("error_code", "MEM-UNKNOWN"),
                        "message": error.message,
                        "details": error.data,
                    }
                },
                status_code=error.http_status,
            )
        except Exception:
            return JSONResponse(
                {"error": {"error_code": "MEM-INTERNAL-0001", "message": "Internal server error"}},
                status_code=500,
            )

    return app
