"""Admin inspection and fresh active-only reads; no generation side effects."""

import asyncio

import asyncpg
from fastapi.encoders import jsonable_encoder

from isekai_memory.experience import pagination
from isekai_memory.experience.service import CLASSIFICATIONS
from isekai_memory.skills import sources
from isekai_memory.skills.sources import fail
from isekai_memory.store.database import get_pool


async def get(conn, arguments, *, admin=False):
    row = await conn.fetchrow("""
        SELECT r.*,s.name FROM memory_skill_revisions r JOIN memory_skills s ON s.id=r.skill_id
        WHERE r.id=$1::uuid AND r.project_id=$2
    """, arguments["revision_id"], arguments["project_id"])
    if row is None:
        raise fail(status=404)
    if not admin and (
        row["status"] != "active"
        or CLASSIFICATIONS.index(row["classification"]) > CLASSIFICATIONS.index(arguments.get("max_classification", "internal"))
        or (arguments.get("source_lock_digest") and row["source_lock_digest"] != arguments["source_lock_digest"])
        or ("expected_version" in arguments and row["version"] != arguments["expected_version"])
    ):
        raise fail(status=404)
    bindings = await sources.saved(conn, row)
    fresh, evidence = await sources.freshness(conn, row, bindings)
    if not admin and not fresh:
        raise fail(status=404)
    result = {key: value for key, value in dict(row).items() if key not in {"id", "idempotency_key", "submission_digest"}}
    result.update(revision_id=row["id"], sources=bindings, fresh=fresh)
    if admin:
        result["source_evidence"] = evidence if fresh else []
        result["events"] = [dict(event) for event in await conn.fetch(
            "SELECT version,actor_id,action,previous_status,applied_status,cause_memory_id,created_at "
            "FROM memory_skill_events WHERE revision_id=$1 ORDER BY version", row["id"])]
    return jsonable_encoder(result)


async def read(arguments, *, admin=False):
    try:
        async with asyncio.timeout(3), get_pool().acquire() as conn, conn.transaction(isolation="repeatable_read", readonly=True):
            await conn.execute("SET LOCAL statement_timeout='2s'")
            return {"skill": await get(conn, arguments, admin=admin), "usage": "review_only" if admin else "reference_only"}
    except (TimeoutError, asyncpg.QueryCanceledError) as exc:
        raise fail("Skill read exceeded its time budget", "MEM-SKILL-0006", 503) from exc


async def list_revisions(arguments):
    skill_id = arguments.get("skill_id")
    status = arguments.get("status", "pending")
    view = ["skills", arguments["project_id"], skill_id or "*", arguments.get("status", "*" if skill_id else "pending")]
    at, row_id = pagination.decode(arguments.get("cursor"), view)
    limit = arguments.get("limit", 10)
    async with get_pool().acquire() as conn:
        rows = await conn.fetch("""
            SELECT r.id,r.skill_id,r.project_id,s.name,r.revision,r.version,r.status,r.origin,r.classification,
                   r.source_lock_digest,r.source_watermark,r.content_digest,r.created_by,r.created_at,r.updated_at
            FROM memory_skill_revisions r JOIN memory_skills s ON s.id=r.skill_id
            WHERE r.project_id=$1 AND ($2::uuid IS NULL OR r.skill_id=$2)
              AND ($3::text IS NULL OR r.status=$3)
              AND ($5::timestamptz IS NULL OR (r.created_at,r.id)<($5,$6::uuid))
            ORDER BY r.created_at DESC,r.id DESC LIMIT $4
        """, arguments["project_id"], skill_id, None if skill_id and "status" not in arguments else status, limit + 1, at, row_id)
    result = pagination.page([dict(row) for row in rows], limit, view)
    for row in result["items"]:
        row["revision_id"] = row.pop("id")
    return jsonable_encoder(result)
