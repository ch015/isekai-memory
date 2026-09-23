"""Small member-facing API for project history, materials and retrieval with citations."""
from .tools import ID, TEXT, tool

UUID = {"type": "string", "format": "uuid"}
KINDS = {"enum": ["activity", "material", "result"]}
BASE = {"project_id": ID, "expected_actor": TEXT}
REF = {"type": "object", "additionalProperties": False, "required": ["label", "uri"], "properties": {
    "label": {"type": "string", "minLength": 1, "maxLength": 200},
    "uri": {"type": "string", "minLength": 1, "maxLength": 2048},
    "digest": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
}}
RECORD_TOOLS = [
    tool("memory_project_record_put", "Share one immutable member record, idempotent by ID and authenticated author. Reference data, not workflow authority.", {
        **BASE, "record_id": UUID, "kind": KINDS,
        "title": {"type": "string", "minLength": 1, "maxLength": 200},
        "body": {"type": "string", "maxLength": 8192}, "unit_id": {"type": ["string", "null"], "maxLength": 128},
        "occurred_at": {"type": "string", "format": "date-time", "maxLength": 64},
        "refs": {"type": "array", "maxItems": 20, "items": REF},
    }, [*BASE, "record_id", "kind", "title", "body", "occurred_at", "refs"]),
    tool("memory_project_record_list", "Search or page active records of this project only. Always returns authors and source citations; no implicit approval.", {
        **BASE, "query": {"type": "string", "minLength": 1, "maxLength": 200}, "kind": KINDS,
        "unit_id": {"type": "string", "minLength": 1, "maxLength": 128},
        "before": {"type": "integer", "minimum": 1, "maximum": 9223372036854775807},
        "limit": {"type": "integer", "minimum": 1, "maximum": 50},
    }, ["project_id"]),
    tool("memory_project_record_remove", "Author or project owner: erase a record's content and remove it from search; preserve its idempotency tombstone.", {
        **BASE, "record_id": UUID,
    }, [*BASE, "record_id"]),
]
RECORD_SCOPES = {item["name"]: ("read" if item["name"].endswith("_list") else "write") for item in RECORD_TOOLS}
