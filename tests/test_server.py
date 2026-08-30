"""MCP 2026-07-28 protocol and transport tests."""

from __future__ import annotations

import io
import json

import httpx
import pytest

from isekai_memory.config import Settings
from isekai_memory.server.auth import Principal, authorize_tool
from isekai_memory.server.errors import MemoryToolError
from isekai_memory.server.http_handler import create_app
from isekai_memory.server.mcp_handler import McpProtocolHandler, McpStdioServer
from isekai_memory.server.protocol import (
    ERR_HEADER_MISMATCH,
    ERR_INVALID_PARAMS,
    ERR_METHOD_NOT_FOUND,
    ERR_UNSUPPORTED_PROTOCOL_VERSION,
    PROTOCOL_VERSION,
    SUPPORTED_VERSIONS,
    extract_request_meta,
    validate_protocol_version,
)
from isekai_memory.server.validation import validate_tool_arguments


def _meta(version: str = PROTOCOL_VERSION) -> dict:
    return {
        "io.modelcontextprotocol/protocolVersion": version,
        "io.modelcontextprotocol/clientCapabilities": {},
        "io.modelcontextprotocol/clientInfo": {"name": "test", "version": "1"},
    }


def _request(method: str, params: dict | None = None, *, identifier: int = 1) -> dict:
    request_params = dict(params or {})
    request_params.setdefault("_meta", _meta())
    return {
        "jsonrpc": "2.0",
        "id": identifier,
        "method": method,
        "params": request_params,
    }


async def _dispatch(name, arguments, principal):
    return {"name": name, "arguments": arguments}


async def _http_mcp(
    method: str,
    *,
    params: object | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    app = create_app(Settings(auth_enabled=False), _dispatch)
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": {"_meta": _meta()} if params is None else params,
    }
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post("/mcp", json=payload, headers=headers or {})


def test_extract_request_meta_missing_meta_raises() -> None:
    with pytest.raises(MemoryToolError) as raised:
        extract_request_meta({})
    assert raised.value.code == ERR_INVALID_PARAMS


def test_extract_request_meta_missing_version_raises() -> None:
    with pytest.raises(MemoryToolError) as raised:
        extract_request_meta({"_meta": {"io.modelcontextprotocol/clientCapabilities": {}}})
    assert raised.value.code == ERR_INVALID_PARAMS


def test_validate_protocol_version_rejects_unsupported() -> None:
    from isekai_memory.server.protocol import RequestMeta

    meta = RequestMeta(protocol_version="1999-01-01", client_info=None, client_capabilities={}, raw={})
    with pytest.raises(MemoryToolError) as raised:
        validate_protocol_version(meta)
    assert raised.value.code == ERR_UNSUPPORTED_PROTOCOL_VERSION
    assert raised.value.data["supportedVersions"] == SUPPORTED_VERSIONS


def test_input_schema_rejects_extra_and_missing_fields() -> None:
    with pytest.raises(MemoryToolError) as raised:
        validate_tool_arguments("memory_artifact_publish", {"unexpected": True})
    assert raised.value.code == -32602
    assert raised.value.data["error_code"] == "MEM-TOOL-0002"


def test_read_only_principal_cannot_publish() -> None:
    principal = Principal("user-1", "project-1", frozenset({"read"}))
    with pytest.raises(MemoryToolError) as raised:
        authorize_tool(principal, "memory_artifact_publish", {})
    assert raised.value.http_status == 403


def test_project_scope_is_enforced() -> None:
    principal = Principal("user-1", "project-1", frozenset({"read"}))
    with pytest.raises(MemoryToolError) as raised:
        authorize_tool(principal, "memory_handoff_list", {"project_id": "project-2"})
    assert raised.value.data["error_code"] == "MEM-AUTH-0003"


@pytest.mark.asyncio
async def test_server_discover_returns_cacheable_schema_shape() -> None:
    handler = McpProtocolHandler(_dispatch)
    response = await handler.handle(_request("server/discover"), principal=Principal.local_stdio())
    result = response["result"]
    assert result["resultType"] == "complete"
    assert result["supportedVersions"] == ["2026-07-28"]
    assert result["capabilities"] == {"tools": {"listChanged": False}}
    assert isinstance(result["instructions"], str) and result["instructions"]
    assert result["ttlMs"] == 3_600_000
    assert result["cacheScope"] == "public"
    assert "serverInfo" not in result
    assert result["_meta"]["io.modelcontextprotocol/serverInfo"]["name"] == "isekai-memory"


