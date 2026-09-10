"""Atomic review, replacement, erasure and suppression release."""

from __future__ import annotations

from typing import Any

from isekai_memory.experience.persistence import ensure_not_suppressed, error, lock_project, missing, suppress
from isekai_memory.store.database import get_pool


def _receipt(memory_id: str, event: Any, replay: bool) -> dict[str, Any]:
    result = {
        "memory_id": memory_id,
        "applied_status": event["applied_status"],
        "applied_version": event["version"],
        "already_applied": replay,
    }
    if event["related_memory_id"]:
        result["related_memory_id"] = str(event["related_memory_id"])
    return result


async def _event(conn, row, actor_id, action, after, now, related=None):
    await conn.execute(
        "UPDATE memory_experiences SET status=$2, version=version+1, updated_at=$3 WHERE id=$1", row["id"], after, now
    )
    return await conn.fetchrow(
        """
        INSERT INTO memory_experience_events (memory_id,version,actor_id,action,previous_status,applied_status,related_memory_id)
        VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING version, applied_status, related_memory_id
        """,
        row["id"],
        row["version"] + 1,
        actor_id,
        action,
        row["status"],
        after,
        related,
    )


async def review(
    *, project_id: str, memory_id: str, actor_id: str, action: str, expected_version: int
) -> dict[str, Any]:
    async with get_pool().acquire() as conn, conn.transaction():
        await lock_project(conn, project_id)
        row = await conn.fetchrow(
            "SELECT * FROM memory_experiences WHERE id=$1::uuid AND project_id=$2 FOR UPDATE", memory_id, project_id
        )
        if row is None:
            raise missing()
        receipt = await conn.fetchrow(
            "SELECT actor_id,action,applied_status,version,related_memory_id FROM memory_experience_events "
            "WHERE memory_id=$1::uuid AND version=$2",
            memory_id,
            expected_version + 1,
        )
        if receipt and receipt["actor_id"] == actor_id and receipt["action"] == action:
            return _receipt(memory_id, receipt, True)
        before = {"approve": "pending", "reject": "pending", "archive": "active"}.get(action)
        if row["version"] != expected_version or row["status"] == "forgotten" or (before and row["status"] != before):
            raise error("Experience version or lifecycle transition conflicts", "MEM-EXPERIENCE-0003")
        parent = None
        if action == "approve" and row["supersedes_id"]:
            parent = await conn.fetchrow(
                "SELECT * FROM memory_experiences WHERE id=$1 AND project_id=$2 FOR UPDATE",
                row["supersedes_id"],
                project_id,
            )
            if parent is None or parent["status"] != "active" or parent["version"] != row["supersedes_version"]:
                raise error("The revision's parent has changed or retired", "MEM-EXPERIENCE-0008")
        now = await conn.fetchval("SELECT clock_timestamp()")
        if action == "approve":
            if (row["expires_at"] is not None and row["expires_at"] <= now) or (
                row["valid_from"] is not None and row["valid_from"] > now
            ):
                raise error("An experience outside its validity interval cannot be approved", "MEM-EXPERIENCE-0004")
            await ensure_not_suppressed(conn, project_id, row["source_payload_digest"], row["content_fingerprint"])
            if parent is not None:
                # A title/tag-only correction retains the same claim, not a
                # rejected claim. Do not suppress the replacement's own identity.
                if (parent["source_payload_digest"], parent["content_fingerprint"]) != (
                    row["source_payload_digest"],
                    row["content_fingerprint"],
                ):
                    await suppress(conn, parent, actor_id, "superseded")
                await _event(conn, parent, actor_id, "supersede", "superseded", now, row["id"])
        after = {"approve": "active", "reject": "rejected", "archive": "archived", "forget": "forgotten"}[action]
        if action in {"reject", "forget"}:
            await suppress(conn, row, actor_id, after)
        if action == "forget":
            # Set status in the same statement as erasure to satisfy DB guards.
            await conn.execute(
                "UPDATE memory_experiences SET status='forgotten', title='[forgotten]', content='[forgotten]', "
                "tags='{}', search_text='', source='{}'::jsonb, source_handoff_id=NULL WHERE id=$1",
                row["id"],
            )
        event = await _event(conn, row, actor_id, action, after, now, parent["id"] if parent else None)
        return _receipt(memory_id, event, False)


async def release_suppression(
    *, project_id: str, memory_id: str, actor_id: str, expected_suppression_version: int
) -> dict[str, Any]:
    async with get_pool().acquire() as conn, conn.transaction():
        await lock_project(conn, project_id)
        row = await conn.fetchrow(
            "SELECT source_payload_digest,content_fingerprint FROM memory_experiences WHERE id=$1::uuid AND project_id=$2",
            memory_id,
            project_id,
        )
        if row is None:
            raise missing()
        suppression = await conn.fetchrow(
            "SELECT * FROM memory_experience_suppressions WHERE project_id=$1 AND source_payload_digest=$2 AND content_fingerprint=$3 FOR UPDATE",
            project_id,
            row["source_payload_digest"],
            row["content_fingerprint"],
        )
        if suppression is None:
            raise missing()
        replay = (
            suppression["released_at"] is not None
            and suppression["version"] == expected_suppression_version + 1
            and suppression["updated_by"] == actor_id
        )
        if not replay:
            if suppression["version"] != expected_suppression_version or suppression["released_at"] is not None:
                raise error("Suppression version conflicts", "MEM-EXPERIENCE-0009")
            await conn.execute(
                "UPDATE memory_experience_suppressions SET released_at=clock_timestamp(),updated_at=clock_timestamp(),updated_by=$4,version=version+1 "
                "WHERE project_id=$1 AND source_payload_digest=$2 AND content_fingerprint=$3",
                project_id,
                row["source_payload_digest"],
                row["content_fingerprint"],
                actor_id,
            )
        return {
            "memory_id": memory_id,
            "suppression_version": expected_suppression_version + 1,
            "released": True,
            "already_released": replay,
        }
