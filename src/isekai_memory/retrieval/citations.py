"""Versioned provenance binding for search excerpts and full memory reads."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

BINDING_FIELDS = (
    "project_id",
    "memory_id",
    "version",
    "classification",
    "kind",
    "title",
    "source_handoff_id",
    "source_lock_digest",
    "source_payload_digest",
)


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def attach(row: dict, *, excerpt_chars: int = 512) -> dict:
    item = {
        ("memory_id" if key == "id" else key): str(value) if isinstance(value, UUID) else value
        for key, value in row.items()
    }
    content = item.pop("content")
    tags = item.pop("tags")
    item["excerpt"] = content[:excerpt_chars]
    citation = {
        "schema_version": 1,
        "content_digest": digest(
            canonical({"kind": item["kind"], "title": item["title"], "content": content, "tags": tags})
        ),
        "excerpt_digest": digest(item["excerpt"]),
    }
    binding = {key: item[key] for key in BINDING_FIELDS}
    if item.get("compatibility_digest") is not None:
        binding["compatibility_digest"] = item["compatibility_digest"]
        citation["schema_version"] = 2
    else:
        item.pop("compatibility_digest", None)
    citation["binding_digest"] = digest(canonical({**binding, **citation}))
    item["citation"] = citation
    return item
