"""Parameterized PostgreSQL queries for Memory services."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from isekai_memory.server.errors import MemoryToolError
from isekai_memory.store.database import get_pool

# --- Artifact Registry ---


async def insert_artifact(
    *, artifact_id: str, kind: str, version: str, manifest_digest: str,
    artifact_digest: str, archive_digest: str, archive_blob: bytes | None,
    archive_url: str | None, published_by: str, metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO artifacts (
                artifact_id, kind, version, manifest_digest, artifact_digest,
                archive_digest, archive_blob, archive_url, published_by, metadata
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb)
            ON CONFLICT (artifact_id, kind, version) DO NOTHING
            RETURNING id, artifact_id, kind, version, manifest_digest,
                      artifact_digest, archive_digest, published_at
            """,
            artifact_id, kind, version, manifest_digest, artifact_digest,
            archive_digest, archive_blob, archive_url, published_by, metadata or {},
        )
    return dict(row) if row is not None else None


async def fetch_artifact(*, artifact_id: str, kind: str, version: str) -> dict[str, Any] | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, artifact_id, kind, version, manifest_digest, artifact_digest,
                   archive_digest, archive_blob, archive_url, published_by, published_at, metadata
            FROM artifacts
            WHERE artifact_id=$1 AND kind=$2 AND version=$3
            """,
            artifact_id, kind, version,
        )
    return dict(row) if row is not None else None


async def list_artifact_versions(*, artifact_id: str, kind: str) -> list[dict[str, Any]]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT artifact_id, kind, version, manifest_digest, artifact_digest,
                   archive_digest, published_at
            FROM artifacts
            WHERE artifact_id=$1 AND kind=$2
            """,
            artifact_id, kind,
        )
    return [dict(row) for row in rows]


# --- Artifact Policies ---


async def get_policies_for_org(*, organization_id: str) -> list[dict[str, Any]]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, organization_id, project_pattern, kind, artifact_id,
                   version_range, required, priority, created_at, updated_at
            FROM artifact_policies
            WHERE organization_id=$1
            ORDER BY priority DESC, updated_at DESC, id ASC
            """,
            organization_id,
        )
    return [dict(row) for row in rows]


async def upsert_policy(
    *, organization_id: str, project_pattern: str, kind: str, artifact_id: str,
    version_range: str, required: bool, priority: int,
) -> dict[str, Any]:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO artifact_policies (
                organization_id, project_pattern, kind, artifact_id,
                version_range, required, priority
            ) VALUES ($1,$2,$3,$4,$5,$6,$7)
            ON CONFLICT (organization_id, project_pattern, kind, artifact_id)
            DO UPDATE SET version_range=EXCLUDED.version_range,
                          required=EXCLUDED.required,
                          priority=EXCLUDED.priority,
                          updated_at=now()
            RETURNING id, organization_id, project_pattern, kind, artifact_id,
                      version_range, required, priority, created_at, updated_at
            """,
            organization_id, project_pattern, kind, artifact_id, version_range, required, priority,
        )
    return dict(row)


async def delete_policy(*, policy_id: str, organization_id: str) -> bool:
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM artifact_policies WHERE id=$1::uuid AND organization_id=$2",
            policy_id, organization_id,
        )
    return result == "DELETE 1"


# --- Work Handoff ---


