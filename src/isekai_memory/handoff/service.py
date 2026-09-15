"""Work Handoff business logic — push, list, legacy pull, and recoverable leases."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from isekai_memory.config import Settings
from isekai_memory.handoff import continuation
from isekai_memory.handoff.validation import validate_envelopes
from isekai_memory.server.errors import MemoryToolError
from isekai_memory.store import queries


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _compute_envelope_digest(task_envelope: Any, result_envelope: Any) -> str:
    payload = _canonical_bytes(task_envelope) + _canonical_bytes(result_envelope)
    return "sha256:" + hashlib.sha256(payload).hexdigest()


async def push_handoff(
    arguments: dict[str, Any],
    *,
    settings: Settings | None = None,
    from_user: str = "local-stdio",
) -> dict[str, Any]:
    """Validate and register a completed phase result as an immutable handoff."""
    settings = settings or Settings()
    validate_envelopes(arguments)
    recipient = arguments.get("recipient_user_id")
    package = arguments.get("continuation")
    if recipient is not None:
        from jsonschema import Draft202012Validator

        if not Draft202012Validator(continuation.RECIPIENT).is_valid(recipient):
            raise continuation.invalid("Invalid recipient identity")
    continuation_digest = continuation.validate(package) if package is not None else None
    handoff_version = 2 if recipient is not None or package is not None else 1
    computed_envelope = _compute_envelope_digest(arguments["task_envelope"], arguments["result_envelope"])
    if computed_envelope != arguments["envelope_digest"]:
        raise MemoryToolError(
            "envelope_digest verification failed",
            data={"error_code": "MEM-HANDOFF-0002", "expected": arguments["envelope_digest"], "computed": computed_envelope},
        )
    raw_output = arguments.get("raw_output")
    if raw_output is not None and len(raw_output.encode("utf-8")) > settings.handoff_max_raw_output_bytes:
        raise MemoryToolError(
            "raw_output exceeds configured size limit",
            data={"error_code": "MEM-HANDOFF-0004", "max_bytes": settings.handoff_max_raw_output_bytes},
        )

    payload_material = {
        "project_id": arguments["project_id"],
        "unit_id": arguments["unit_id"],
        "phase_attempt_id": arguments["phase_attempt_id"],
        "phase_id": arguments["phase_id"],
        "from_user": from_user,
        "result_status": arguments["result_status"],
        "classification": arguments["classification"],
        "task_summary": arguments.get("task_summary"),
        "passed_checks": arguments.get("passed_checks", []),
        "artifacts_produced": arguments.get("artifacts_produced", []),
        "handoff_note": arguments.get("handoff_note"),
        "task_envelope": arguments["task_envelope"],
        "result_envelope": arguments["result_envelope"],
        "context_digest": arguments["context_digest"],
        "raw_output": raw_output,
        "lock_snapshot_digest": arguments["lock_snapshot_digest"],
        "envelope_digest": arguments["envelope_digest"],
    }
    if handoff_version == 2:
        payload_material.update(handoff_version=2, recipient_user_id=recipient,
                                continuation=package, continuation_digest=continuation_digest)
    payload_digest = _digest(payload_material)
    expires_at = datetime.now(UTC) + timedelta(hours=settings.handoff_default_expiry_hours)
    row = await queries.insert_handoff(
        project_id=arguments["project_id"],
        unit_id=arguments["unit_id"],
        phase_attempt_id=arguments["phase_attempt_id"],
        phase_id=arguments["phase_id"],
        from_user=from_user,
        result_status=arguments["result_status"],
        classification=arguments["classification"],
        task_summary=arguments.get("task_summary"),
        passed_checks=arguments.get("passed_checks", []),
        artifacts_produced=arguments.get("artifacts_produced", []),
        handoff_note=arguments.get("handoff_note"),
        task_envelope=arguments["task_envelope"],
        result_envelope=arguments["result_envelope"],
        context_digest=arguments["context_digest"],
        raw_output=raw_output,
        lock_snapshot_digest=arguments["lock_snapshot_digest"],
        envelope_digest=arguments["envelope_digest"],
        payload_digest=payload_digest,
        expires_at=expires_at,
        handoff_version=handoff_version,
        recipient_user_id=recipient,
        continuation=package,
        continuation_digest=continuation_digest,
    )
    if row is None:
        existing = await queries.get_handoff_by_attempt(
            project_id=arguments["project_id"],
            phase_attempt_id=arguments["phase_attempt_id"],
        )
        if existing is None:
            raise MemoryToolError("handoff conflict row disappeared", data={"error_code": "MEM-HANDOFF-0005"})
        if existing["payload_digest"] != payload_digest:
            raise MemoryToolError(
                "phase_attempt_id already exists with a different handoff payload",
                data={"error_code": "MEM-HANDOFF-0005", "handoff_id": str(existing["id"])},
            )
        return {
            "handoff_id": str(existing["id"]),
            "created_at": existing["created_at"].isoformat(),
            "expires_at": existing["expires_at"].isoformat(),
            "already_exists": True,
            **({"handoff_version": 2, "recipient_user_id": recipient,
                "continuation_digest": continuation_digest} if handoff_version == 2 else {}),
        }
    return {
        "handoff_id": str(row["id"]),
        "created_at": row["created_at"].isoformat(),
        "expires_at": row["expires_at"].isoformat(),
        "already_exists": False,
        **({"handoff_version": 2, "recipient_user_id": recipient,
            "continuation_digest": continuation_digest} if handoff_version == 2 else {}),
    }


async def list_handoffs(arguments: dict[str, Any]) -> list[dict[str, Any]]:
    rows = await queries.list_pending_handoffs(project_id=arguments["project_id"], unit_id=arguments.get("unit_id"))
    return [
        {
            "id": str(row["id"]),
            "unit_id": row["unit_id"],
            "phase_id": row["phase_id"],
            "from_user": row["from_user"],
            "result_status": row["result_status"],
            "classification": row["classification"],
            "task_summary": row["task_summary"],
            "handoff_note": row["handoff_note"],
            "created_at": row["created_at"].isoformat(),
            "expires_at": row["expires_at"].isoformat(),
        }
        for row in rows
    ]


async def pull_handoff(
    arguments: dict[str, Any],
    *,
    claimed_by: str = "local-stdio",
    authorized_project_id: str | None = None,
) -> dict[str, Any]:
    project_id = authorized_project_id or arguments.get("project_id")
    row = await queries.claim_handoff(
        handoff_id=arguments["handoff_id"],
        claimed_by=claimed_by,
        project_id=project_id,
    )
    if row is None:
        raise MemoryToolError(
            "Handoff not found, expired, outside project scope, or already claimed",
            data={"error_code": "MEM-HANDOFF-0001", "handoff_id": arguments["handoff_id"]},
        )
    return {
        "handoff_id": str(row["id"]),
        "project_id": row["project_id"],
        "unit_id": row["unit_id"],
        "phase_attempt_id": row["phase_attempt_id"],
        "phase_id": row["phase_id"],
        "from_user": row["from_user"],
        "result_status": row["result_status"],
        "classification": row["classification"],
        "task_summary": row["task_summary"],
        "handoff_note": row["handoff_note"],
        "passed_checks": row["passed_checks"],
        "artifacts_produced": row["artifacts_produced"],
        "task_envelope": row["task_envelope"],
        "result_envelope": row["result_envelope"],
        "context_digest": row["context_digest"],
        "raw_output": row["raw_output"],
        "lock_snapshot_digest": row["lock_snapshot_digest"],
        "envelope_digest": row["envelope_digest"],
        "claimed_by": row["claimed_by"],
        "claimed_at": row["claimed_at"].isoformat(),
        "expires_at": row["expires_at"].isoformat(),
    }


def _claim_token_digest(claim_token: str) -> str:
    """Reduce the client capability to a non-reversible value before persistence."""
    return hashlib.sha256(claim_token.encode("utf-8")).hexdigest()


def _recoverable_handoff_result(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **continuation.delivery_fields(row),
        "handoff_id": str(row["id"]),
        "project_id": row["project_id"],
        "unit_id": row["unit_id"],
        "phase_attempt_id": row["phase_attempt_id"],
        "phase_id": row["phase_id"],
        "from_user": row["from_user"],
        "result_status": row["result_status"],
        "classification": row["classification"],
        "task_summary": row["task_summary"],
        "handoff_note": row["handoff_note"],
        "passed_checks": row["passed_checks"],
        "artifacts_produced": row["artifacts_produced"],
        "task_envelope": row["task_envelope"],
        "result_envelope": row["result_envelope"],
        "context_digest": row["context_digest"],
        "raw_output": row["raw_output"],
        "lock_snapshot_digest": row["lock_snapshot_digest"],
        "envelope_digest": row["envelope_digest"],
        "claimed_by": row["claimed_by"],
        "claimed_at": row["claimed_at"].isoformat(),
        "lease_expires_at": row["claim_lease_expires_at"].isoformat(),
        "claim_generation": row["claim_generation"],
        "expires_at": row["expires_at"].isoformat(),
    }


def _project_id(arguments: dict[str, Any], authorized_project_id: str | None) -> str:
    return authorized_project_id or arguments["project_id"]


async def claim_handoff_recoverable(
    arguments: dict[str, Any],
    *,
    settings: Settings | None = None,
    claimed_by: str = "local-stdio",
    authorized_project_id: str | None = None,
) -> dict[str, Any]:
    """Acquire a new lease or replay an active lease for the same client token."""
    settings = settings or Settings()
    lease_seconds = arguments.get("lease_seconds", settings.handoff_claim_lease_default_seconds)
    if not settings.handoff_claim_lease_min_seconds <= lease_seconds <= settings.handoff_claim_lease_max_seconds:
        raise MemoryToolError(
            "Requested handoff lease is outside configured bounds",
            data={
                "error_code": "MEM-HANDOFF-0006",
                "minimum_seconds": settings.handoff_claim_lease_min_seconds,
                "maximum_seconds": settings.handoff_claim_lease_max_seconds,
            },
        )
    row = await queries.claim_handoff_lease(
        handoff_id=arguments["handoff_id"],
        project_id=_project_id(arguments, authorized_project_id),
        claimed_by=claimed_by,
        claim_token_digest=_claim_token_digest(arguments["claim_token"]),
        lease_seconds=lease_seconds,
        accept_handoff_version=arguments.get("accept_handoff_version", 1),
    )
    if row is None:
        raise MemoryToolError(
            "Handoff is unavailable for this project, actor, and claim token",
            data={"error_code": "MEM-HANDOFF-0007", "handoff_id": arguments["handoff_id"]},
        )
    result = _recoverable_handoff_result(row)
    result["claim_replayed"] = row["claim_replayed"]
    return result


async def get_claimed_handoff(
    arguments: dict[str, Any],
    *,
    claimed_by: str = "local-stdio",
    authorized_project_id: str | None = None,
) -> dict[str, Any]:
    """Recover the payload of an active claim after a lost claim response."""
    row = await queries.get_claimed_handoff(
        handoff_id=arguments["handoff_id"],
        project_id=_project_id(arguments, authorized_project_id),
        claimed_by=claimed_by,
        claim_token_digest=_claim_token_digest(arguments["claim_token"]),
    )
    if row is None:
        raise MemoryToolError(
            "No active handoff lease matches this project, actor, and claim token",
            data={"error_code": "MEM-HANDOFF-0007", "handoff_id": arguments["handoff_id"]},
        )
    return _recoverable_handoff_result(row)


async def acknowledge_claimed_handoff(
    arguments: dict[str, Any],
    *,
    claimed_by: str = "local-stdio",
    authorized_project_id: str | None = None,
) -> dict[str, Any]:
    row = await queries.acknowledge_handoff(
        handoff_id=arguments["handoff_id"],
        project_id=_project_id(arguments, authorized_project_id),
        claimed_by=claimed_by,
        claim_token_digest=_claim_token_digest(arguments["claim_token"]),
        claim_generation=arguments["claim_generation"],
    )
    if row is None:
        raise MemoryToolError(
            "Handoff acknowledgement does not match an active or completed claim",
            data={"error_code": "MEM-HANDOFF-0008", "handoff_id": arguments["handoff_id"]},
        )
    return {
        "handoff_id": str(row["id"]),
        "claim_generation": row["claim_generation"],
        "acknowledged": True,
        "already_acknowledged": row["already_acknowledged"],
    }


async def nack_claimed_handoff(
    arguments: dict[str, Any],
    *,
    claimed_by: str = "local-stdio",
    authorized_project_id: str | None = None,
) -> dict[str, Any]:
    row = await queries.nack_handoff(
        handoff_id=arguments["handoff_id"],
        project_id=_project_id(arguments, authorized_project_id),
        claimed_by=claimed_by,
        claim_token_digest=_claim_token_digest(arguments["claim_token"]),
        claim_generation=arguments["claim_generation"],
        reason_code=arguments["reason_code"],
    )
    if row is None:
        raise MemoryToolError(
            "Handoff rejection does not match an active or completed claim",
            data={"error_code": "MEM-HANDOFF-0008", "handoff_id": arguments["handoff_id"]},
        )
    return {
        "handoff_id": str(row["id"]),
        "claim_generation": row["claim_generation"],
        "nacked": True,
        "already_nacked": row["already_nacked"],
        "reason_code": arguments["reason_code"],
    }