@pytest.mark.asyncio
async def test_tools_list_returns_cacheable_result() -> None:
    handler = McpProtocolHandler(_dispatch)
    response = await handler.handle(_request("tools/list"), principal=Principal.local_stdio())
    result = response["result"]
    assert result["resultType"] == "complete"
    assert result["ttlMs"] == 3_600_000
    assert result["cacheScope"] == "public"
    assert len(result["tools"]) == 12


@pytest.mark.asyncio
async def test_malformed_envelope_without_id_is_not_silenced_as_notification() -> None:
    handler = McpProtocolHandler(_dispatch)
    response = await handler.handle(
        {"jsonrpc": "1.0", "method": "tools/list", "params": {"_meta": _meta()}},
        principal=Principal.local_stdio(),
    )
    assert response["id"] is None
    assert response["error"]["code"] == -32600


@pytest.mark.asyncio
@pytest.mark.parametrize("identifier", [None, True, [], {}, float("nan"), float("inf"), float("-inf")])
async def test_invalid_request_id_types_are_rejected(identifier: object) -> None:
    handler = McpProtocolHandler(_dispatch)
    request = _request("tools/list")
    request["id"] = identifier
    response = await handler.handle(request, principal=Principal.local_stdio())
    assert response["id"] is None
    assert response["error"]["code"] == -32600


@pytest.mark.asyncio
async def test_missing_meta_returns_invalid_params() -> None:
    handler = McpProtocolHandler(_dispatch)
    response = await handler.handle(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        principal=Principal.local_stdio(),
    )
    assert response["error"]["code"] == ERR_INVALID_PARAMS


@pytest.mark.asyncio
async def test_unsupported_version_returns_error() -> None:
    handler = McpProtocolHandler(_dispatch)
    response = await handler.handle(
        _request("tools/list", {"_meta": _meta("1999-01-01")}),
        principal=Principal.local_stdio(),
    )
    assert response["error"]["code"] == ERR_UNSUPPORTED_PROTOCOL_VERSION


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["unknown/method", "initialize", "ping"])
async def test_removed_or_unknown_method_returns_method_not_found(method: str) -> None:
    handler = McpProtocolHandler(_dispatch)
    response = await handler.handle(_request(method), principal=Principal.local_stdio())
    assert response["error"]["code"] == ERR_METHOD_NOT_FOUND


@pytest.mark.asyncio
async def test_removed_initialized_notification_has_no_response() -> None:
    handler = McpProtocolHandler(_dispatch)
    request = _request("notifications/initialized")
    request.pop("id")
    assert await handler.handle(request, principal=Principal.local_stdio()) is None


@pytest.mark.asyncio
async def test_tool_failure_is_mcp_error_result() -> None:
    async def dispatch(name, arguments, principal):
        raise MemoryToolError("denied", data={"error_code": "MEM-AUTH-0002"})

    handler = McpProtocolHandler(dispatch)
    response = await handler.handle(
        _request(
            "tools/call",
            {
                "name": "memory_handoff_list",
                "arguments": {"project_id": "project-1"},
                "_meta": _meta(),
            },
        ),
        principal=Principal.local_stdio(),
    )
    assert response["result"]["isError"] is True
    assert response["result"]["resultType"] == "complete"
    assert response["result"]["structuredContent"]["error"]["error_code"] == "MEM-AUTH-0002"


@pytest.mark.asyncio
async def test_stdio_framing_is_modern_only() -> None:
    discover = json.dumps(_request("server/discover", identifier=1))
    initialize = json.dumps(_request("initialize", identifier=2))
    input_stream = io.StringIO(f"{discover}\n{initialize}\n")
    output_stream = io.StringIO()

    await McpStdioServer(_dispatch).serve(input_stream, output_stream)

    responses = [json.loads(line) for line in output_stream.getvalue().splitlines()]
    assert responses[0]["result"]["supportedVersions"] == [PROTOCOL_VERSION]
    assert responses[1]["error"]["code"] == ERR_METHOD_NOT_FOUND


