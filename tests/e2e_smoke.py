"""PostgreSQL-backed HTTP E2E smoke test for a migrated Memory server.

Required environment variables: MEMORY_BASE_URL, MEMORY_ADMIN_TOKEN,
MEMORY_READ_TOKEN, and MEMORY_CROSS_PROJECT_TOKEN.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from helpers import build_artifact_archive, handoff_arguments  # noqa: E402

from isekai_memory.registry.verification import canonical_bytes, digest_bytes
from isekai_memory.server.protocol import PROTOCOL_VERSION

BASE_URL = os.environ["MEMORY_BASE_URL"].rstrip("/")
ADMIN_TOKEN = os.environ["MEMORY_ADMIN_TOKEN"]
READ_TOKEN = os.environ["MEMORY_READ_TOKEN"]
CROSS_TOKEN = os.environ["MEMORY_CROSS_PROJECT_TOKEN"]


def request(
    path: str,
    *,
    token: str | None = None,
    payload: Any | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, Any, dict[str, str]]:
    body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode()
    request_headers = {"Content-Type": "application/json", **(headers or {})}
    if token:
        request_headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        BASE_URL + path,
        data=body,
        headers=request_headers,
        method="POST" if body is not None else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None, dict(response.headers)
    except urllib.error.HTTPError as error:
        raw = error.read()
        return error.code, json.loads(raw) if raw else None, dict(error.headers)


def request_meta() -> dict[str, Any]:
    return {
        "io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION,
        "io.modelcontextprotocol/clientCapabilities": {},
        "io.modelcontextprotocol/clientInfo": {"name": "e2e", "version": "1"},
    }


def mcp(method: str, *, token: str, params: dict[str, Any] | None = None, identifier: int = 1) -> Any:
    request_params = dict(params or {})
    request_params["_meta"] = request_meta()
    routing_headers = {
        "MCP-Protocol-Version": PROTOCOL_VERSION,
        "Mcp-Method": method,
    }
    if method == "tools/call":
        routing_headers["Mcp-Name"] = request_params["name"]
    status, response, response_headers = request(
        "/mcp",
        token=token,
        payload={"jsonrpc": "2.0", "id": identifier, "method": method, "params": request_params},
        headers=routing_headers,
    )
    assert status == 200, (status, response)
    protocol_header = response_headers.get("MCP-Protocol-Version") or response_headers.get("mcp-protocol-version")
    assert protocol_header == PROTOCOL_VERSION, response_headers
    assert response.get("error") is None, response
    return response["result"]


def mcp_tool(token: str, name: str, arguments: dict[str, Any]) -> Any:
    result = mcp("tools/call", token=token, params={"name": name, "arguments": arguments})
    assert result["isError"] is False, result
    return result["structuredContent"]


def main() -> None:
    status, ready, _ = request("/ready")
    assert status == 200 and ready == {"database": "ok", "schema_revision": "003"}, ready

    discovered = mcp("server/discover", token=ADMIN_TOKEN)
    assert discovered["supportedVersions"] == [PROTOCOL_VERSION]
    assert discovered["ttlMs"] == 3_600_000 and discovered["cacheScope"] == "public"
    assert "serverInfo" not in discovered
    assert discovered["_meta"]["io.modelcontextprotocol/serverInfo"]["name"] == "isekai-memory"
    listed = mcp("tools/list", token=ADMIN_TOKEN)
    names = {tool["name"] for tool in listed["tools"]}
    assert len(names) == 12, names

    archive, manifest = build_artifact_archive()
    publish = {
        "artifact_id": "demo",
        "kind": "foundation",
        "version": "1.0.0",
        "archive_base64": base64.b64encode(archive).decode(),
        "manifest_digest": digest_bytes(canonical_bytes(manifest)),
        "artifact_digest": manifest["artifact_digest"],
        "archive_digest": digest_bytes(archive),
        "metadata": {"source": "e2e"},
    }

    status, denied, _ = request("/tools/memory_artifact_publish", token=READ_TOKEN, payload=publish)
    assert status == 403 and denied["error"]["error_code"] == "MEM-AUTH-0002", denied

    first_publish = mcp_tool(ADMIN_TOKEN, "memory_artifact_publish", publish)
    second_publish = mcp_tool(ADMIN_TOKEN, "memory_artifact_publish", publish)
    assert first_publish["already_exists"] is False
    assert second_publish["already_exists"] is True and second_publish["id"] == first_publish["id"]

    policy = mcp_tool(
        ADMIN_TOKEN,
        "memory_policy_upsert",
        {
            "organization_id": "organization-1",
            "project_pattern": "project-*",
            "kind": "foundation",
            "artifact_id": "demo",
            "version_range": ">=1.0.0 <2.0.0",
            "required": True,
            "priority": 100,
        },
    )
    resolved = mcp_tool(
        ADMIN_TOKEN,
        "memory_artifact_resolve",
        {"project_id": "project-1", "organization_id": "organization-1"},
    )
    assert len(resolved) == 1 and resolved[0]["version"] == "1.0.0", resolved
    fetched = mcp_tool(
        ADMIN_TOKEN,
        "memory_artifact_fetch",
        {
            "artifact_id": "demo",
            "kind": "foundation",
            "version": "1.0.0",
            "expected_artifact_digest": manifest["artifact_digest"],
        },
    )
    assert base64.b64decode(fetched["archive_base64"], validate=True) == archive
    assert fetched["archive_digest"] == publish["archive_digest"]

    handoff = handoff_arguments()
    first_push = mcp_tool(ADMIN_TOKEN, "memory_handoff_push", handoff)
    second_push = mcp_tool(ADMIN_TOKEN, "memory_handoff_push", handoff)
    assert first_push["already_exists"] is False
    assert second_push["already_exists"] is True and second_push["handoff_id"] == first_push["handoff_id"]
    pending = mcp_tool(ADMIN_TOKEN, "memory_handoff_list", {"project_id": "project-1"})
    assert [item["id"] for item in pending] == [first_push["handoff_id"]], pending

    status, cross_list, _ = request(
        "/tools/memory_handoff_list",
        token=CROSS_TOKEN,
        payload={"project_id": "project-1"},
    )
    assert status == 403 and cross_list["error"]["error_code"] == "MEM-AUTH-0003", cross_list
    status, cross_pull, _ = request(
        "/tools/memory_handoff_pull",
        token=CROSS_TOKEN,
        payload={"project_id": "project-1", "handoff_id": first_push["handoff_id"]},
    )
    assert status == 403 and cross_pull["error"]["error_code"] == "MEM-AUTH-0003", cross_pull

    pulled = mcp_tool(
        ADMIN_TOKEN,
        "memory_handoff_pull",
        {"project_id": "project-1", "handoff_id": first_push["handoff_id"]},
    )
    assert pulled["project_id"] == "project-1"
    assert pulled["from_user"] == "admin-1" and pulled["claimed_by"] == "admin-1", pulled

    status, invalid, _ = request(
        "/tools/memory_handoff_list",
        token=ADMIN_TOKEN,
        payload={"project_id": "project-1", "unexpected": True},
    )
    assert status == 400 and invalid["error"]["error_code"] == "MEM-TOOL-0002", invalid

    deleted = mcp_tool(
        ADMIN_TOKEN,
        "memory_policy_delete",
        {"organization_id": "organization-1", "policy_id": policy["id"]},
    )
    assert deleted == {"policy_id": policy["id"], "deleted": True}
    after_delete = mcp_tool(
        ADMIN_TOKEN,
        "memory_artifact_resolve",
        {"project_id": "project-1", "organization_id": "organization-1"},
    )
    assert after_delete == []

    print(
        json.dumps(
            {
                "ready": ready,
                "mcp_protocol": PROTOCOL_VERSION,
                "tool_count": len(names),
                "artifact_round_trip": True,
                "policy_upsert_delete": True,
                "handoff_idempotent_round_trip": True,
                "read_only_denied": True,
                "cross_project_denied": True,
                "schema_error_controlled": True,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
