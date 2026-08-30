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
    assert len(responses) == 4, responses

    discovered = responses[0]["result"]
    assert discovered["supportedVersions"] == [PROTOCOL_VERSION]
    assert discovered["ttlMs"] == 3_600_000 and discovered["cacheScope"] == "public"
    assert "serverInfo" not in discovered
    assert len(responses[1]["result"]["tools"]) == 12

    db_call = responses[2]["result"]
    assert db_call["isError"] is False, db_call
    assert db_call["structuredContent"] == [], db_call
    assert responses[3]["error"]["code"] == -32601

    print(
        json.dumps(
            {
                "mcp_protocol": PROTOCOL_VERSION,
                "server_discover": True,
                "tool_count": 12,
                "database_tool_call": True,
                "initialize_rejected": True,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