async def insert_handoff(
    *, project_id: str, unit_id: str, phase_attempt_id: str, phase_id: str,
    from_user: str, result_status: str, classification: str, task_summary: str | None,
    passed_checks: list[str], artifacts_produced: list[dict[str, Any]],
    handoff_note: str | None, task_envelope: dict[str, Any],
    result_envelope: dict[str, Any], context_digest: str, raw_output: str | None,
    lock_snapshot_digest: str, envelope_digest: str, payload_digest: str,
    expires_at: datetime, handoff_version: int = 1, recipient_user_id: str | None = None,
    continuation: dict[str, Any] | None = None, continuation_digest: str | None = None,
    compatibility_digest: str | None = None,
) -> dict[str, Any] | None:
    pool = get_pool()
    async with pool.acquire() as conn, conn.transaction():
        # Serialize publication/replay before checking current recipient reachability.
        await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
                           "handoff-push:" + json.dumps([project_id, phase_attempt_id]))
        if await conn.fetchval("SELECT EXISTS(SELECT 1 FROM handoffs WHERE project_id=$1 AND phase_attempt_id=$2)",
                               project_id, phase_attempt_id):
            return None
        if recipient_user_id is not None:
            reachable = await conn.fetchval(
                """SELECT EXISTS(SELECT 1 FROM memory_eligible_members WHERE project_id=$1 AND user_id=$2)""",
                project_id, recipient_user_id,
            )
            if not reachable:
                raise MemoryToolError("Recipient is not available for handoff in this project",
                                      data={"error_code": "MEM-HANDOFF-0013"}, http_status=400)
        row = await conn.fetchrow(
            """
            INSERT INTO handoffs (
                project_id, unit_id, phase_attempt_id, phase_id, from_user,
                result_status, classification, task_summary, passed_checks, artifacts_produced, handoff_note,
                task_envelope, result_envelope, context_digest, raw_output,
                lock_snapshot_digest, envelope_digest, payload_digest, expires_at,
                handoff_version, recipient_user_id, continuation, continuation_digest, compatibility_digest
            ) VALUES (
                $1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10::jsonb,$11,
                $12::jsonb,$13::jsonb,$14,$15,$16,$17,$18,$19,$20,$21,$22::jsonb,$23,$24
            )
            ON CONFLICT (project_id, phase_attempt_id) DO NOTHING
            RETURNING id, created_at, expires_at
            """,
            project_id, unit_id, phase_attempt_id, phase_id, from_user,
            result_status, classification, task_summary, passed_checks, artifacts_produced, handoff_note,
            task_envelope, result_envelope, context_digest, raw_output,
            lock_snapshot_digest, envelope_digest, payload_digest, expires_at,
            handoff_version, recipient_user_id, continuation, continuation_digest, compatibility_digest,
        )
    return dict(row) if row is not None else None


