"""Project-scoped metadata reads and row-locked lease renewal."""

from datetime import datetime, timedelta

from isekai_memory.server.errors import MemoryToolError
from isekai_memory.store.database import get_pool

# Deliberately exclude envelopes, raw output, artifacts and token digests.
METADATA_COLUMNS = """
    id, project_id, unit_id, phase_attempt_id, phase_id, from_user,
    result_status, classification, status, created_at, expires_at,
    claimed_by, claimed_at, claim_generation, claim_lease_expires_at,
    claim_disposition, claim_reason_code, payload_digest,
    lock_snapshot_digest, envelope_digest,
    handoff_version, recipient_user_id, continuation_digest, continuity_managed,
    left(task_summary, 512) AS task_summary,
    left(handoff_note, 512) AS handoff_note,
    (coalesce(length(task_summary), 0) > 512 OR
     coalesce(length(handoff_note), 0) > 512) AS preview_truncated
"""

VIEW_FILTERS = {
    "available": """NOT continuity_managed AND expires_at > $7 AND (recipient_user_id IS NULL OR recipient_user_id=$2) AND
        (status='pending' OR (status='claimed' AND claim_lease_expires_at <= $7))""",
    "claimed": """expires_at > $7 AND status='claimed'
        AND claimed_by=$2 AND claim_lease_expires_at > $7""",
    "sent": "from_user=$2",
}


async def inbox_rows(*, project_id, actor_id, view, unit_id, classifications, before_at, before_id, limit):
    async with get_pool().acquire() as conn, conn.transaction(isolation="repeatable_read", readonly=True):
        observed_at = await conn.fetchval("SELECT clock_timestamp()")
        # SQL fragments are code-owned constants; every caller value is bound.
        rows = await conn.fetch(
            f"""
            SELECT {METADATA_COLUMNS} FROM handoffs
            WHERE project_id=$1 AND $2::text IS NOT NULL AND $7::timestamptz IS NOT NULL
              AND ($3::text IS NULL OR unit_id=$3)
              AND classification=ANY($4::text[])
              AND ($5::timestamptz IS NULL OR (created_at, id) < ($5, $6::uuid))
              AND ({VIEW_FILTERS[view]})
            ORDER BY created_at DESC, id DESC LIMIT $8
            """,
            project_id, actor_id, unit_id, classifications, before_at, before_id, observed_at, limit + 1,
        )
        return [dict(row) for row in rows], observed_at


async def status_row(*, project_id, handoff_id, classifications):
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            f"""SELECT {METADATA_COLUMNS}, statement_timestamp() AS observed_at
                FROM handoffs WHERE project_id=$1 AND id=$2::uuid
                  AND classification=ANY($3::text[])""",
            project_id, handoff_id, classifications,
        )
        return dict(row) if row else None


def unavailable():
    return MemoryToolError(
        "No active lease matches this project, actor, token and generation",
        data={"error_code": "MEM-HANDOFF-0010"}, http_status=409,
    )


async def renew_lease(*, project_id, handoff_id, actor_id, token_digest, generation,
                      deadline: datetime, max_seconds: int):
    async with get_pool().acquire() as conn, conn.transaction():
        row = await conn.fetchrow(
            """SELECT status, claimed_by, claim_token_digest, claim_generation,
                      claim_lease_expires_at, expires_at, recipient_user_id, continuity_managed
               FROM handoffs WHERE project_id=$1 AND id=$2::uuid FOR UPDATE""",
            project_id, handoff_id,
        )
        # Sample after acquiring the row lock, not at transaction start.
        now = await conn.fetchval("SELECT clock_timestamp()")
        if (
            row is None or row["status"] != "claimed" or row.get("continuity_managed", False)
            or row["claimed_by"] != actor_id or row["claim_token_digest"] != token_digest
            or row["claim_generation"] != generation
            or row["recipient_user_id"] not in (None, actor_id)
            or row["claim_lease_expires_at"] is None or row["claim_lease_expires_at"] <= now
            or row["expires_at"] is None or row["expires_at"] <= now
        ):
            raise unavailable()
        current = row["claim_lease_expires_at"]
        # Absolute-deadline retries never repeatedly extend an active lease.
        if deadline > current and deadline > now + timedelta(seconds=max_seconds):
            raise MemoryToolError(
                "Requested deadline exceeds the configured maximum lease duration",
                data={"error_code": "MEM-HANDOFF-0011", "maximum_seconds": max_seconds}, http_status=400,
            )
        effective = max(current, min(deadline, row["expires_at"]))
        extended = effective > current
        if extended:
            await conn.execute(
                "UPDATE handoffs SET claim_lease_expires_at=$2 WHERE id=$1::uuid",
                handoff_id, effective,
            )
        return {
            "handoff_id": handoff_id, "claim_generation": generation,
            "lease_expires_at": effective.isoformat(), "expires_at": row["expires_at"].isoformat(),
            "observed_at": now.isoformat(), "extended": extended,
        }
