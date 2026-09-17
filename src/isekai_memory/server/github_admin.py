"""Local operator controls for GitHub identity bindings."""

import json

from isekai_memory.server.github_config import subject
from isekai_memory.store.database import close_pool, get_pool, init_pool
from isekai_memory.store.github_identities import bind_legacy


async def administer(settings, args):
    github_id = subject(args.bind_github_user or args.disable_github_user or args.enable_github_user)
    await init_pool(settings)
    try:
        if args.bind_github_user:
            result = await bind_legacy(github_id, args.user_id, settings.github.organization_id)
        else:
            disabled = bool(args.disable_github_user)
            async with get_pool().acquire() as conn:
                row = await conn.fetchrow(
                    """UPDATE memory_github_identities SET disabled_at=CASE WHEN $2 THEN now() ELSE NULL END
                    WHERE github_id=$1 RETURNING user_id""",
                    github_id,
                    disabled,
                )
            if row is None:
                raise ValueError("Identity is not registered")
            result = {"user_id": row["user_id"], "disabled": disabled}
        print(json.dumps(result))
    finally:
        await close_pool()
