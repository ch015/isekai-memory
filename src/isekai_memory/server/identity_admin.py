"""Local operator identity binding/disable commands; never accessible as MCP tools."""

import json
from uuid import UUID

from isekai_memory.store.database import close_pool, get_pool, init_pool
from isekai_memory.store.identities import bind_legacy


async def administer(settings, args):
    tenant = str(UUID(args.tenant_id or settings.entra.tenant_id))
    await init_pool(settings)
    try:
        if args.bind_entra_user:
            result = await bind_legacy(tenant, args.bind_entra_user, args.user_id, settings.entra.organization_id)
        else:
            oid = str(UUID(args.disable_entra_user or args.enable_entra_user))
            disabled = bool(args.disable_entra_user)
            async with get_pool().acquire() as conn:
                row = await conn.fetchrow(
                    """UPDATE memory_identities SET disabled_at=CASE WHEN $3 THEN now() ELSE NULL END
                    WHERE tenant_id=$1 AND object_id=$2 RETURNING user_id""",
                    tenant,
                    oid,
                    disabled,
                )
            if row is None:
                raise ValueError("Identity is not registered")
            result = {"user_id": row["user_id"], "disabled": disabled}
        print(json.dumps(result))
    finally:
        await close_pool()
