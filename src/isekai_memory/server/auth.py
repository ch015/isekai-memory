"""HTTP token authentication and tool authorization."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from isekai_memory.server.errors import MemoryToolError
from isekai_memory.store import queries
from isekai_memory.team.tools import TEAM_SCOPES


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
    "memory_repo_list": "read",
    "memory_repo_check_updates": "read",
    "memory_handoff_push": "write",
    "memory_handoff_list": "read",
    "memory_handoff_pull": "write",
    "memory_handoff_claim": "write",
    "memory_handoff_get_claimed": "write",
    "memory_handoff_ack": "write",
    "memory_handoff_nack": "write",
    "memory_experience_propose": "write",
    "memory_experience_list": "admin",
    "memory_experience_review": "admin",
    "memory_experience_revise": "admin",
    "memory_experience_history": "admin",
    "memory_experience_suppression_release": "admin",
    "memory_search": "read",
    "memory_read": "read",
    "memory_generation_enqueue": "admin",
    "memory_generation_list": "admin",
    "memory_generation_retry": "admin",
    "memory_summary_read": "read",
    "memory_skill_generate": "admin",
    "memory_skill_propose": "write",
    "memory_skill_revise": "admin",
    "memory_skill_review": "admin",
    "memory_skill_list": "admin",
    "memory_skill_inspect": "admin",
    "memory_skill_read": "read",
    "memory_skill_export": "admin",
}
_PROJECT_SCOPED_TOOLS = {
    "memory_handoff_push",
    "memory_handoff_list",
    "memory_handoff_pull",
    "memory_handoff_claim",
    "memory_handoff_get_claimed",
    "memory_handoff_ack",
    "memory_handoff_nack",
    "memory_experience_propose",
    "memory_experience_list",
    "memory_experience_review",
    "memory_experience_revise",
    "memory_experience_history",
    "memory_experience_suppression_release",
    "memory_search",
    "memory_read",
    "memory_generation_enqueue",
    "memory_generation_list",
    "memory_generation_retry",
    "memory_summary_read",
    "memory_skill_generate",
    "memory_skill_propose",
    "memory_skill_revise",
    "memory_skill_review",
    "memory_skill_list",
    "memory_skill_inspect",
    "memory_skill_read",
    "memory_skill_export",
}


_TOOL_SCOPES.update(TEAM_SCOPES)
_PROJECT_SCOPED_TOOLS.update(TEAM_SCOPES)


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
