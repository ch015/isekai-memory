"""Verified tenant/object identity bindings; never merge by email or display name."""

from uuid import UUID

from isekai_memory.server.errors import MemoryToolError
from isekai_memory.store.database import get_pool


async def resolve(tenant_id: str, object_id: str, organization_id: str) -> str:
    actor = f"entra:{tenant_id}:{object_id}"
    async with get_pool().acquire() as conn:
        await conn.execute(
            """INSERT INTO memory_identities(tenant_id,object_id,user_id,organization_id)
            VALUES($1,$2,$3,$4) ON CONFLICT(tenant_id,object_id) DO NOTHING""",
            tenant_id,
            object_id,
            actor,
            organization_id,
        )
        row = await conn.fetchrow(
            "SELECT user_id,organization_id,disabled_at FROM memory_identities WHERE tenant_id=$1 AND object_id=$2",
            tenant_id,
            object_id,
        )
    if row["disabled_at"] is not None or row["organization_id"] != organization_id:
        raise MemoryToolError(
            "Company account access is disabled", data={"error_code": "MEM-AUTH-DISABLED"}, http_status=403
        )
    return row["user_id"]


async def bind_legacy(tenant_id: str, object_id: str, user_id: str, organization_id: str):
    """Operator-only pre-login binding. Refuse to move an identity that already owns history."""
    tenant_id, object_id = str(UUID(tenant_id)), str(UUID(object_id))
    if not user_id or len(user_id) > 128 or not organization_id or len(organization_id) > 128:
        raise ValueError("Explicit user and organization identifiers are required")
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO memory_identities(tenant_id,object_id,user_id,organization_id)
            VALUES($1,$2,$3,$4) ON CONFLICT DO NOTHING RETURNING user_id""",
            tenant_id,
            object_id,
            user_id,
            organization_id,
        )
    if row is None:
        raise ValueError("Identity/user is already bound; no existing ownership was changed")
    return {"user_id": user_id, "bound": True}
