"""Project-authorized bounded metadata views; payloads and private claim hashes excluded."""

from fastapi.encoders import jsonable_encoder

from isekai_memory.continuity.common import CLASSIFICATIONS, ceiling, fail, is_admin, transaction
from isekai_memory.continuity.delivery import bundle
from isekai_memory.experience import pagination

UNIT_COLUMNS = "id,unit_key,summary,assignee_user_ids,state,claimed_by,claim_generation,lease_expires_at,updated_at"


async def status(arguments, *, principal):
    project = arguments["project_id"]
    async with transaction(project) as conn:
        parent = await bundle(conn, project, arguments["bundle_id"], retained=False)
        rows = await conn.fetch("SELECT id,recipient_user_id,routing_version,acknowledged_at,revoked_at,created_at "
                                "FROM memory_continuity_deliveries WHERE bundle_id=$1 ORDER BY (revoked_at IS NULL) DESC,created_at DESC,id DESC LIMIT 129", parent["id"])
        current = [row for row in rows if row["revoked_at"] is None]
        if not (is_admin(principal) or parent["from_user"] == principal.user_id or any(row["recipient_user_id"] == principal.user_id for row in current)):
            raise fail()
        ceiling(parent, arguments)
        units = await conn.fetch(f"SELECT {UNIT_COLUMNS} FROM memory_continuity_units WHERE bundle_id=$1 ORDER BY unit_key", parent["id"])
        return jsonable_encoder({"bundle": dict(parent), "deliveries": [dict(row) for row in rows[:128]], "delivery_history_truncated": len(rows) > 128,
                                 "units": [dict(row) for row in units],
                                 "intake": {"total": len(current), "acknowledged": sum(row["acknowledged_at"] is not None for row in current)},
                                 "observed_at": await conn.fetchval("SELECT clock_timestamp()"), "cache_policy": "no_store"})


async def listing(arguments, *, principal, view):
    project = arguments["project_id"]
    limit = arguments.get("limit", 20)
    scope = ["continuity-" + view, project, principal.user_id, str(is_admin(principal)),
             arguments.get("from_user_id", ""), arguments.get("work_id", ""), arguments.get("target_id", ""),
             arguments.get("max_classification", "internal"), str(arguments.get("include_acknowledged", False))]
    at, row_id = pagination.decode(arguments.get("cursor"), scope)
    async with transaction(project) as conn:
        if view == "checkpoints":
            actor = arguments.get("from_user_id") if is_admin(principal) else principal.user_id
            if not is_admin(principal) and arguments.get("from_user_id", actor) != actor:
                raise fail()
            rows = await conn.fetch("""
                SELECT id,work_id,from_user,version,classification,lock_snapshot_digest,continuation_digest,
                    snapshot_digest,payload_digest,created_at,expires_at,forgotten_at
                FROM memory_checkpoints WHERE project_id=$1
                AND ($2::timestamptz IS NULL OR (created_at,id)<($2,$3::uuid))
                AND ($5::text IS NULL OR from_user=$5) AND ($6::text IS NULL OR work_id=$6)
                ORDER BY created_at DESC,id DESC LIMIT $4
            """, project, at, row_id, limit + 1, actor, arguments.get("work_id"))
        elif view == "inbox":
            allowed = CLASSIFICATIONS[:CLASSIFICATIONS.index(arguments.get("max_classification", "internal")) + 1]
            rows = await conn.fetch("""
                SELECT d.id,d.bundle_id,d.recipient_user_id,d.routing_version,d.acknowledged_at,d.created_at,
                    b.from_user,b.classification,b.source_digest,b.expires_at,b.version AS current_routing_version
                FROM memory_continuity_deliveries d JOIN memory_continuity_bundles b ON b.id=d.bundle_id
                WHERE d.project_id=$1 AND d.recipient_user_id=$5 AND d.revoked_at IS NULL
                    AND b.revoked_at IS NULL AND b.expires_at>clock_timestamp()
                    AND (d.acknowledged_at IS NULL OR $6::boolean) AND b.classification=ANY($7::text[])
                    AND ($2::timestamptz IS NULL OR (d.created_at,d.id)<($2,$3::uuid))
                ORDER BY d.created_at DESC,d.id DESC LIMIT $4
            """, project, at, row_id, limit + 1, principal.user_id, arguments.get("include_acknowledged", False), allowed)
        elif view == "history":
            rows = await conn.fetch("SELECT id,target_id,actor_id,action,details,created_at FROM memory_continuity_events WHERE project_id=$1 "
                                    "AND ($2::timestamptz IS NULL OR (created_at,id)<($2,$3::uuid)) AND ($5::text IS NULL OR target_id=$5) "
                                    "ORDER BY created_at DESC,id DESC LIMIT $4", project, at, row_id, limit + 1, arguments.get("target_id"))
        else:
            raise ValueError("Unknown internal continuity view")
        result = pagination.page([dict(row) for row in rows], limit, scope)
        return jsonable_encoder({**result, "observed_at": await conn.fetchval("SELECT clock_timestamp()"), "cache_policy": "no_store"})


async def members(arguments, *, principal):
    # Reuse a scoped cursor with a deterministic synthetic UUID per user and first token time.
    scope = ["continuity-members", arguments["project_id"], principal.user_id]
    at, row_id = pagination.decode(arguments.get("cursor"), scope)
    limit = arguments.get("limit", 20)
    async with transaction(arguments["project_id"]) as conn:
        rows = await conn.fetch("""
            SELECT * FROM (
                SELECT user_id, md5(user_id)::uuid AS id, created_at
                FROM memory_eligible_members WHERE project_id=$1
            ) identities WHERE $2::timestamptz IS NULL OR (created_at,id)<($2,$3::uuid)
            ORDER BY created_at DESC,id DESC LIMIT $4
        """, arguments["project_id"], at, row_id, limit + 1)
        result = pagination.page([dict(row) for row in rows], limit, scope)
        result["items"] = [{"user_id": row["user_id"]} for row in result["items"]]
        return {**result, "cache_policy": "no_store"}