async def get_handoff_by_attempt(*, project_id: str, phase_attempt_id: str) -> dict[str, Any] | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, project_id, unit_id, phase_attempt_id, phase_id, from_user,
                   envelope_digest, payload_digest, created_at, expires_at
            FROM handoffs WHERE project_id=$1 AND phase_attempt_id=$2
            """,
            project_id, phase_attempt_id,
        )
    return dict(row) if row is not None else None


async def list_pending_handoffs(*, project_id: str, unit_id: str | None = None, limit: int = 100,
                               after_id: str | None = None, exclude_actor: str | None = None) -> list[dict[str, Any]]:
    pool = get_pool()
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            """
            UPDATE handoffs SET status='expired'
            WHERE project_id=$1 AND status='pending' AND expires_at <= now() AND handoff_version=1 AND NOT continuity_managed
            """,
            project_id,
        )
        rows = await conn.fetch(
            """
            SELECT id, unit_id, phase_id, from_user, result_status, classification, task_summary,
                   handoff_note, created_at, expires_at
            FROM handoffs
            WHERE project_id=$1 AND status='pending' AND expires_at > now() AND handoff_version=1 AND NOT continuity_managed
              AND ($2::text IS NULL OR unit_id=$2)
              AND ($3::uuid IS NULL OR (created_at,id) < (
                  SELECT created_at,id FROM handoffs WHERE id=$3::uuid AND project_id=$1))
              AND ($4::text IS NULL OR from_user<>$4)
            ORDER BY created_at DESC,id DESC LIMIT $5
            """,
            project_id, unit_id, after_id, exclude_actor, limit,
        )
    return [dict(row) for row in rows]


async def claim_handoff(
    *, handoff_id: str, claimed_by: str, project_id: str | None,
) -> dict[str, Any] | None:
    """Preserve the legacy one-shot pull transition."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE handoffs
            SET status='claimed', claimed_by=$2, claimed_at=now(),
                claim_token_digest=NULL, claim_lease_expires_at=NULL,
                claim_generation=claim_generation + 1,
                claim_disposition=NULL, claim_reason_code=NULL
            WHERE id=$1::uuid AND status='pending' AND expires_at > now() AND handoff_version=1 AND NOT continuity_managed
              AND ($3::text IS NULL OR project_id=$3)
            RETURNING id, project_id, unit_id, phase_attempt_id, phase_id, from_user,
                      result_status, classification, task_summary, passed_checks, artifacts_produced, handoff_note,
                      task_envelope, result_envelope, context_digest, raw_output,
                      lock_snapshot_digest, envelope_digest, compatibility_digest, claimed_by, claimed_at, expires_at
            """,
            handoff_id, claimed_by, project_id,
        )
    return dict(row) if row is not None else None


async def claim_handoff_lease(
    *, handoff_id: str, project_id: str, claimed_by: str,
    claim_token_digest: str, lease_seconds: int, accept_handoff_version: int = 1,
) -> dict[str, Any] | None:
    """Acquire or replay a recoverable claim while serializing contenders."""
    pool = get_pool()
    async with pool.acquire() as conn, conn.transaction():
        locked = await conn.fetchrow(
            """
            SELECT status, claimed_by, claim_token_digest, claim_lease_expires_at,
                   expires_at, handoff_version, recipient_user_id, continuity_managed
            FROM handoffs
            WHERE id=$1::uuid AND project_id=$2
            FOR UPDATE
            """,
            handoff_id, project_id,
        )
        db_now = await conn.fetchval("SELECT clock_timestamp()")
        if locked is None or locked["expires_at"] is None or locked["expires_at"] <= db_now:
            return None
        if (locked["continuity_managed"] or locked["handoff_version"] > accept_handoff_version
                or locked["recipient_user_id"] not in (None, claimed_by)):
            return None
        replay = (
            locked["status"] == "claimed"
            and locked["claim_lease_expires_at"] is not None
            and locked["claim_lease_expires_at"] > db_now
            and locked["claimed_by"] == claimed_by
            and locked["claim_token_digest"] == claim_token_digest
        )
        if replay:
            row = await conn.fetchrow(
                """
                SELECT id, project_id, unit_id, phase_attempt_id, phase_id, from_user,
                       result_status, classification, task_summary, passed_checks, artifacts_produced, handoff_note,
                       task_envelope, result_envelope, context_digest, raw_output,
                       lock_snapshot_digest, envelope_digest, compatibility_digest, claimed_by, claimed_at,
                       claim_lease_expires_at, claim_generation, expires_at,
                       handoff_version, recipient_user_id, continuation, continuation_digest, payload_digest
                FROM handoffs WHERE id=$1::uuid
                """,
                handoff_id,
            )
            result = dict(row)
            result["claim_replayed"] = True
            return result
        recoverable = locked["status"] == "pending" or (
            locked["status"] == "claimed"
            and locked["claim_lease_expires_at"] is not None
            and locked["claim_lease_expires_at"] <= db_now
        )
        if not recoverable:
            return None
        token_was_completed = await conn.fetchval(
            """
            SELECT EXISTS(
                SELECT 1 FROM handoff_claim_receipts
                WHERE handoff_id=$1::uuid AND project_id=$2 AND actor_id=$3
                  AND claim_token_digest=$4
            )
            """,
            handoff_id, project_id, claimed_by, claim_token_digest,
        )
        if token_was_completed:
            return None
        row = await conn.fetchrow(
            """
            UPDATE handoffs
            SET status='claimed', claimed_by=$2, claimed_at=clock_timestamp(),
                claim_token_digest=$3,
                claim_lease_expires_at=LEAST(
                    clock_timestamp() + make_interval(secs => $4::double precision),
                    expires_at
                ),
                claim_generation=claim_generation + 1,
                claim_disposition=NULL, claim_reason_code=NULL
            WHERE id=$1::uuid
            RETURNING id, project_id, unit_id, phase_attempt_id, phase_id, from_user,
                      result_status, classification, task_summary, passed_checks, artifacts_produced, handoff_note,
                      task_envelope, result_envelope, context_digest, raw_output,
                      lock_snapshot_digest, envelope_digest, compatibility_digest, claimed_by, claimed_at,
                      claim_lease_expires_at, claim_generation, expires_at,
                      handoff_version, recipient_user_id, continuation, continuation_digest, payload_digest
            """,
            handoff_id, claimed_by, claim_token_digest, lease_seconds,
        )
        result = dict(row)
        result["claim_replayed"] = False
        return result


async def get_claimed_handoff(
    *, handoff_id: str, project_id: str, claimed_by: str, claim_token_digest: str,
) -> dict[str, Any] | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, project_id, unit_id, phase_attempt_id, phase_id, from_user,
                   result_status, classification, task_summary, passed_checks, artifacts_produced, handoff_note,
                   task_envelope, result_envelope, context_digest, raw_output,
                   lock_snapshot_digest, envelope_digest, compatibility_digest, claimed_by, claimed_at,
                   claim_lease_expires_at, claim_generation, expires_at,
                   handoff_version, recipient_user_id, continuation, continuation_digest, payload_digest
            FROM handoffs
            WHERE id=$1::uuid AND project_id=$2 AND status='claimed' AND NOT continuity_managed
              AND claimed_by=$3 AND claim_token_digest=$4
              AND (recipient_user_id IS NULL OR recipient_user_id=$3)
              AND claim_lease_expires_at > clock_timestamp() AND expires_at > clock_timestamp()
            """,
            handoff_id, project_id, claimed_by, claim_token_digest,
        )
    return dict(row) if row is not None else None


