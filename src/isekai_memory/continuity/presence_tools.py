"""Strict M9 presence APIs; project observation is separate from continuity policy."""

from isekai_memory.experience.tools import _CLASSIFICATION, _CURSOR, _ID, _UUID, _tool

VERSION = {"type": "integer", "minimum": 0, "maximum": 2147483646}
TOKEN = {"type": "string", "minLength": 32, "maxLength": 256, "pattern": r"^[A-Za-z0-9_-]+$", "not": {"pattern": r"\s"}}
POLICY = {
    "type": "object", "additionalProperties": False,
    "required": ["enabled", "heartbeat_seconds", "stale_after_seconds", "idle_after_seconds", "retention_hours"],
    "properties": {"enabled": {"type": "boolean"}, "heartbeat_seconds": {"type": "integer", "minimum": 10, "maximum": 60},
                   "stale_after_seconds": {"type": "integer", "minimum": 45, "maximum": 300},
                   "idle_after_seconds": {"type": "integer", "minimum": 60, "maximum": 3600},
                   "retention_hours": {"type": "integer", "minimum": 1, "maximum": 720}},
}
HOST = {"enum": ["codex", "claude", "kiro", "unknown"]}
LINKS = {"work_unit_id": {"anyOf": [_UUID, {"type": "null"}]},
         "checkpoint_id": {"anyOf": [_UUID, {"type": "null"}]}}
AUTH = {"session_id": _UUID, "session_token": TOKEN}
REPORT = {
    "sequence": {**VERSION, "minimum": 1}, "state_sequence": VERSION,
    "reported_state": {"enum": ["running", "waiting_approval", "blocked", "idle", "unknown"]},
    "observation_scope": {"enum": ["worker", "controller", "partial"]},
    "state_observation_available": {"type": "boolean"},
    "active_work_count": {"type": "integer", "minimum": 0, "maximum": 128},
    "policy_version": VERSION, "classification": _CLASSIFICATION, **LINKS,
}
READ = {"scope": {"enum": ["mine", "project"], "default": "mine"}, "max_classification": _CLASSIFICATION,
        "include_ended": {"type": "boolean"}, "host_kind": HOST,
        "limit": {"type": "integer", "minimum": 1, "maximum": 50}, "cursor": _CURSOR}
PRESENCE_TOOLS = [
    _tool("memory_presence_policy_get", "Read versioned observation policy. Missing policy disables collection, not authentication.", [], {}),
    _tool("memory_presence_policy_set", "Admin: replace presence policy with version, reason and idempotent receipt. Does not activate any client or change work ownership.",
          ["policy", "expected_version", "idempotency_key", "reason"],
          {"policy": POLICY, "expected_version": VERSION, "idempotency_key": _ID, "reason": {**_ID, "maxLength": 2048}}),
    _tool("memory_presence_register", "Register your explicitly enabled Core observer. Stable instance plus private session token makes retries non-refreshing. Not proof of human presence.",
          ["client_instance_id", "session_token", "host_kind", "session_kind", "classification"],
          {"client_instance_id": _UUID, "session_token": TOKEN, "host_kind": HOST,
           "session_kind": {"enum": ["worker", "controller"]}, "classification": _CLASSIFICATION,
           "parent_session_id": {"anyOf": [_UUID, {"type": "null"}]}}),
    _tool("memory_presence_heartbeat", "Report current observed work state with monotonic transport/state sequences. Never renews work leases. Do not replay offline heartbeat history.",
          [*AUTH, *REPORT], {**AUTH, **REPORT}),
    _tool("memory_presence_end", "End your session using its private token and next sequence. Ended or retired sessions cannot be revived by late reports.",
          [*AUTH, "sequence"], {**AUTH, "sequence": {**VERSION, "minimum": 1}}),
    _tool("memory_presence_list", "Read bounded authorized session metadata and derived idle/freshness. Project scope is admin-only. No session token hashes.", [], READ),
    _tool("memory_presence_users", "Read user aggregates from the complete authorized open-session set, not from a single sessions page. Idle is observed Core inactivity, not human absence.", [], READ),
    _tool("memory_presence_prune", "Admin: retire expired observation metadata in bounded batches. Keeps minimal anti-replay tombstones; never changes work leases or ownership.",
          ["idempotency_key", "reason"], {"idempotency_key": _ID, "reason": {**_ID, "maxLength": 2048},
                                       "limit": {"type": "integer", "minimum": 1, "maximum": 500}}),
]
PRESENCE_SCOPES = {tool["name"]: "read" for tool in PRESENCE_TOOLS}
PRESENCE_SCOPES.update(dict.fromkeys(["memory_presence_register", "memory_presence_heartbeat", "memory_presence_end"], "write"))
PRESENCE_SCOPES.update(dict.fromkeys(["memory_presence_policy_set", "memory_presence_prune"], "admin"))
