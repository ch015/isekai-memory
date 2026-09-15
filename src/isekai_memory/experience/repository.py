"""Project-scoped retrieval and bounded administrative audit views."""

from __future__ import annotations

from typing import Any

from isekai_memory.experience import pagination
from isekai_memory.experience.lifecycle import release_suppression as release_suppression
from isekai_memory.experience.lifecycle import review as review
from isekai_memory.experience.persistence import missing
from isekai_memory.experience.submissions import propose as propose
from isekai_memory.store.database import get_pool

_PUBLIC_COLUMNS = """
    id, project_id, source_handoff_id, source, source_lock_digest, classification,
    kind, title, content, tags, status, version, created_by, expires_at, created_at, updated_at, source_payload_digest,
    valid_from, supersedes_id, supersedes_version, revision_root_id, revision_number, is_correction
"""


async def list_for_review(*, project_id: str, status: str, limit: int, offset: int, cursor: str | None = None,
                          actor_id: str | None = None, metadata_only: bool = False,
                          maximum: str = "restricted", memory_id: str | None = None) -> dict:
    from isekai_memory.continuity.overview import read_transaction

    levels = ("public", "internal", "confidential", "restricted")
    scope = ["queue-v2", project_id, actor_id, status, maximum, str(metadata_only), memory_id]
    at, row_id = pagination.decode(cursor, scope)
    columns = _PUBLIC_COLUMNS
    if metadata_only:
        columns = ",".join(key.strip() for key in columns.split(",") if key.strip() not in {"source", "content", "tags"})
    async with read_transaction() as conn:
        now = await conn.fetchval("SELECT transaction_timestamp()")
        rows = await conn.fetch(
            f"SELECT {columns}, (expires_at <= now()) IS TRUE AS expired "
            "FROM memory_experiences WHERE project_id=$1 AND status=$2 "
            "AND ($5::timestamptz IS NULL OR (created_at,id)<($5,$6::uuid)) "
            "AND classification=ANY($7::text[]) AND ($8::uuid IS NULL OR id=$8) "
            "ORDER BY created_at DESC, id DESC LIMIT $3 OFFSET $4",
            project_id, status, limit + 1, offset, at, row_id,
            list(levels[:levels.index(maximum) + 1]), memory_id,
        )
    result = pagination.page([dict(row) for row in rows], limit, scope, offset if cursor is None else None)
    result.setdefault("next_offset", None)
    return {**result, "project_id": project_id, "actor_id": actor_id, "observed_at": now,
            "cache_policy": "no_store", "metadata_only": metadata_only, "max_classification": maximum}


async def history(*, project_id: str, memory_id: str, limit: int, cursor: str | None = None) -> dict:
    async with get_pool().acquire() as conn, conn.transaction(isolation="repeatable_read", readonly=True):
        target = await conn.fetchrow(
            "SELECT coalesce(revision_root_id,id) AS root_id,source_payload_digest,content_fingerprint "
            "FROM memory_experiences WHERE id=$1::uuid AND project_id=$2",
            memory_id,
            project_id,
        )
        if target is None:
            raise missing()
        scope = ["history", project_id, str(target["root_id"])]
        at, row_id = pagination.decode(cursor, scope)
        rows = await conn.fetch(
            f"SELECT {_PUBLIC_COLUMNS} FROM memory_experiences "
            "WHERE project_id=$1 AND coalesce(revision_root_id,id)=$2 "
            "AND ($4::timestamptz IS NULL OR (created_at,id)<($4,$5::uuid)) "
            "ORDER BY created_at DESC,id DESC LIMIT $3",
            project_id,
            target["root_id"],
            limit + 1,
            at,
            row_id,
        )
        result = pagination.page([dict(row) for row in rows], limit, scope)
        events = await conn.fetch(
            "SELECT memory_id,version,actor_id,action,previous_status,applied_status,related_memory_id,created_at "
            "FROM memory_experience_events WHERE memory_id=ANY($1::uuid[]) ORDER BY memory_id,version",
            [row["id"] for row in result["items"]],
        )
        grouped = {}
        for event in events:
            grouped.setdefault(event["memory_id"], []).append(dict(event))
        for row in result["items"]:
            row["events"] = grouped.get(row["id"], [])
        suppression = await conn.fetchrow(
            "SELECT memory_id,reason,version,updated_by,updated_at,released_at FROM memory_experience_suppressions "
            "WHERE project_id=$1 AND source_payload_digest=$2 AND content_fingerprint=$3",
            project_id,
            target["source_payload_digest"],
            target["content_fingerprint"],
        )
        result.update(
            memory_id=memory_id,
            revision_root_id=str(target["root_id"]),
            suppression=dict(suppression) if suppression else None,
        )
        return result


async def read(
    *,
    project_id: str,
    memory_id: str,
    classifications: list[str],
    source_lock_digest: str | None,
) -> dict[str, Any]:
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            f"SELECT {_PUBLIC_COLUMNS} FROM memory_experiences "
            "WHERE id=$1::uuid AND project_id=$2 AND status='active' "
            "AND (valid_from IS NULL OR valid_from <= now()) "
            "AND (expires_at IS NULL OR expires_at > now()) AND classification=ANY($3::text[]) "
            "AND ($4::text IS NULL OR source_lock_digest=$4)",
            memory_id,
            project_id,
            classifications,
            source_lock_digest,
        )
    if row is None:
        raise missing()
    return dict(row)