async def acknowledge_handoff(
    *, handoff_id: str, project_id: str, claimed_by: str,
    claim_token_digest: str, claim_generation: int,
) -> dict[str, Any] | None:
    pool = get_pool()
    async with pool.acquire() as conn, conn.transaction():
        receipt = await conn.fetchrow(
            """
            SELECT claim_generation
            FROM handoff_claim_receipts
            WHERE handoff_id=$1::uuid AND project_id=$2 AND actor_id=$3
              AND claim_token_digest=$4 AND claim_generation=$5
              AND operation='acknowledged'
            """,
            handoff_id, project_id, claimed_by, claim_token_digest, claim_generation,
        )
        if receipt is not None:
            return {"id": handoff_id, "claim_generation": receipt["claim_generation"], "already_acknowledged": True}
        locked = await conn.fetchrow(
            """
            SELECT status, claimed_by, claim_token_digest, claim_lease_expires_at,
                   claim_generation, claim_disposition, expires_at
            FROM handoffs
            WHERE id=$1::uuid AND project_id=$2
            FOR UPDATE
            """,
            handoff_id, project_id,
        )
        db_now = await conn.fetchval("SELECT clock_timestamp()")
        if (
            locked is None
            or locked["claimed_by"] != claimed_by
            or locked["claim_token_digest"] != claim_token_digest
            or locked["claim_generation"] != claim_generation
        ):
            return None
        if locked["status"] == "acknowledged" and locked["claim_disposition"] == "acknowledged":
            return {"id": handoff_id, "claim_generation": locked["claim_generation"], "already_acknowledged": True}
        active = (
            locked["status"] == "claimed"
            and locked["claim_lease_expires_at"] is not None
            and locked["claim_lease_expires_at"] > db_now
            and locked["expires_at"] is not None
            and locked["expires_at"] > db_now
        )
        if not active:
            return None
        row = await conn.fetchrow(
            """
            UPDATE handoffs
            SET status='acknowledged', claim_disposition='acknowledged', claim_reason_code=NULL
            WHERE id=$1::uuid AND claim_generation=$2
            RETURNING id, claim_generation
            """,
            handoff_id, claim_generation,
        )
        if row is None:
            return None
        result = dict(row)
        await conn.execute(
            """
            INSERT INTO handoff_claim_receipts (
                handoff_id, project_id, actor_id, claim_token_digest,
                claim_generation, operation
            ) VALUES ($1::uuid,$2,$3,$4,$5,'acknowledged')
            ON CONFLICT ON CONSTRAINT uq_handoff_claim_receipt DO NOTHING
            """,
            handoff_id, project_id, claimed_by, claim_token_digest, result["claim_generation"],
        )
        result["already_acknowledged"] = False
        return result


