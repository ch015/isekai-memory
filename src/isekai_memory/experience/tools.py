"""Input contracts for source-backed experience tools."""

from __future__ import annotations

from typing import Any

_TEXT = {"type": "string", "minLength": 1, "pattern": r"\S", "not": {"pattern": r"[\u0000\uD800-\uDFFF]"}}
_ID = {**_TEXT, "maxLength": 128}
_UUID = {"type": "string", "format": "uuid"}
_KIND = {"enum": ["fact", "decision", "constraint", "lesson", "procedure"]}
_CLASSIFICATION = {"enum": ["public", "internal", "confidential", "restricted"], "default": "internal"}
_VERSION = {"type": "integer", "minimum": 1, "maximum": 2147483646}
_CURSOR = {"type": "string", "minLength": 1, "maxLength": 2048}
_LIMIT = {"type": "integer", "minimum": 1, "maximum": 100, "default": 20}
_BODY = {
    "source_handoff_id": _UUID,
    "idempotency_key": _ID,
    "kind": _KIND,
    "title": {**_TEXT, "maxLength": 200},
    "content": {**_TEXT, "maxLength": 4096},
    "tags": {"type": "array", "maxItems": 16, "uniqueItems": True, "items": {**_TEXT, "maxLength": 64}},
    "valid_from": {"type": "string", "format": "date-time", "maxLength": 64},
    "expires_at": {"type": "string", "format": "date-time", "maxLength": 64},
}
_VISIBILITY = {
    "max_classification": _CLASSIFICATION,
    "source_lock_digest": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
}


def _tool(name: str, description: str, required: list[str], properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "required": ["project_id", *required],
            "properties": {"project_id": _ID, **properties},
            "additionalProperties": False,
            **(
                {"not": {"required": ["cursor", "offset"]}} if "cursor" in properties and "offset" in properties else {}
            ),
        },
    }


EXPERIENCE_TOOLS = [
    _tool(
        "memory_experience_propose",
        "Propose a pending project experience from an existing handoff. Requires admin review before retrieval.",
        ["source_handoff_id", "idempotency_key", "kind", "title", "content"],
        _BODY,
    ),
    _tool(
        "memory_experience_revise",
        "Admin-only immutable correction proposal. Approval atomically replaces its active parent at the captured version.",
        ["memory_id", "expected_version", "idempotency_key", "kind", "title", "content"],
        {**_BODY, "memory_id": _UUID, "expected_version": _VERSION},
    ),
    _tool(
        "memory_experience_history",
        "Admin-only family history and target suppression version, including retired and forgotten rows.",
        ["memory_id"],
        {"memory_id": _UUID, "limit": _LIMIT, "cursor": _CURSOR},
    ),
    _tool(
        "memory_experience_suppression_release",
        "Admin-only version-guarded release of a suppressed claim; never reactivates an old memory.",
        ["memory_id", "expected_suppression_version"],
        {"memory_id": _UUID, "expected_suppression_version": _VERSION},
    ),
    _tool(
        "memory_experience_list",
        "Admin-only review queue, including inactive and expired entries.",
        [],
        {
            "status": {
                "enum": ["pending", "active", "rejected", "archived", "superseded", "forgotten"],
                "default": "pending",
            },
            "limit": _LIMIT,
            "cursor": _CURSOR,
            "offset": {"type": "integer", "minimum": 0, "maximum": 10000, "default": 0},
        },
    ),
    _tool(
        "memory_experience_review",
        "Admin-only approve/reject/archive/forget with expected version. Forget erases stored plaintext. Retries return original receipts.",
        ["memory_id", "action", "expected_version"],
        {
            "memory_id": _UUID,
            "action": {"enum": ["approve", "reject", "archive", "forget"]},
            "expected_version": _VERSION,
        },
    ),
    _tool(
        "memory_search",
        "Search approved, unexpired project experiences. Returns reference excerpts and provenance; never consumes a handoff.",
        ["query"],
        {
            "query": {**_TEXT, "maxLength": 512},
            "kind": _KIND,
            **_VISIBILITY,
            "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
            "max_chars": {"type": "integer", "minimum": 1000, "maximum": 16000, "default": 8000},
        },
    ),
    _tool(
        "memory_read",
        "Read one approved, unexpired project experience as reference data with source attribution.",
        ["memory_id"],
        {"memory_id": _UUID, **_VISIBILITY},
    ),
]
