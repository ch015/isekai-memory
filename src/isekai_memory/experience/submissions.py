"""Immutable proposals and admin corrections, with durable idempotency receipts."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from isekai_memory.experience.persistence import ensure_not_suppressed, error, lock_project, missing
from isekai_memory.store.database import get_pool

_CLASSIFICATIONS = ("public", "internal", "confidential", "restricted")


@asynccontextmanager
async def _transaction(connection):
    if connection is not None:
        # Internal generation completion owns this transaction and project lock.
        yield connection
    else:
        async with get_pool().acquire() as conn, conn.transaction():
            yield conn


async def propose(
    *,
    project_id: str,
    actor_id: str,
    source_handoff_id: str | None,
    idempotency_key: str,
    kind: str,
    title: str,
    content: str,
    tags: list[str],
    search_text: str,
    submission_digest: str,
    content_fingerprint: str,
    expires_at: datetime | None,
    valid_from: datetime | None = None,
    memory_id: str | None = None,
    expected_version: int | None = None,
    connection=None,
) -> dict[str, Any]:
    async with _transaction(connection) as conn:
        await lock_project(conn, project_id)
        # First check the durable receipt, including after forget/source deletion.
        existing = await conn.fetchrow(
            "SELECT id, submission_digest FROM memory_experiences "
            "WHERE project_id=$1 AND created_by=$2 AND idempotency_key=$3",
            project_id,
            actor_id,
            idempotency_key,
        )
        if existing is not None:
            if existing["submission_digest"] != submission_digest:
                raise error("Idempotency key already identifies a different proposal", "MEM-EXPERIENCE-0002")
            return {"memory_id": str(existing["id"]), "already_exists": True}
        parent = None
        if memory_id is not None:
            parent = await conn.fetchrow(
                "SELECT * FROM memory_experiences WHERE id=$1::uuid AND project_id=$2 FOR UPDATE",
                memory_id,
                project_id,
            )
            if parent is None:
                raise missing()
            if parent["status"] != "active" or parent["version"] != expected_version:
                raise error("The revision's parent has changed or retired", "MEM-EXPERIENCE-0008")
            source_handoff_id = source_handoff_id or parent["source_handoff_id"]
        source = await conn.fetchrow(
            "SELECT id,unit_id,phase_attempt_id,phase_id,result_status,classification,envelope_digest,payload_digest,lock_snapshot_digest "
            "FROM handoffs WHERE id=$1::uuid AND project_id=$2 FOR KEY SHARE",
            source_handoff_id,
            project_id,
        )
        if source is None:
            raise missing()
        now = await conn.fetchval("SELECT clock_timestamp()")
        if (expires_at is not None and expires_at <= now) or (
            expires_at is not None and valid_from is not None and valid_from >= expires_at
        ):
            raise error("Experience validity interval is invalid or expired", "MEM-EXPERIENCE-0004", 400)
        await ensure_not_suppressed(conn, project_id, source["payload_digest"], content_fingerprint)
        attribution = dict(source)
        attribution["id"] = str(source["id"])
        classification = source["classification"]
        if parent:
            classification = _CLASSIFICATIONS[
                max(_CLASSIFICATIONS.index(classification), _CLASSIFICATIONS.index(parent["classification"]))
            ]
        inserted = await conn.fetchval(
            """
            INSERT INTO memory_experiences (
                project_id,source_handoff_id,source,source_lock_digest,classification,
                kind,title,content,tags,search_text,created_by,idempotency_key,submission_digest,expires_at,
                source_payload_digest,content_fingerprint,valid_from,supersedes_id,supersedes_version,
                revision_root_id,revision_number,is_correction
            ) VALUES ($1,$2::uuid,$3::jsonb,$4,$5,$6,$7,$8,$9::text[],$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22)
            RETURNING id
            """,
            project_id,
            source["id"],
            attribution,
            source["lock_snapshot_digest"],
            classification,
            kind,
            title,
            content,
            tags,
            search_text,
            actor_id,
            idempotency_key,
            submission_digest,
            expires_at,
            source["payload_digest"],
            content_fingerprint,
            valid_from,
            parent["id"] if parent else None,
            parent["version"] if parent else None,
            (parent["revision_root_id"] or parent["id"]) if parent else None,
            parent["revision_number"] + 1 if parent else 1,
            parent is not None,
        )
        return {"memory_id": str(inserted), "already_exists": False}
