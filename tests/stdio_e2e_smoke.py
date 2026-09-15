"""Exercise the installed stdio entry point against a migrated PostgreSQL DB."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any

from isekai_memory.server.protocol import PROTOCOL_VERSION


def request(identifier: int, method: str, params: dict[str, Any] | None = None) -> str:
    request_params = dict(params or {})
    request_params["_meta"] = {
        "io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION,
        "io.modelcontextprotocol/clientCapabilities": {},
        "io.modelcontextprotocol/clientInfo": {"name": "stdio-e2e", "version": "1"},
    }
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": identifier,
            "method": method,
            "params": request_params,
        },
        separators=(",", ":"),
    )


def main() -> None:
    environment = dict(os.environ)
    if not environment.get("ISEKAI_MEMORY_DATABASE_URL"):
        raise SystemExit("ISEKAI_MEMORY_DATABASE_URL is required")

    frames = "\n".join(
        [
            request(1, "server/discover"),
            request(2, "tools/list"),
            request(
                3,
                "tools/call",
                {
                    "name": "memory_handoff_list",
                    "arguments": {"project_id": "stdio-e2e-project"},
                },
            ),
            request(4, "initialize"),
            request(5, "tools/call", {"name": "memory_search", "arguments": {"project_id": "stdio-e2e-project", "query": "lease"}}),
            request(6, "tools/call", {"name": "memory_knowledge_list", "arguments": {"project_id": "stdio-e2e-project"}}),
            request(7, "tools/call", {"name": "memory_grant_list", "arguments": {"project_id": "stdio-e2e-project"}}),
            request(8, "tools/call", {"name": "memory_feedback_list", "arguments": {"project_id": "stdio-e2e-project"}}),
            request(9, "tools/call", {"name": "memory_handoff_inbox", "arguments": {"project_id": "stdio-e2e-project"}}),
            request(10, "tools/call", {"name": "memory_collaboration_overview", "arguments": {"project_id": "stdio-e2e-project"}}),
            request(11, "tools/call", {"name": "memory_collaboration_list", "arguments": {"project_id": "stdio-e2e-project", "view": "work"}}),
            "",
        ]
    )
    completed = subprocess.run(
        [sys.executable, "-m", "isekai_memory.main", "--mode", "stdio"],
        input=frames,
        text=True,
        capture_output=True,
        env=environment,
        timeout=20,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    responses = [json.loads(line) for line in completed.stdout.splitlines()]
    assert len(responses) == 11, responses

    discovered = responses[0]["result"]
    assert discovered["supportedVersions"] == [PROTOCOL_VERSION]
    assert discovered["ttlMs"] == 3_600_000 and discovered["cacheScope"] == "public"
    assert "serverInfo" not in discovered
    assert len(responses[1]["result"]["tools"]) == 82

    db_call = responses[2]["result"]
    assert db_call["isError"] is False, db_call
    assert db_call["structuredContent"] == [], db_call
    assert responses[3]["error"]["code"] == -32601
    assert responses[4]["result"]["isError"] is False
    assert responses[4]["result"]["structuredContent"]["items"] == []
    for response in responses[5:9]:
        assert response["result"]["isError"] is False and response["result"]["structuredContent"]["items"] == []
    overview = responses[9]["result"]["structuredContent"]
    assert responses[9]["result"]["isError"] is False and overview["actor_id"] == "local-stdio"
    assert overview["identity"]["local"] is True and overview["counts"]["work"]["value"] == 0
    assert overview["telemetry"]["idle"]["value"] is None
    assert responses[10]["result"]["isError"] is False
    assert responses[10]["result"]["structuredContent"]["items"] == []

    print(
        json.dumps(
            {
                "mcp_protocol": PROTOCOL_VERSION,
                "server_discover": True,
                "tool_count": 82,
                "experience_search": True,
                "database_tool_call": True,
                "initialize_rejected": True,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
