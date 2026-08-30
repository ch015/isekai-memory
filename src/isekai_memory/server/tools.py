"""MCP tool catalog for Artifact Registry, Policy, and Work Handoff."""

from __future__ import annotations

from typing import Any

DIGEST = {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
SHORT_ID = {"type": "string", "minLength": 1, "maxLength": 128}
KIND = {"enum": ["foundation", "preset"]}
CLASSIFICATION = {"enum": ["public", "internal", "confidential", "restricted"]}
CLAIM_TOKEN = {"type": "string", "minLength": 32, "maxLength": 256, "pattern": "^[A-Za-z0-9_-]+$"}
CLAIM_REASON = {"enum": ["retryable", "processing_failed", "shutdown", "cancelled"]}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "memory_artifact_resolve",
        "description": "Resolve required artifacts for the authenticated project using organization policy.",
        "inputSchema": {
            "type": "object", "required": ["project_id", "organization_id"],
            "properties": {"project_id": SHORT_ID, "organization_id": SHORT_ID},
            "additionalProperties": False,
        },
    },
    {
        "name": "memory_artifact_fetch",
        "description": "Fetch an immutable artifact archive after logical digest verification.",
        "inputSchema": {
            "type": "object", "required": ["artifact_id", "kind", "version", "expected_artifact_digest"],
            "properties": {
                "artifact_id": SHORT_ID, "kind": KIND,
                "version": {"type": "string", "minLength": 1, "maxLength": 64},
                "expected_artifact_digest": DIGEST,
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "memory_artifact_publish",
        "description": "Verify and publish a Core-compatible artifact archive.",
        "inputSchema": {
            "type": "object",
            "required": ["artifact_id", "kind", "version", "archive_base64", "manifest_digest", "artifact_digest", "archive_digest"],
            "properties": {
                "artifact_id": SHORT_ID, "kind": KIND,
                "version": {"type": "string", "minLength": 1, "maxLength": 64},
                "archive_base64": {"type": "string", "minLength": 1},
                "manifest_digest": DIGEST, "artifact_digest": DIGEST, "archive_digest": DIGEST,
                "metadata": {"type": "object"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "memory_policy_upsert",
        "description": "Create or update one deterministic organization artifact policy.",
        "inputSchema": {
            "type": "object",
            "required": ["organization_id", "project_pattern", "kind", "artifact_id", "version_range"],
            "properties": {
                "organization_id": SHORT_ID, "project_pattern": {"type": "string", "minLength": 1, "maxLength": 128},
                "kind": KIND, "artifact_id": SHORT_ID,
                "version_range": {"type": "string", "minLength": 1, "maxLength": 128},
                "required": {"type": "boolean"}, "priority": {"type": "integer", "minimum": -100000, "maximum": 100000},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "memory_policy_delete",
        "description": "Delete an organization artifact policy.",
        "inputSchema": {
            "type": "object", "required": ["organization_id", "policy_id"],
            "properties": {"organization_id": SHORT_ID, "policy_id": {"type": "string", "format": "uuid"}},
            "additionalProperties": False,
        },
    },
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
