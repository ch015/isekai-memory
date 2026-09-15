"""Bounded administration and read-only summary projection contracts."""

from isekai_memory.experience.tools import _CURSOR, _ID, _LIMIT, _UUID, _VERSION, _VISIBILITY, _tool

_SCOPE = {"phase_id": _ID, **_VISIBILITY}

GENERATION_TOOLS = [
    _tool("memory_generation_enqueue", "Admin-only: enqueue a bounded source scan or an approved-reference summary. Never runs a model.",
          ["kind"], {"kind": {"enum": ["extract", "summary"]}, "limit": _LIMIT, **_SCOPE}),
    _tool("memory_generation_list", "Admin-only durable job status, source watermarks and dead letters; no lease credentials.",
          [], {"status": {"enum": ["queued", "running", "succeeded", "dead"], "default": "dead"},
               "limit": _LIMIT, "cursor": _CURSOR}),
    _tool("memory_generation_retry", "Admin-only version-fenced dead-letter redrive. Adds at most three attempts, lifetime limit 30.",
          ["job_id", "expected_version"], {"job_id": _UUID, "expected_version": _VERSION}),
    _tool("memory_summary_read", "Read a fresh project/phase snapshot of approved references; stale snapshots return no text. Never generates.",
          [], {**_SCOPE, "max_chars": {"type": "integer", "minimum": 1000, "maximum": 16000, "default": 8000}}),
]

# Extraction scans the entire authorized project. Summary-only options must not be silently ignored.
GENERATION_TOOLS[0]["inputSchema"]["allOf"] = [{
    "if": {"properties": {"kind": {"const": "extract"}}},
    "then": {"not": {"anyOf": [{"required": [key]} for key in _SCOPE]}},
    "else": {"not": {"required": ["limit"]}},
}]
