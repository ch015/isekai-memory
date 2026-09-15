"""Pinned, opt-in M9 usage ledger contracts. No raw host events or caller actor."""
from isekai_memory.continuity.presence_tools import HOST, TOKEN, VERSION
from isekai_memory.continuity.usage_metrics import FIELDS, MAX_TOKENS, METHODS, QUALITIES, REASONS
from isekai_memory.experience.tools import _CLASSIFICATION, _CURSOR, _ID, _UUID, _tool

LABEL = {"type": "string", "minLength": 1, "maxLength": 128, "pattern": r"^[A-Za-z0-9][A-Za-z0-9._:+/-]*$", "not": {"pattern": r"\s"}}
DATE = {"type": "string", "format": "date-time", "maxLength": 40}
NULL = {"type": "null"}
COUNTER = {"type": "object", "additionalProperties": False,
           "required": ["value", "quality", "estimate_method", "omission_reason"],
           "properties": {"value": {"anyOf": [{"type": "integer", "minimum": 0, "maximum": MAX_TOKENS}, NULL]},
                          "quality": {"enum": list(QUALITIES)},
                          "estimate_method": {"enum": [None, *METHODS]}, "omission_reason": {"enum": [None, *REASONS]}}}
METRICS = {"type": "object", "additionalProperties": False, "required": list(FIELDS),
           "properties": dict.fromkeys(FIELDS, COUNTER)}
THRESHOLD = {"anyOf": [{"type": "integer", "minimum": 1, "maximum": MAX_TOKENS}, NULL]}
POLICY = {"type": "object", "additionalProperties": False,
          "required": ["enabled", "retention_days", "late_report_hours", "timezone", "project_alert_tokens", "user_alert_tokens"],
          "properties": {"enabled": {"type": "boolean"},
                         "retention_days": {"type": "integer", "minimum": 1, "maximum": 90},
                         "late_report_hours": {"type": "integer", "minimum": 1, "maximum": 168},
                         "timezone": LABEL, "project_alert_tokens": THRESHOLD, "user_alert_tokens": THRESHOLD}}
MUTATION = {"idempotency_key": _ID, "reason": {**_ID, "maxLength": 2048}}
BIND = {"work_unit_id": _UUID, "claim_token": TOKEN, "claim_generation": {**VERSION, "minimum": 1}}
REGISTER = {"execution_attempt_id": _UUID, "meter_epoch": _UUID, "session_token": TOKEN,
            "host_kind": HOST, "host_version": LABEL, "adapter_version": LABEL,
            "provider": LABEL, "model_id": LABEL, "classification": _CLASSIFICATION,
            "observation_scope": {"const": "exclusive_run"},
            "parent_session_id": {"anyOf": [_UUID, NULL]},
            "work_binding": {"anyOf": [{"type": "object", "additionalProperties": False,
                                       "required": list(BIND), "properties": BIND}, NULL]}}
AUTH = {"session_id": _UUID, "session_token": TOKEN}
REPORT = {"sequence": {**VERSION, "minimum": 1}, "metrics": METRICS,
          "semantics_version": {"const": 1}, "completion_state": {"enum": ["in_progress", "final"]},
          "coverage": {"enum": ["partial", "complete"]},
          "source_occurred_at": {"anyOf": [DATE, NULL]}}
READ = {"scope": {"enum": ["mine", "project"], "default": "mine"}, "max_classification": _CLASSIFICATION,
        "period": {"enum": ["today", "week", "custom"], "default": "today"}, "timezone": LABEL,
        "start_at": DATE, "end_at": DATE, "user_id": _ID, "host_kind": HOST, "model_id": LABEL, "work_unit_id": _UUID}
USAGE_TOOLS = [
    _tool("memory_usage_policy_get", "Read separate opt-in usage collection, retention and soft-alert policy.", [], {}),
    _tool("memory_usage_policy_set", "Admin: versioned full usage policy replacement with reason and receipt. Never starts observers or stops work.",
          ["policy", "expected_version", *MUTATION], {"policy": POLICY, "expected_version": VERSION, **MUTATION}),
    _tool("memory_usage_register", "Register your private reporter for one exclusive run attempt, independently of presence. Run rollups and external parent conversations are unsupported.",
          list(REGISTER), REGISTER),
    _tool("memory_usage_report", "Report one absolute run counter revision. Exact receipt retries do not double count; does not heartbeat or renew leases.",
          [*AUTH, *REPORT], {**AUTH, **REPORT}),
    _tool("memory_usage_summary", "Whole authorized retained set, separate reported/estimated/null totals and stable soft-alert identities. Not a billing or account quota API.",
          [], {**READ, "group_by": {"enum": ["none", "user", "host", "model", "work"]}}),
    _tool("memory_usage_list", "Bounded scoped usage metadata and latest counters, never private reporter tokens or source text.",
          [], {**READ, "limit": {"type": "integer", "minimum": 1, "maximum": 50}, "cursor": _CURSOR}),
    _tool("memory_usage_prune", "Admin: retire bounded expired usage rows, scrub metrics and preserve bounded anti-replay identities. Does not touch work or presence.",
          list(MUTATION), {**MUTATION, "limit": {"type": "integer", "minimum": 1, "maximum": 500}}),
]
USAGE_SCOPES = {tool["name"]: "read" for tool in USAGE_TOOLS}
USAGE_SCOPES.update(dict.fromkeys(["memory_usage_register", "memory_usage_report"], "write"))
USAGE_SCOPES.update(dict.fromkeys(["memory_usage_policy_set", "memory_usage_prune"], "admin"))
