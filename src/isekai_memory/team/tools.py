"""Bounded project-scoped M6 contracts. Actor identity always comes from authentication."""

from isekai_memory.experience.tools import (
    _CLASSIFICATION,
    _CURSOR,
    _ID,
    _TEXT,
    _UUID,
    _VERSION,
    _VISIBILITY,
    _tool,
)

DIGEST = {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
DATE = {"type": "string", "format": "date-time", "maxLength": 64}
ASSET = {"asset_kind": {"enum": ["experience", "skill", "knowledge"]}, "asset_id": _UUID, "asset_version": _VERSION}
PAGE = {"cursor": _CURSOR, "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 10}}
TEAM_TOOLS = [
    _tool("memory_grant_create", "Owner admin: grant one exact fresh asset version to one consumer project for reference-only reads.",
          [*ASSET, "consumer_project_id", "expires_at", "max_classification", "idempotency_key"],
          {**ASSET, **_VISIBILITY, "consumer_project_id": _ID, "expires_at": DATE, "idempotency_key": _ID}),
    _tool("memory_grant_revoke", "Owner admin: permanently revoke a version-fenced grant. Cannot erase copies already delivered.",
          ["grant_id", "expected_version"], {"grant_id": _UUID, "expected_version": _VERSION}),
    _tool("memory_grant_list", "Owner admin: bounded grant metadata, including revoked/expired entries; no asset bodies.", [], PAGE),
    _tool("memory_shared_read", "Consumer project: recheck exact grant and live asset on every read. No export, transitive sharing or cache authority.",
          ["grant_id", "grant_version"], {"grant_id": _UUID, "grant_version": _VERSION, **_VISIBILITY}),
    _tool("memory_knowledge_sync", "Admin: explicitly publish a bounded pushed Wiki snapshot. No network fetch; freshness is publisher-reported with at most seven-day validity.",
          ["provider", "source_key", "source_revision", "expected_version", "classification", "title", "content", "content_digest", "valid_until"],
          {"provider": {"const": "pushed_wiki_v1"}, "source_key": _ID, "source_revision": _ID,
           "expected_version": {"type": "integer", "minimum": 0, "maximum": 2147483645}, "classification": _CLASSIFICATION,
           "title": {**_TEXT, "maxLength": 200}, "content": {**_TEXT, "maxLength": 8192}, "content_digest": DIGEST, "valid_until": DATE}),
    _tool("memory_knowledge_delete", "Admin: erase current snapshot prose, preserve revision receipts and invalidate old grants.",
          ["document_id", "expected_version"], {"document_id": _UUID, "expected_version": _VERSION}),
    _tool("memory_knowledge_list", "Admin: bounded source inventory metadata; includes expired/deleted entries, never content.", [], PAGE),
    _tool("memory_knowledge_read", "Read current unexpired pushed knowledge as untrusted reference data, not verified live upstream state.",
          ["document_id"], {"document_id": _UUID, "expected_version": _VERSION, "max_classification": _CLASSIFICATION}),
    _tool("memory_skill_import", "Admin: validate a deterministic M5 native archive into quarantine only. Unsigned provenance is a claim, not trust or installation.",
          ["archive_base64", "archive_digest", "manifest_digest", "artifact_digest", "classification", "idempotency_key"],
          {"archive_base64": {"type": "string", "minLength": 1, "maxLength": 349528}, "archive_digest": DIGEST,
           "manifest_digest": DIGEST, "artifact_digest": DIGEST, "classification": _CLASSIFICATION, "idempotency_key": _ID}),
    _tool("memory_skill_import_inspect", "Admin-only quarantine inspection; source claims are not locally approved evidence.",
          ["import_id"], {"import_id": _UUID, "max_classification": _CLASSIFICATION}),
    _tool("memory_skill_import_list", "Admin-only bounded quarantine/erasure metadata inventory; no imported bodies or source claims.",
          [], {**PAGE, "status": {"enum": ["quarantined", "forgotten"], "default": "quarantined"}}),
    _tool("memory_skill_import_forget", "Admin: erase quarantined body/resources/source claims while retaining conflict and erasure receipts.",
          ["import_id", "expected_version"], {"import_id": _UUID, "expected_version": _VERSION}),
    _tool("memory_feedback_record", "Write one explicit immutable actor/asset-version observation. Reported outcomes require same-project handoff evidence; never updates ranking or approval.",
          [*ASSET, "usefulness", "outcome", "idempotency_key"],
          {**ASSET, "grant_id": _UUID, "grant_version": _VERSION,
           "usefulness": {"enum": ["helpful", "not_helpful", "uncertain"]},
           "outcome": {"enum": ["not_attempted", "succeeded", "failed"]}, "handoff_id": _UUID, "idempotency_key": _ID}),
    _tool("memory_feedback_list", "Admin-only bounded project feedback records. Counts are not success, truth, trust or approval.",
          [], {**PAGE, "asset_id": _UUID}),
]
TEAM_SCOPES = {tool["name"]: "admin" for tool in TEAM_TOOLS}
TEAM_SCOPES.update(memory_shared_read="read", memory_knowledge_read="read", memory_feedback_record="write")