async def nack_handoff(
    *, handoff_id: str, project_id: str, claimed_by: str,
    claim_token_digest: str, claim_generation: int, reason_code: str,
) -> dict[str, Any] | None:
    pool = get_pool()
    async with pool.acquire() as conn, conn.transaction():
        receipt = await conn.fetchrow(
            """
            SELECT claim_generation, reason_code
            FROM handoff_claim_receipts
            WHERE handoff_id=$1::uuid AND project_id=$2 AND actor_id=$3
              AND claim_token_digest=$4 AND claim_generation=$5
              AND operation='nacked'
            """,
            handoff_id, project_id, claimed_by, claim_token_digest, claim_generation,
        )
        if receipt is not None:
            if receipt["reason_code"] != reason_code:
                return None
            return {"id": handoff_id, "claim_generation": receipt["claim_generation"], "already_nacked": True}
        locked = await conn.fetchrow(
            """
            SELECT status, claimed_by, claim_token_digest, claim_lease_expires_at,
                   claim_generation, claim_disposition, claim_reason_code,
                   expires_at
            FROM handoffs
            WHERE id=$1::uuid AND project_id=$2
            FOR UPDATE
            """,
            handoff_id, project_id,
        )
        db_now = await conn.fetchval("SELECT clock_timestamp()")
        if (
            locked is None
            or locked["claimed_by"] != claimed_by
            or locked["claim_token_digest"] != claim_token_digest
            or locked["claim_generation"] != claim_generation
        ):
            return None
        if locked["status"] == "pending" and locked["claim_disposition"] == "nacked":
            if locked["claim_reason_code"] != reason_code:
                return None
            return {"id": handoff_id, "claim_generation": locked["claim_generation"], "already_nacked": True}
        active = (
            locked["status"] == "claimed"
            and locked["claim_lease_expires_at"] is not None
            and locked["claim_lease_expires_at"] > db_now
            and locked["expires_at"] is not None
            and locked["expires_at"] > db_now
        )
        if not active:
            return None
        row = await conn.fetchrow(
            """
            UPDATE handoffs
            SET status='pending', claim_lease_expires_at=NULL,
                claim_disposition='nacked', claim_reason_code=$2
            WHERE id=$1::uuid AND claim_generation=$3
            RETURNING id, claim_generation
            """,
            handoff_id, reason_code, claim_generation,
        )
        if row is None:
            return None
        result = dict(row)
        await conn.execute(
            """
            INSERT INTO handoff_claim_receipts (
                handoff_id, project_id, actor_id, claim_token_digest,
                claim_generation, operation, reason_code
            ) VALUES ($1::uuid,$2,$3,$4,$5,'nacked',$6)
            ON CONFLICT ON CONSTRAINT uq_handoff_claim_receipt DO NOTHING
            """,
            handoff_id, project_id, claimed_by, claim_token_digest,
            result["claim_generation"], reason_code,
        )
        result["already_nacked"] = False
        return result


# --- Access Tokens ---


async def get_token_by_hash(*, token_hash: str) -> dict[str, Any] | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, token_hash, project_id, user_id, scopes,
                   expires_at, revoked_at, created_at
            FROM access_tokens WHERE token_hash=$1
            """,
            token_hash,
        )
    return dict(row) if row is not None else None


async def create_token(
    *, token_hash: str, project_id: str, user_id: str,
    scopes: list[str], expires_at: datetime | None,
) -> dict[str, Any]:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO access_tokens (token_hash, project_id, user_id, scopes, expires_at)
            VALUES ($1,$2,$3,$4,$5)
            RETURNING id, project_id, user_id, scopes, expires_at, created_at
            """,
            token_hash, project_id, user_id, scopes, expires_at,
        )
    return dict(row)


async def revoke_token(*, token_id: str) -> bool:
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE access_tokens SET revoked_at=now() WHERE id=$1::uuid AND revoked_at IS NULL",
            token_id,
        )
    return result == "UPDATE 1"
