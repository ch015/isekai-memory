"""PostgreSQL-backed HTTP E2E smoke test for a migrated Memory server.

Required environment variables: MEMORY_BASE_URL, MEMORY_ADMIN_TOKEN,
MEMORY_READ_TOKEN, and MEMORY_CROSS_PROJECT_TOKEN.
"""

from __future__ import annotations

import json
import os
import secrets
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from isekai_memory.store.database import EXPECTED_SCHEMA_REVISION

sys.path.insert(0, str(Path(__file__).parent))
from helpers import handoff_arguments  # noqa: E402

from isekai_memory.server.protocol import PROTOCOL_VERSION
from isekai_memory.server.tools import TOOL_NAMES

BASE_URL = os.environ["MEMORY_BASE_URL"].rstrip("/")
ADMIN_TOKEN = os.environ["MEMORY_ADMIN_TOKEN"]
READ_TOKEN = os.environ["MEMORY_READ_TOKEN"]
CROSS_TOKEN = os.environ["MEMORY_CROSS_PROJECT_TOKEN"]
PROJECT_ID = os.environ.get("MEMORY_TEST_PROJECT_ID", "project-1")


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
    assert status == 200 and ready == {"database": "ok", "schema_revision": EXPECTED_SCHEMA_REVISION}, ready

    discovered = mcp("server/discover", token=ADMIN_TOKEN)
    assert discovered["supportedVersions"] == [PROTOCOL_VERSION]
    assert discovered["ttlMs"] == 3_600_000 and discovered["cacheScope"] == "public"
    assert "serverInfo" not in discovered
    assert discovered["_meta"]["io.modelcontextprotocol/serverInfo"]["name"] == "isekai-memory"
    listed = mcp("tools/list", token=ADMIN_TOKEN)
    names = {tool["name"] for tool in listed["tools"]}
    assert names == TOOL_NAMES, names
    assert "memory_search" in names and "memory_experience_review" in names
    assert "memory_artifact_publish" not in names
    assert isinstance(mcp_tool(ADMIN_TOKEN, "memory_repo_list", {}), list)

    handoff = handoff_arguments()
    handoff["project_id"] = PROJECT_ID
    status, denied, _ = request("/tools/memory_handoff_push", token=READ_TOKEN, payload=handoff)
    assert status == 403 and denied["error"]["error_code"] == "MEM-AUTH-0002", denied
    first_push = mcp_tool(ADMIN_TOKEN, "memory_handoff_push", handoff)
    second_push = mcp_tool(ADMIN_TOKEN, "memory_handoff_push", handoff)
    assert first_push["already_exists"] is False
    assert second_push["already_exists"] is True and second_push["handoff_id"] == first_push["handoff_id"]
    pending = mcp_tool(ADMIN_TOKEN, "memory_handoff_list", {"project_id": PROJECT_ID})
    assert [item["id"] for item in pending] == [first_push["handoff_id"]], pending

    status, cross_list, _ = request(
        "/tools/memory_handoff_list",
        token=CROSS_TOKEN,
        payload={"project_id": PROJECT_ID},
    )
    assert status == 403 and cross_list["error"]["error_code"] == "MEM-AUTH-0003", cross_list
    status, cross_pull, _ = request(
        "/tools/memory_handoff_pull",
        token=CROSS_TOKEN,
        payload={"project_id": PROJECT_ID, "handoff_id": first_push["handoff_id"]},
    )
    assert status == 403 and cross_pull["error"]["error_code"] == "MEM-AUTH-0003", cross_pull

    pulled = mcp_tool(
        ADMIN_TOKEN,
        "memory_handoff_pull",
        {"project_id": PROJECT_ID, "handoff_id": first_push["handoff_id"]},
    )
    assert pulled["project_id"] == PROJECT_ID
    assert pulled["from_user"] == pulled["claimed_by"], pulled

    status, invalid, _ = request(
        "/tools/memory_handoff_list",
        token=ADMIN_TOKEN,
        payload={"project_id": PROJECT_ID, "unexpected": True},
    )
    assert status == 400 and invalid["error"]["error_code"] == "MEM-TOOL-0002", invalid

    proposal = {
        "project_id": PROJECT_ID, "source_handoff_id": first_push["handoff_id"],
        "idempotency_key": secrets.token_urlsafe(16), "kind": "lesson",
        "title": "인증 모듈 재시도", "content": "Keep lease receipts after response loss.",
    }
    proposed = mcp_tool(ADMIN_TOKEN, "memory_experience_propose", proposal)
    memory_id = proposed["memory_id"]
    assert mcp_tool(ADMIN_TOKEN, "memory_experience_propose", proposal)["already_exists"]
    search_args = {"project_id": PROJECT_ID, "query": "인증 모듈"}
    assert mcp_tool(READ_TOKEN, "memory_search", search_args)["items"] == []
    review_args = {"project_id": PROJECT_ID, "memory_id": memory_id, "action": "approve", "expected_version": 1}
    status, denied, _ = request("/tools/memory_experience_review", token=READ_TOKEN, payload=review_args)
    assert status == 403 and denied["error"]["error_code"] == "MEM-AUTH-0002", denied
    assert mcp_tool(ADMIN_TOKEN, "memory_experience_review", review_args)["applied_version"] == 2
    found = mcp_tool(READ_TOKEN, "memory_search", search_args)
    assert [item["memory_id"] for item in found["items"]] == [memory_id]
    read_args = {"project_id": PROJECT_ID, "memory_id": memory_id}
    read = mcp_tool(READ_TOKEN, "memory_read", read_args)
    assert read["memory"]["source"]["id"] == first_push["handoff_id"]
    status, denied, _ = request("/tools/memory_read", token=CROSS_TOKEN, payload=read_args)
    assert status == 403 and denied["error"]["error_code"] == "MEM-AUTH-0003", denied
    revised = mcp_tool(ADMIN_TOKEN, "memory_experience_revise", {
        "project_id": PROJECT_ID, "memory_id": memory_id, "expected_version": 2,
        "idempotency_key": secrets.token_urlsafe(16), "kind": "lesson",
        "title": "인증 모듈 정정", "content": "Keep generation fencing with lease receipts.",
    })
    child = revised["memory_id"]
    mcp_tool(ADMIN_TOKEN, "memory_experience_review", {**review_args, "memory_id": child})
    assert [item["memory_id"] for item in mcp_tool(READ_TOKEN, "memory_search", search_args)["items"]] == [child]
    history = mcp_tool(ADMIN_TOKEN, "memory_experience_history", read_args)
    assert len(history["items"]) == 2 and history["suppression"]["reason"] == "superseded"
    status, blocked, _ = request("/tools/memory_experience_propose", token=ADMIN_TOKEN, payload={**proposal, "idempotency_key": secrets.token_urlsafe(16)})
    assert status == 409 and blocked["error"]["error_code"] == "MEM-EXPERIENCE-0007"
    release = {**read_args, "expected_suppression_version": history["suppression"]["version"]}
    mcp_tool(ADMIN_TOKEN, "memory_experience_suppression_release", release)
    assert mcp_tool(ADMIN_TOKEN, "memory_experience_suppression_release", release)["already_released"]
    mcp_tool(ADMIN_TOKEN, "memory_experience_review", {**review_args, "memory_id": child, "action": "archive", "expected_version": 2})
    assert mcp_tool(READ_TOKEN, "memory_search", search_args)["items"] == []
    mcp_tool(ADMIN_TOKEN, "memory_experience_review", {**review_args, "memory_id": child, "action": "forget", "expected_version": 3})
    history = mcp_tool(ADMIN_TOKEN, "memory_experience_history", {**read_args, "memory_id": child})
    tombstone = next(item for item in history["items"] if item["memory_id"] == child)
    assert tombstone["content"] == "[forgotten]" and tombstone["source"] == {}

    print(
        json.dumps(
            {
                "ready": ready,
                "mcp_protocol": PROTOCOL_VERSION,
                "tool_count": len(names),
                "repository_list": True,
                "experience_review_search_read_archive": True,
                "experience_revision_suppression_forget": True,
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
