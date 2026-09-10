"""Shared transaction guards for experience mutations."""

from __future__ import annotations

from typing import Any

from isekai_memory.server.errors import MemoryToolError


def error(message: str, code: str, status: int = 409) -> MemoryToolError:
    return MemoryToolError(message, data={"error_code": code}, http_status=status)


def missing() -> MemoryToolError:
    return error("Experience or source is not available in this project", "MEM-EXPERIENCE-0001", 404)


async def lock_project(conn, project_id: str) -> None:
    # All mutation paths use the same order: project advisory lock, then row locks.
    await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", "isekai-experience:" + project_id)


async def ensure_not_suppressed(conn, project_id: str, source_digest: str, fingerprint: str) -> None:
    if await conn.fetchval(
        "SELECT EXISTS(SELECT 1 FROM memory_experience_suppressions "
        "WHERE project_id=$1 AND source_payload_digest=$2 AND content_fingerprint=$3 AND released_at IS NULL)",
        project_id,
        source_digest,
        fingerprint,
    ):
        raise error(
            "This source-backed claim is suppressed; admin release is required before proposing it again",
            "MEM-EXPERIENCE-0007",
        )


async def suppress(conn, row: Any, actor_id: str, reason: str) -> None:
    await conn.execute(
        """
        INSERT INTO memory_experience_suppressions
            (project_id, source_payload_digest, content_fingerprint, memory_id, reason, updated_by)
        VALUES ($1,$2,$3,$4,$5,$6)
        ON CONFLICT (project_id, source_payload_digest, content_fingerprint) DO UPDATE
        SET memory_id=EXCLUDED.memory_id, reason=EXCLUDED.reason, updated_by=EXCLUDED.updated_by,
            version=memory_experience_suppressions.version+1, updated_at=clock_timestamp(), released_at=NULL
        """,
        row["project_id"],
        row["source_payload_digest"],
        row["content_fingerprint"],
        row["id"],
        reason,
        actor_id,
    )
