"""Versioned M8 continuity APIs, separate from the single-recipient contract."""

from isekai_memory.continuity.presence_tools import PRESENCE_SCOPES, PRESENCE_TOOLS
from isekai_memory.continuity.usage_tools import USAGE_SCOPES, USAGE_TOOLS
from isekai_memory.experience.tools import _CLASSIFICATION, _CURSOR, _UUID, _tool
from isekai_memory.handoff.continuation import OPAQUE, RECIPIENT, SCHEMA, TEXT

VERSION = {"type": "integer", "minimum": 0, "maximum": 2147483645}
DIGEST = {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$", "not": {"pattern": r"\s"}}
DATE = {"type": "string", "format": "date-time", "maxLength": 40}
USERS = {"type": "array", "items": RECIPIENT, "minItems": 1, "maxItems": 32, "uniqueItems": True}
BACKUPS = {**USERS, "minItems": 0}
PATH = {"type": "string", "minLength": 1, "maxLength": 256}
POLICY = {
    "type": "object", "additionalProperties": False,
    "required": ["enabled", "default_recipient_user_ids", "default_backup_user_ids", "sender_rules",
                 "retention_hours", "lease_seconds", "checkpoint_interval_seconds", "checkpoint_max_bytes",
                 "checkpoint_allowed_paths", "allow_emergency_takeover"],
    "properties": {
        "enabled": {"type": "boolean"},
        "default_recipient_user_ids": USERS, "default_backup_user_ids": BACKUPS,
        "sender_rules": {"type": "array", "maxItems": 100, "items": {
            "type": "object", "additionalProperties": False,
            "required": ["from_user_id", "recipient_user_ids", "backup_user_ids"],
            "properties": {"from_user_id": RECIPIENT, "recipient_user_ids": USERS, "backup_user_ids": BACKUPS},
        }},
        "retention_hours": {"type": "integer", "minimum": 1, "maximum": 8760},
        "lease_seconds": {"type": "integer", "minimum": 30, "maximum": 3600},
        "checkpoint_interval_seconds": {"type": "integer", "minimum": 30, "maximum": 3600},
        "checkpoint_max_bytes": {"type": "integer", "minimum": 1024, "maximum": 1048576},
        "checkpoint_allowed_paths": {"type": "array", "items": PATH, "maxItems": 100, "uniqueItems": True},
        "allow_emergency_takeover": {"type": "boolean"},
    },
}
SNAPSHOT = {
    "type": "object", "additionalProperties": False, "required": ["schema_version", "files"],
    "properties": {
        "schema_version": {"type": "integer", "const": 1},
        "files": {"type": "array", "maxItems": 100, "items": {
            "type": "object", "additionalProperties": False, "required": ["path", "content_base64", "digest"],
            "properties": {"path": PATH, "content_base64": {"type": ["string", "null"], "maxLength": 1398104},
                           "digest": {"anyOf": [DIGEST, {"type": "null"}]}, "executable": {"type": "boolean"}},
        }},
    },
}
UNITS = {"type": "array", "minItems": 1, "maxItems": 32, "items": {
    "type": "object", "additionalProperties": False, "required": ["key", "summary", "assignee_user_ids"],
    "properties": {"key": OPAQUE, "summary": TEXT, "assignee_user_ids": USERS},
}}
PAGE = {"limit": {"type": "integer", "minimum": 1, "maximum": 50}, "cursor": _CURSOR}
MUTATION = {"idempotency_key": OPAQUE, "reason": TEXT}
CLAIM = {"unit_id": _UUID, "claim_token": {"type": "string", "minLength": 32, "maxLength": 256,
                                          "pattern": "^[A-Za-z0-9_-]+$", "not": {"pattern": r"\s"}}}
FENCE = {**CLAIM, "claim_generation": {**VERSION, "minimum": 1}}

CONTINUITY_TOOLS = [
    _tool("memory_collaboration_events", "Read-only durable scoped notifications, separate from list cursors. Encrypted commit-ordered catch-up; reset_required demands a fresh overview. No bodies, hidden counts, acknowledgement or lease mutation.",
          [], {"scope": {"enum": ["mine", "project"], "default": "mine"}, "max_classification": _CLASSIFICATION,
               "cursor": {"type": "string", "minLength": 1, "maxLength": 2048}, "limit": {"type": "integer", "minimum": 1, "maximum": 50}}),
    _tool("memory_collaboration_events_prune", "Admin: bounded notification retention cleanup, never erases immutable source audit. Old cursors must fully resync.",
          [*MUTATION], {**MUTATION}),
    _tool("memory_collaboration_overview", "Read-only scoped collaboration counts, authenticated identity and capabilities. Missing idle/usage telemetry is unavailable, never zero. Project-wide scope requires admin; allowed tools are scope-level hints, not resource approval.",
          [], {"scope": {"enum": ["mine", "project"], "default": "mine"}, "max_classification": _CLASSIFICATION,
               "include_inactive": {"type": "boolean"}, "include_acknowledged": {"type": "boolean"}}),
    _tool("memory_collaboration_list", "Read-only bounded M8 work, inbox, sent or checkpoint metadata. No bodies, acknowledgement, lease renewal or execution. Live scoped cursor; project-wide scope requires admin.",
          ["view"], {"view": {"enum": ["work", "inbox", "sent", "checkpoints"]}, **PAGE,
                     "scope": {"enum": ["mine", "project"], "default": "mine"}, "max_classification": _CLASSIFICATION,
                     "include_inactive": {"type": "boolean"}, "include_acknowledged": {"type": "boolean"}}),
    _tool("memory_continuity_policy_set", "Project admin: replace version-fenced continuity policy, sender 1:N rules, checkpoints and recovery limits. No execution approval.",
          ["policy", "expected_version", *MUTATION], {"policy": POLICY, "expected_version": VERSION, **MUTATION}),
    _tool("memory_continuity_policy_get", "Read project continuity policy and revision. Disabled or absent policy never grants capture authority.", [], {}),
    _tool("memory_continuity_members", "Admin: list bounded eligible project identities, never credentials or token hashes.", [], {**PAGE}),
    _tool("memory_checkpoint_save", "Save immutable in-progress state under your own identity. Optional bounded snapshot stores explicitly allowed files, never arbitrary archives.",
          ["work_id", "expected_version", "continuation", "classification", "lock_snapshot_digest", "idempotency_key"],
          {"work_id": OPAQUE, "expected_version": VERSION, "continuation": SCHEMA, "snapshot": SNAPSHOT,
           "classification": _CLASSIFICATION, "lock_snapshot_digest": DIGEST, "idempotency_key": OPAQUE}),
    _tool("memory_checkpoint_list", "List own checkpoint metadata, or project-wide metadata for admins. No snapshot bytes.", [],
          {**PAGE, "from_user_id": RECIPIENT, "work_id": OPAQUE}),
    _tool("memory_checkpoint_read", "Read a retained checkpoint as its publisher or project admin. No automatic restoration or execution.",
          ["checkpoint_id"], {"checkpoint_id": _UUID, "max_classification": _CLASSIFICATION}),
    _tool("memory_checkpoint_forget", "Admin: erase checkpoint body/snapshot and revoke dependent deliveries and work claims; immutable audit remains.",
          ["checkpoint_id", *MUTATION], {"checkpoint_id": _UUID, **MUTATION}),
    _tool("memory_continuity_publish", "Create atomic independent deliveries and explicitly scoped work units from a checkpoint or admin-promoted legacy handoff. No automatic work split or execution.",
          ["source_kind", "source_id", "expected_policy_version", *MUTATION],
          {"source_kind": {"enum": ["checkpoint", "handoff"]}, "source_id": _UUID,
           "expected_policy_version": VERSION, "recipient_user_ids": USERS, "work_units": UNITS, **MUTATION}),
    _tool("memory_continuity_inbox", "Read your independent recipient deliveries. One user's ack never consumes another's; live cursor, not notification feed.",
          [], {**PAGE, "include_acknowledged": {"type": "boolean"}, "max_classification": _CLASSIFICATION}),
    _tool("memory_continuity_status", "Publisher/recipient/admin: metadata, per-recipient intake and separate work states. Never claim-token hashes or source bytes.",
          ["bundle_id"], {"bundle_id": _UUID, "max_classification": _CLASSIFICATION}),
    _tool("memory_continuity_read", "Assigned recipient: read pinned shared context without taking a work lease. Admins do not impersonate recipients.",
          ["delivery_id"], {"delivery_id": _UUID, "max_classification": _CLASSIFICATION}),
    _tool("memory_continuity_ack", "Assigned recipient: idempotently acknowledge only your delivery; not work completion.",
          ["delivery_id", "idempotency_key"], {"delivery_id": _UUID, "idempotency_key": OPAQUE}),
    _tool("memory_continuity_reassign", "Admin: atomically replace recipients/work assignments with version/generation guards and audit. Optional emergency takeover requires enabled policy and explicit confirmation.",
          ["bundle_id", "expected_version", "expected_generations", "recipient_user_ids", "work_units", *MUTATION],
          {"bundle_id": _UUID, "expected_version": VERSION, "recipient_user_ids": USERS, "work_units": UNITS,
           "expected_generations": {"type": "object", "maxProperties": 32, "additionalProperties": VERSION},
           "emergency_takeover": {"type": "boolean"}, "takeover_unit_keys": {"type": "array", "items": OPAQUE, "maxItems": 32, "uniqueItems": True},
           "confirm_running_work_may_continue": {"const": True}, **MUTATION}),
    _tool("memory_continuity_claim", "Acquire one token-fenced work unit. All recipients may read context; only eligible assignees can own this unit.",
          [*CLAIM], {**CLAIM, "expected_generation": VERSION, "expected_routing_version": {**VERSION, "minimum": 1}}),
    _tool("memory_continuity_renew", "Renew only an active work claim to an absolute bounded deadline, without extending retention.",
          [*FENCE, "lease_expires_at"], {**FENCE, "lease_expires_at": DATE}),
    _tool("memory_continuity_release", "Release an active work lease or report completion with independent immutable receipt. Reported completion is not verified execution.",
          [*FENCE, "action", *MUTATION], {**FENCE, "action": {"enum": ["release", "complete"]}, **MUTATION}),
    _tool("memory_continuity_history", "Admin: bounded project continuity audit metadata and versioned policy/assignment decisions, not checkpoint bodies.",
          [], {**PAGE, "target_id": OPAQUE}),
]
next(tool for tool in CONTINUITY_TOOLS if tool["name"] == "memory_continuity_claim")["inputSchema"]["dependentRequired"] = {
    "expected_generation": ["expected_routing_version"], "expected_routing_version": ["expected_generation"],
}
CONTINUITY_SCOPES = {tool["name"]: "read" for tool in CONTINUITY_TOOLS}
CONTINUITY_SCOPES.update(dict.fromkeys([
    "memory_continuity_policy_set", "memory_continuity_members", "memory_checkpoint_forget",
    "memory_continuity_reassign", "memory_continuity_history", "memory_collaboration_events_prune",
], "admin"))
CONTINUITY_SCOPES.update(dict.fromkeys([
    "memory_checkpoint_save", "memory_continuity_publish", "memory_continuity_ack",
    "memory_continuity_claim", "memory_continuity_renew", "memory_continuity_release",
], "write"))
CONTINUITY_TOOLS.extend(PRESENCE_TOOLS)
CONTINUITY_SCOPES.update(PRESENCE_SCOPES)

CONTINUITY_TOOLS.extend(USAGE_TOOLS)
CONTINUITY_SCOPES.update(USAGE_SCOPES)
