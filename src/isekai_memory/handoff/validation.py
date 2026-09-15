"""Core Task/Result envelope validation used at the Memory trust boundary."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any

from isekai_memory.server.errors import MemoryToolError

_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMMON_REQUIRED = {"correlation_id", "operation_id", "work_bundle_id", "unit_id", "phase_attempt_id"}
_TASK_REQUIRED = _COMMON_REQUIRED | {
    "type", "task_id", "role", "objective", "acceptance_criteria", "allowed_actions",
    "forbidden_actions", "required_outputs", "workspace_root", "lock_snapshot_digest",
    "context_bundle_ref", "context_bundle_digest", "result_path", "deadline",
}
_RESULT_REQUIRED = _COMMON_REQUIRED | {
    "type", "task_id", "status", "summary", "outputs", "evidence_refs", "unresolved",
    "context_usage", "raw_output_ref", "raw_output_digest", "started_at", "ended_at",
}


def _error(message: str, **details: Any) -> MemoryToolError:
    return MemoryToolError(message, data={"error_code": "MEM-HANDOFF-0003", **details})


def _require_object(envelope: Any, required: set[str], expected_type: str) -> dict[str, Any]:
    if not isinstance(envelope, dict):
        raise _error(f"{expected_type} must be an object")
    missing = sorted(required - envelope.keys())
    if missing:
        raise _error(f"{expected_type} is missing required fields", missing=missing)
    if envelope.get("type") != expected_type:
        raise _error(f"envelope type must be {expected_type}")
    for key in _COMMON_REQUIRED | {"task_id"}:
        if not isinstance(envelope.get(key), str) or not envelope[key]:
            raise _error(f"{expected_type}.{key} must be a non-empty string")
    return envelope


def _validate_timestamp(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise _error(f"{field} must be a UTC timestamp")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise _error(f"{field} is not a valid timestamp") from error


def _validate_digest(value: Any, field: str) -> None:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise _error(f"{field} must be a sha256 digest")


def validate_envelopes(arguments: dict[str, Any]) -> None:
    task = _require_object(arguments["task_envelope"], _TASK_REQUIRED, "task_envelope")
    result = _require_object(arguments["result_envelope"], _RESULT_REQUIRED, "result_envelope")

    for field in ("correlation_id", "work_bundle_id", "unit_id", "phase_attempt_id", "session_id", "task_id"):
        if task.get(field) != result.get(field):
            raise _error("Task/Result correlation mismatch", field=field)
    for field in ("unit_id", "phase_attempt_id"):
        if task[field] != arguments[field]:
            raise _error("Handoff scope differs from Task envelope", field=field)

    if result["status"] not in ("succeeded", "failed", "cancelled", "lost"):
        raise _error("Result status is invalid")
    if result["status"] != arguments["result_status"]:
        raise _error("result_status differs from Result envelope status")

    _validate_digest(task["lock_snapshot_digest"], "task_envelope.lock_snapshot_digest")
    _validate_digest(task["context_bundle_digest"], "task_envelope.context_bundle_digest")
    _validate_digest(result["raw_output_digest"], "result_envelope.raw_output_digest")
    if task["lock_snapshot_digest"] != arguments["lock_snapshot_digest"]:
        raise _error("lock_snapshot_digest differs from Task envelope")
    if task["context_bundle_digest"] != arguments["context_digest"]:
        raise _error("context_digest differs from Task context bundle digest")

    for field in ("deadline",):
        _validate_timestamp(task[field], f"task_envelope.{field}")
    for field in ("started_at", "ended_at"):
        _validate_timestamp(result[field], f"result_envelope.{field}")
    if datetime.fromisoformat(result["ended_at"].replace("Z", "+00:00")) < datetime.fromisoformat(
        result["started_at"].replace("Z", "+00:00")
    ):
        raise _error("Result ended_at precedes started_at")

    for envelope, fields, name in (
        (task, ("acceptance_criteria", "allowed_actions", "forbidden_actions", "required_outputs"), "task_envelope"),
        (result, ("outputs", "evidence_refs", "unresolved"), "result_envelope"),
    ):
        for field in fields:
            value = envelope[field]
            if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
                raise _error(f"{name}.{field} must be an array of non-empty strings")
            if len(value) != len(set(value)):
                raise _error(f"{name}.{field} must contain unique values")

    context_usage = result["context_usage"]
    if (
        not isinstance(context_usage, dict)
        or set(context_usage) != {"mode", "used", "capacity"}
        or context_usage.get("mode") not in ("exact", "estimated", "unavailable")
        or not isinstance(context_usage.get("used"), int)
        or not isinstance(context_usage.get("capacity"), int)
        or context_usage["used"] < 0
        or context_usage["capacity"] < 0
    ):
        raise _error("result_envelope.context_usage is invalid")

    raw_output = arguments.get("raw_output")
    if raw_output is not None:
        computed = "sha256:" + hashlib.sha256(raw_output.encode("utf-8")).hexdigest()
        if computed != result["raw_output_digest"]:
            raise _error("raw_output does not match Result raw_output_digest", computed=computed)
