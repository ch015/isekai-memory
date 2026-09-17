"""Immutable GitHub IDs, independent of usernames, email and Entra identities."""

from isekai_memory.server.errors import MemoryToolError
from isekai_memory.server.github_config import subject
from isekai_memory.store.database import get_pool


async def resolve(github_id: str, organization_id: str) -> str:
    github_id = subject(github_id)
    async with get_pool().acquire() as conn:
        await conn.execute(
            """INSERT INTO memory_github_identities(github_id,user_id,organization_id)
            VALUES($1,$2,$3) ON CONFLICT(github_id) DO NOTHING""",
            github_id,
            f"github:{github_id}",
            organization_id,
        )
        row = await conn.fetchrow(
            "SELECT user_id,organization_id,disabled_at FROM memory_github_identities WHERE github_id=$1", github_id
        )
    if row["disabled_at"] is not None or row["organization_id"] != organization_id:
        raise MemoryToolError(
            "GitHub account access is disabled", data={"error_code": "MEM-AUTH-DISABLED"}, http_status=403
        )
    return row["user_id"]


async def bind_legacy(github_id: str, user_id: str, organization_id: str):
    github_id = subject(github_id)
    if not user_id or len(user_id) > 128 or organization_id != "DevSecOps":
        raise ValueError("Explicit user ID and DevSecOps organization are required")
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO memory_github_identities(github_id,user_id,organization_id)
            VALUES($1,$2,$3) ON CONFLICT DO NOTHING RETURNING user_id""",
            github_id,
            user_id,
            organization_id,
        )
    if row is None:
        raise ValueError("Identity/user is already bound; no existing ownership was changed")
    return {"user_id": user_id, "bound": True}
