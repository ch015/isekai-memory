"""HTTP token authentication and tool authorization."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from isekai_memory.server.errors import MemoryToolError
from isekai_memory.store import queries


@dataclass(frozen=True)
class Principal:
    user_id: str
    project_id: str | None
    scopes: frozenset[str]
    local: bool = False

    @classmethod
    def local_stdio(cls) -> Principal:
        return cls(user_id="local-stdio", project_id=None, scopes=frozenset({"read", "write", "admin"}), local=True)


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


async def verify_token(raw_token: str | None) -> Principal:
    if not raw_token:
        raise MemoryToolError(
            "Authentication token is required",
            data={"error_code": "MEM-AUTH-0001"},
            http_status=401,
        )
    record = await queries.get_token_by_hash(token_hash=hash_token(raw_token))
    if record is None or record["revoked_at"] is not None:
        raise MemoryToolError(
            "Invalid or revoked authentication token",
            data={"error_code": "MEM-AUTH-0001"},
            http_status=401,
        )
    if record["expires_at"] is not None and record["expires_at"] <= datetime.now(UTC):
        raise MemoryToolError(
            "Authentication token has expired",
            data={"error_code": "MEM-AUTH-0001"},
            http_status=401,
        )
    return Principal(
        user_id=record["user_id"],
        project_id=record["project_id"],
        scopes=frozenset(record["scopes"]),
    )


_TOOL_SCOPES = {
    "memory_artifact_resolve": "read",
    "memory_artifact_fetch": "read",
    "memory_artifact_publish": "write",
    "memory_policy_upsert": "admin",
    "memory_policy_delete": "admin",
    "memory_handoff_push": "write",
    "memory_handoff_list": "read",
    "memory_handoff_pull": "write",
    "memory_handoff_claim": "write",
    "memory_handoff_get_claimed": "write",
    "memory_handoff_ack": "write",
    "memory_handoff_nack": "write",
}
_PROJECT_SCOPED_TOOLS = {
    "memory_artifact_resolve",
    "memory_handoff_push",
    "memory_handoff_list",
    "memory_handoff_pull",
    "memory_handoff_claim",
    "memory_handoff_get_claimed",
    "memory_handoff_ack",
    "memory_handoff_nack",
}


def authorize_tool(principal: Principal, tool_name: str, arguments: dict[str, Any]) -> None:
    required_scope = _TOOL_SCOPES.get(tool_name)
    if required_scope is None:
        raise MemoryToolError(
            f"Unknown tool: {tool_name}",
            code=-32602,
            data={"error_code": "MEM-TOOL-0001"},
            http_status=404,
        )
    if not principal.local and required_scope not in principal.scopes and "admin" not in principal.scopes:
        raise MemoryToolError(
            f"Scope '{required_scope}' is required",
            data={"error_code": "MEM-AUTH-0002", "required_scope": required_scope},
            http_status=403,
        )
    if tool_name in _PROJECT_SCOPED_TOOLS and not principal.local:
        requested_project = arguments.get("project_id")
        if not requested_project or requested_project != principal.project_id:
            raise MemoryToolError(
                "Request project does not match token project",
                data={"error_code": "MEM-AUTH-0003"},
                http_status=403,
            )
