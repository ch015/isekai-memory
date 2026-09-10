"""Source-backed experience proposal, governance and bounded retrieval."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from isekai_memory.experience import repository
from isekai_memory.retrieval.citations import attach
from isekai_memory.retrieval.service import search as search
from isekai_memory.server.errors import MemoryToolError

CLASSIFICATIONS = ("public", "internal", "confidential", "restricted")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _normalize(value: str, *, limit: int) -> str:
    normalized = unicodedata.normalize("NFC", value).strip()
    if len(normalized) > limit:
        raise MemoryToolError(
            "Normalized experience text exceeds its field limit",
            code=-32602,
            data={"error_code": "MEM-EXPERIENCE-0005"},
        )
    return normalized


def _search_text(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _serialize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            ("memory_id" if key == "id" else key): _serialize(item) if key != "source" else item
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    return value.isoformat() if isinstance(value, datetime) else str(value) if isinstance(value, UUID) else value


def _visibility(arguments: dict[str, Any]) -> dict[str, Any]:
    maximum = arguments.get("max_classification", "internal")
    return {
        "project_id": arguments["project_id"],
        "classifications": list(CLASSIFICATIONS[: CLASSIFICATIONS.index(maximum) + 1]),
        "source_lock_digest": arguments.get("source_lock_digest"),
    }


async def _submit(arguments: dict[str, Any], *, actor_id: str, correction: bool, connection=None) -> dict[str, Any]:
    material = {
        "source_handoff_id": str(UUID(arguments["source_handoff_id"])) if "source_handoff_id" in arguments else None,
        "kind": arguments["kind"],
        "title": _normalize(arguments["title"], limit=200),
        "content": _normalize(arguments["content"], limit=4096),
        "tags": sorted({_normalize(tag, limit=64) for tag in arguments.get("tags", [])}),
        "expires_at": (
            datetime.fromisoformat(arguments["expires_at"].upper().replace("Z", "+00:00")).astimezone(UTC).isoformat()
            if "expires_at" in arguments
            else None
        ),
    }
    # Preserve the exact M1 digest when the new optional field is omitted.
    if "valid_from" in arguments:
        material["valid_from"] = (
            datetime.fromisoformat(arguments["valid_from"].upper().replace("Z", "+00:00")).astimezone(UTC).isoformat()
        )
    parent = {}
    if correction:
        parent = {"memory_id": str(UUID(arguments["memory_id"])), "expected_version": arguments["expected_version"]}
        material.update(parent)
    digest = "sha256:" + hashlib.sha256(_json(material).encode("utf-8")).hexdigest()
    fingerprint = (
        "sha256:"
        + hashlib.sha256(
            (material["kind"] + "\n" + " ".join(_search_text(material["content"]).split())).encode()
        ).hexdigest()
    )
    return await repository.propose(
        project_id=arguments["project_id"],
        actor_id=actor_id,
        source_handoff_id=material["source_handoff_id"],
        idempotency_key=arguments["idempotency_key"],
        kind=material["kind"],
        title=material["title"],
        content=material["content"],
        tags=material["tags"],
        search_text=_search_text(" ".join([material["title"], material["content"], *material["tags"]])),
        submission_digest=digest,
        content_fingerprint=fingerprint,
        **parent,
        valid_from=datetime.fromisoformat(material["valid_from"]) if material.get("valid_from") else None,
        expires_at=datetime.fromisoformat(material["expires_at"]) if material["expires_at"] else None,
        **({"connection": connection} if connection is not None else {}),
    )


async def propose(arguments: dict[str, Any], *, actor_id: str, connection=None) -> dict[str, Any]:
    return await _submit(arguments, actor_id=actor_id, correction=False, connection=connection)


async def revise(arguments: dict[str, Any], *, actor_id: str) -> dict[str, Any]:
    return await _submit(arguments, actor_id=actor_id, correction=True)


async def review(arguments: dict[str, Any], *, actor_id: str) -> dict[str, Any]:
    return await repository.review(
        project_id=arguments["project_id"],
        memory_id=str(UUID(arguments["memory_id"])),
        actor_id=actor_id,
        action=arguments["action"],
        expected_version=arguments["expected_version"],
    )


async def list_for_review(arguments: dict[str, Any]) -> dict[str, Any]:
    return _serialize(
        await repository.list_for_review(
            project_id=arguments["project_id"],
            status=arguments.get("status", "pending"),
            limit=arguments.get("limit", 20),
            offset=arguments.get("offset", 0),
            cursor=arguments.get("cursor"),
        )
    )


async def history(arguments: dict[str, Any]) -> dict[str, Any]:
    return _serialize(
        await repository.history(
            project_id=arguments["project_id"],
            memory_id=str(UUID(arguments["memory_id"])),
            limit=arguments.get("limit", 20),
            cursor=arguments.get("cursor"),
        )
    )


async def release_suppression(arguments: dict[str, Any], *, actor_id: str) -> dict[str, Any]:
    return await repository.release_suppression(
        project_id=arguments["project_id"],
        memory_id=str(UUID(arguments["memory_id"])),
        actor_id=actor_id,
        expected_suppression_version=arguments["expected_suppression_version"],
    )


async def read(arguments: dict[str, Any]) -> dict[str, Any]:
    row = await repository.read(memory_id=arguments["memory_id"], **_visibility(arguments))
    return {"memory": {**_serialize(row), "citation": attach(row)["citation"]}, "usage": "reference_only"}