@pytest.mark.asyncio
async def test_stdio_rejects_non_standard_json_constants() -> None:
    input_stream = io.StringIO('{"jsonrpc":"2.0","id":NaN,"method":"tools/list","params":{}}\n')
    output_stream = io.StringIO()

    await McpStdioServer(_dispatch).serve(input_stream, output_stream)

    response = json.loads(output_stream.getvalue())
    assert response["id"] is None
    assert response["error"]["code"] == -32700


@pytest.mark.asyncio
async def test_http_requires_protocol_and_method_headers() -> None:
    missing_protocol = await _http_mcp("server/discover", headers={"Mcp-Method": "server/discover"})
    assert missing_protocol.status_code == 400
    assert missing_protocol.json()["error"]["code"] == ERR_HEADER_MISMATCH

    missing_method = await _http_mcp(
        "server/discover",
        headers={"MCP-Protocol-Version": PROTOCOL_VERSION},
    )
    assert missing_method.status_code == 400
    assert missing_method.json()["error"]["code"] == ERR_HEADER_MISMATCH


@pytest.mark.asyncio
async def test_http_rejects_legacy_and_header_body_mismatches() -> None:
    legacy = await _http_mcp(
        "server/discover",
        headers={"MCP-Protocol-Version": "2025-06-18", "Mcp-Method": "server/discover"},
    )
    assert legacy.status_code == 400
    assert legacy.json()["error"]["code"] == ERR_UNSUPPORTED_PROTOCOL_VERSION

    wrong_method = await _http_mcp(
        "server/discover",
        headers={"MCP-Protocol-Version": PROTOCOL_VERSION, "Mcp-Method": "tools/list"},
    )
    assert wrong_method.status_code == 400
    assert wrong_method.json()["error"]["code"] == ERR_HEADER_MISMATCH

    wrong_version = await _http_mcp(
        "server/discover",
        params={"_meta": _meta("1999-01-01")},
        headers={"MCP-Protocol-Version": PROTOCOL_VERSION, "Mcp-Method": "server/discover"},
    )
    assert wrong_version.status_code == 400
    assert wrong_version.json()["error"]["code"] == ERR_HEADER_MISMATCH


@pytest.mark.asyncio
async def test_http_enforces_mcp_name_only_for_tools_call() -> None:
    missing_name = await _http_mcp(
        "tools/call",
        params={"name": "memory_handoff_list", "arguments": {}, "_meta": _meta()},
        headers={"MCP-Protocol-Version": PROTOCOL_VERSION, "Mcp-Method": "tools/call"},
    )
    assert missing_name.status_code == 400
    assert missing_name.json()["error"]["code"] == ERR_HEADER_MISMATCH

    name_on_discover = await _http_mcp(
        "server/discover",
        headers={
            "MCP-Protocol-Version": PROTOCOL_VERSION,
            "Mcp-Method": "server/discover",
            "Mcp-Name": "memory_handoff_list",
        },
    )
    assert name_on_discover.status_code == 400
    assert name_on_discover.json()["error"]["code"] == ERR_HEADER_MISMATCH


@pytest.mark.asyncio
async def test_http_rejects_non_standard_json_constants() -> None:
    app = create_app(Settings(auth_enabled=False), _dispatch)
    transport = httpx.ASGITransport(app=app)
    headers = {
        "Content-Type": "application/json",
        "MCP-Protocol-Version": PROTOCOL_VERSION,
        "Mcp-Method": "tools/list",
    }
    body = b'{"jsonrpc":"2.0","id":NaN,"method":"tools/list","params":{}}'
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/mcp", content=body, headers=headers)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == -32700


@pytest.mark.asyncio
async def test_http_valid_discover_and_malformed_call_are_controlled() -> None:
    discover = await _http_mcp(
        "server/discover",
        headers={"MCP-Protocol-Version": PROTOCOL_VERSION, "Mcp-Method": "server/discover"},
    )
    assert discover.status_code == 200
    assert discover.headers["MCP-Protocol-Version"] == PROTOCOL_VERSION
    assert discover.json()["result"]["supportedVersions"] == [PROTOCOL_VERSION]

    malformed = await _http_mcp(
        "tools/call",
        params=["not", "an", "object"],
        headers={
            "MCP-Protocol-Version": PROTOCOL_VERSION,
            "Mcp-Method": "tools/call",
            "Mcp-Name": "memory_handoff_list",
        },
    )
    assert malformed.status_code == 400
    assert malformed.json()["error"]["code"] == ERR_HEADER_MISMATCH
