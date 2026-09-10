"""Reference manifests, never persisted copies of forgotten experience plaintext."""

import asyncio

import asyncpg

from isekai_memory.experience.service import CLASSIFICATIONS
from isekai_memory.retrieval.citations import attach, canonical, digest
from isekai_memory.server.errors import MemoryToolError
from isekai_memory.store.database import get_pool


def scope(arguments: dict) -> dict:
    return {key: arguments.get(key, default) for key, default in (
        ("phase_id", None), ("max_classification", "internal"), ("source_lock_digest", None),
    )}


async def materialize(conn, project_id: str, view: dict) -> dict:
    """One bounded, canonical view; filters precede ordering/limits and citations."""
    classifications = list(CLASSIFICATIONS[:CLASSIFICATIONS.index(view["max_classification"]) + 1])
    rows = await conn.fetch("""
        SELECT m.id,m.project_id,m.version,m.classification,m.kind,m.title,m.content,m.tags,
               m.source_handoff_id,m.source_lock_digest,m.source_payload_digest,
               count(*) OVER () AS total
        FROM memory_experiences m JOIN handoffs h ON h.id=m.source_handoff_id AND h.project_id=m.project_id
        WHERE m.project_id=$1 AND m.status='active'
          AND (m.valid_from IS NULL OR m.valid_from <= statement_timestamp())
          AND (m.expires_at IS NULL OR m.expires_at > statement_timestamp())
          AND m.classification=ANY($2::text[]) AND h.classification=ANY($2::text[])
          AND ($3::text IS NULL OR h.phase_id=$3)
          AND ($4::text IS NULL OR m.source_lock_digest=$4)
          AND m.source_payload_digest=h.payload_digest AND m.source_lock_digest=h.lock_snapshot_digest
          AND m.source->>'envelope_digest'=h.envelope_digest
          AND m.source->>'classification'=h.classification
        ORDER BY m.updated_at DESC,m.id DESC LIMIT 50
    """, project_id, classifications, view["phase_id"], view["source_lock_digest"])
    total = rows[0]["total"] if rows else 0
    items = [attach({k: v for k, v in dict(row).items() if k != "total"}) for row in rows]
    dependencies = [{"memory_id": item["memory_id"], "version": item["version"],
                     "binding_digest": item["citation"]["binding_digest"]} for item in items]
    watermark = digest(canonical({"project_id": project_id, "scope": view, "total": total, "sources": dependencies}))
    return {"items": items, "dependencies": dependencies, "source_count": total, "source_watermark": watermark}


async def read(arguments: dict) -> dict:
    try:
        async with asyncio.timeout(2.5):
            return await _read(arguments)
    except (TimeoutError, asyncpg.QueryCanceledError) as exc:
        raise MemoryToolError("Summary read exceeded its time budget", http_status=503,
                              data={"error_code": "MEM-GENERATION-0004"}) from exc


async def _read(arguments: dict) -> dict:
    project_id, view = arguments["project_id"], scope(arguments)
    async with get_pool().acquire() as conn, conn.transaction(isolation="repeatable_read", readonly=True):
        await conn.execute("SET LOCAL statement_timeout='2s'")
        current = await materialize(conn, project_id, view)
        snapshot = await conn.fetchrow("""
            SELECT job_id,source_watermark FROM memory_summary_snapshots
            WHERE project_id=$1 AND scope=$2::jsonb
            ORDER BY (source_watermark=$3) DESC,created_at DESC,job_id DESC LIMIT 1
        """, project_id, view, current["source_watermark"])
    status = "missing" if snapshot is None else (
        "ready" if snapshot["source_watermark"] == current["source_watermark"] else "stale"
    )
    budget = arguments.get("max_chars", 8000)
    items, used = [], 2
    if status == "ready":
        for item in current["items"]:
            size = len(canonical(item)) + int(bool(items))
            if used + size > budget:
                break
            items.append(item)
            used += size
    return {
        "status": status, "snapshot_id": str(snapshot["job_id"]) if status == "ready" else None,
        "scope": view, "source_watermark": current["source_watermark"] if status == "ready" else None,
        "items": items, "source_count": current["source_count"] if status == "ready" else 0,
        "returned": len(items), "truncated": status == "ready" and len(items) < current["source_count"],
        "result_chars": used, "max_chars": budget, "usage": "reference_only", "citation_schema_version": 1,
        "strategy": "approved_references_v1",
    }
