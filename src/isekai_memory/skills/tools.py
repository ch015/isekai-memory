"""Strict, bounded native Skill input contracts."""

from isekai_memory.experience.tools import _CURSOR, _ID, _TEXT, _UUID, _VERSION, _VISIBILITY, _tool

NAME = {"type": "string", "minLength": 1, "maxLength": 64, "pattern": "^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$"}
SOURCES = {
    "type": "array", "minItems": 1, "maxItems": 8, "uniqueItems": True,
    "items": {"type": "object", "required": ["memory_id", "version"],
              "properties": {"memory_id": _UUID, "version": _VERSION}, "additionalProperties": False},
}


def texts(limit, count):
    return {"type": "array", "minItems": 1, "maxItems": count, "uniqueItems": True,
            "items": {**_TEXT, "maxLength": limit}}


BODY = {
    "type": "object", "required": ["title", "description", "triggers", "steps", "validation"],
    "properties": {
        "title": {**_TEXT, "maxLength": 200}, "description": {**_TEXT, "maxLength": 512},
        "triggers": texts(256, 8), "validation": texts(512, 8),
        "steps": {"type": "array", "minItems": 1, "maxItems": 12, "items": {
            "type": "object", "required": ["instruction", "sources"], "additionalProperties": False,
            "properties": {"instruction": {**_TEXT, "maxLength": 1024},
                           "sources": {"type": "array", "minItems": 1, "maxItems": 8, "uniqueItems": True, "items": _UUID}},
        }},
        "resources": {"type": "array", "maxItems": 4, "items": {
            "type": "object", "required": ["name", "content"], "additionalProperties": False,
            "properties": {"name": NAME, "content": {**_TEXT, "maxLength": 4096}},
        }},
    }, "additionalProperties": False,
}

_SUBMIT = {"idempotency_key": _ID, "sources": SOURCES, "body": BODY}
_STATUS = {"enum": ["pending", "active", "rejected", "archived", "superseded", "stale", "forgotten"], "default": "pending"}
SKILL_TOOLS = [
    _tool("memory_skill_generate", "Admin-only: queue a reference-only scaffold from approved successful procedures; manual revision required before approval.",
          ["sources"], {"sources": SOURCES}),
    _tool("memory_skill_propose", "Propose a pending native Skill from exact approved experience versions. Never installs or executes.",
          ["name", "idempotency_key", "sources", "body"], {"name": NAME, **_SUBMIT}),
    _tool("memory_skill_revise", "Admin-only complete immutable revision, fenced by latest revision number. Never overwrites content.",
          ["skill_id", "expected_revision", "idempotency_key", "sources", "body"],
          {"skill_id": _UUID, "expected_revision": _VERSION, **_SUBMIT}),
    _tool("memory_skill_review", "Admin-only version-fenced approve/reject/archive/forget. Generated scaffolds must first be manually revised.",
          ["revision_id", "expected_version", "action"], {"revision_id": _UUID, "expected_version": _VERSION,
          "action": {"enum": ["approve", "reject", "archive", "forget"]}}),
    _tool("memory_skill_list", "Admin-only bounded review/history metadata; no instruction bodies.",
          [], {"skill_id": _UUID, "status": _STATUS, "cursor": _CURSOR,
               "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 10}}),
    _tool("memory_skill_inspect", "Admin-only draft inspection, review events and source freshness; forgotten bodies remain erased.",
          ["revision_id"], {"revision_id": _UUID}),
    _tool("memory_skill_read", "Read one active fresh reviewed Skill as data; this does not authorize installation or execution.",
          ["revision_id"], {"revision_id": _UUID, **_VISIBILITY}),
    _tool("memory_skill_export", "Admin-only explicit deterministic unsigned native Skill archive; active review version and exact source Lock required.",
          ["revision_id", "expected_version", "source_lock_digest"],
          {"revision_id": _UUID, "expected_version": _VERSION, **_VISIBILITY}),
]
