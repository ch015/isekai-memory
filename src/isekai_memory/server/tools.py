"""MCP tool catalog for Work Handoff and Repository Registry.

Artifact publish/fetch/resolve tools have been removed — artifacts are now
distributed via Git Releases and installed locally by ``isekai init/update``.

Policy tools are commented out for future expansion when policy-based
version resolution is needed again.
"""

from __future__ import annotations

from typing import Any

DIGEST = {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
SHORT_ID = {"type": "string", "minLength": 1, "maxLength": 128}
KIND = {"enum": ["foundation", "preset"]}
CLASSIFICATION = {"enum": ["public", "internal", "confidential", "restricted"]}
CLAIM_TOKEN = {"type": "string", "minLength": 32, "maxLength": 256, "pattern": "^[A-Za-z0-9_-]+$"}
CLAIM_REASON = {"enum": ["retryable", "processing_failed", "shutdown", "cancelled"]}

# ---------------------------------------------------------------------------
# Removed: memory_artifact_resolve, memory_artifact_fetch, memory_artifact_publish
#
# Artifacts are now built in CI, published to Git Releases, and installed
# locally via ``isekai init --foundation <path> --preset <path>``.
# The Memory server no longer stores or serves artifact archives.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Commented out for future expansion:
# memory_policy_upsert, memory_policy_delete
#
# Policy-based version resolution may be reintroduced when the repository
# registry supports automatic upgrade notifications.  The policy engine
# (registry/policy.py) is preserved and can be re-enabled by uncommenting
# the entries below and reconnecting the dispatcher.
# ---------------------------------------------------------------------------
# {
#     "name": "memory_policy_upsert",
#     "description": "Create or update one deterministic organization artifact policy.",
#     "inputSchema": {
#         "type": "object",
#         "required": ["organization_id", "project_pattern", "kind", "artifact_id", "version_range"],
#         "properties": {
#             "organization_id": SHORT_ID, "project_pattern": {"type": "string", "minLength": 1, "maxLength": 128},
#             "kind": KIND, "artifact_id": SHORT_ID,
#             "version_range": {"type": "string", "minLength": 1, "maxLength": 128},
#             "required": {"type": "boolean"}, "priority": {"type": "integer", "minimum": -100000, "maximum": 100000},
#         },
#         "additionalProperties": False,
#     },
# },
# {
#     "name": "memory_policy_delete",
#     "description": "Delete an organization artifact policy.",
#     "inputSchema": {
#         "type": "object", "required": ["organization_id", "policy_id"],
#         "properties": {"organization_id": SHORT_ID, "policy_id": {"type": "string", "format": "uuid"}},
#         "additionalProperties": False,
#     },
# },

TOOLS: list[dict[str, Any]] = [
    # --- Repository Registry -------------------------------------------------
    {
        "name": "memory_repo_list",
        "description": (
            "List registered artifact repositories. "
            "Each entry includes the repository URL, tracked artifact kinds, "
            "and the latest known release version."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind": KIND,
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "memory_repo_check_updates",
        "description": (
            "Check registered repositories for newer artifact releases. "
            "Returns a summary of available updates per repository. "
            "The user decides whether to apply each update."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_url": {"type": "string", "minLength": 1, "maxLength": 2048},
                "kind": KIND,
            },
            "additionalProperties": False,
        },
    },
    # --- Work Handoff --------------------------------------------------------
    {
        "name": "memory_handoff_push",
        "description": "Validate and register a completed Core Task/Result pair for handoff.",
        "inputSchema": {
            "type": "object",
            "required": [
                "project_id", "unit_id", "phase_attempt_id", "phase_id", "result_status", "classification",
                "task_envelope", "result_envelope", "context_digest", "lock_snapshot_digest", "envelope_digest",
            ],
            "properties": {
                "project_id": SHORT_ID, "unit_id": SHORT_ID, "phase_attempt_id": SHORT_ID, "phase_id": SHORT_ID,
                "result_status": {"enum": ["succeeded", "failed", "cancelled", "lost"]},
                "classification": CLASSIFICATION,
                "task_summary": {"type": "string", "maxLength": 4096},
                "passed_checks": {"type": "array", "items": {"type": "string", "minLength": 1}, "maxItems": 100, "uniqueItems": True},
                "artifacts_produced": {"type": "array", "items": {"type": "object"}, "maxItems": 100},
                "task_envelope": {"type": "object", "minProperties": 1},
                "result_envelope": {"type": "object", "minProperties": 1},
                "context_digest": DIGEST,
                "raw_output": {"type": "string"},
                "handoff_note": {"type": "string", "maxLength": 16384},
                "lock_snapshot_digest": DIGEST, "envelope_digest": DIGEST,
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "memory_handoff_list",
        "description": "List non-expired pending handoffs for the authenticated project.",
        "inputSchema": {
            "type": "object", "required": ["project_id"],
            "properties": {"project_id": SHORT_ID, "unit_id": SHORT_ID},
            "additionalProperties": False,
        },
    },
    {
        "name": "memory_handoff_pull",
        "description": "Atomically claim a handoff using the compatibility one-shot operation.",
        "inputSchema": {
            "type": "object", "required": ["project_id", "handoff_id"],
            "properties": {"project_id": SHORT_ID, "handoff_id": {"type": "string", "format": "uuid"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "memory_handoff_claim",
        "description": "Acquire or replay a recoverable, token-bound handoff lease.",
        "inputSchema": {
            "type": "object", "required": ["project_id", "handoff_id", "claim_token"],
            "properties": {
                "project_id": SHORT_ID,
                "handoff_id": {"type": "string", "format": "uuid"},
                "claim_token": CLAIM_TOKEN,
                "lease_seconds": {"type": "integer", "minimum": 1, "maximum": 86400},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "memory_handoff_get_claimed",
        "description": "Recover an active handoff claim response using its client-held token.",
        "inputSchema": {
            "type": "object", "required": ["project_id", "handoff_id", "claim_token"],
            "properties": {
                "project_id": SHORT_ID,
                "handoff_id": {"type": "string", "format": "uuid"},
                "claim_token": CLAIM_TOKEN,
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "memory_handoff_ack",
        "description": "Idempotently acknowledge successful processing of an active claim generation.",
        "inputSchema": {
            "type": "object", "required": ["project_id", "handoff_id", "claim_token", "claim_generation"],
            "properties": {
                "project_id": SHORT_ID,
                "handoff_id": {"type": "string", "format": "uuid"},
                "claim_token": CLAIM_TOKEN,
                "claim_generation": {"type": "integer", "minimum": 1},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "memory_handoff_nack",
        "description": "Idempotently release an active claim generation using a bounded reason code.",
        "inputSchema": {
            "type": "object", "required": ["project_id", "handoff_id", "claim_token", "claim_generation", "reason_code"],
            "properties": {
                "project_id": SHORT_ID,
                "handoff_id": {"type": "string", "format": "uuid"},
                "claim_token": CLAIM_TOKEN,
                "claim_generation": {"type": "integer", "minimum": 1},
                "reason_code": CLAIM_REASON,
            },
            "additionalProperties": False,
        },
    },
]

TOOL_MAP = {tool["name"]: tool for tool in TOOLS}
TOOL_NAMES = set(TOOL_MAP)
