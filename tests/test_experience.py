"""Experience contracts, identity boundaries, normalization and output budgets."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock
from uuid import uuid4

import asyncpg
import pytest

from isekai_memory.experience import service
from isekai_memory.main import dispatch_tool
from isekai_memory.retrieval import service as retrieval
from isekai_memory.server.auth import Principal, authorize_tool
from isekai_memory.server.errors import MemoryToolError
from isekai_memory.server.validation import validate_tool_arguments


def proposal() -> dict:
    return {
        "project_id": "p", "source_handoff_id": str(uuid4()), "idempotency_key": "decision-1",
        "kind": "decision", "title": "Keep lease receipts", "content": "Retry acknowledgement after response loss.",
    }


@pytest.mark.parametrize("name", [
    "memory_experience_propose", "memory_experience_list", "memory_experience_review", "memory_search", "memory_read",
    "memory_experience_revise", "memory_experience_history", "memory_experience_suppression_release",
])
def test_every_experience_tool_enforces_project_even_for_admin(name):
    with pytest.raises(MemoryToolError) as error:
        authorize_tool(Principal("reviewer", "p", frozenset({"admin"})), name, {"project_id": "other"})
    assert error.value.data["error_code"] == "MEM-AUTH-0003"


@pytest.mark.parametrize("scopes", [{"read"}, {"write"}, {"read", "write"}])
@pytest.mark.parametrize("name", ["memory_experience_list", "memory_experience_review", "memory_experience_revise", "memory_experience_history", "memory_experience_suppression_release"])
def test_proposal_writer_cannot_review_or_read_pending_queue(scopes, name):
    with pytest.raises(MemoryToolError) as error:
        authorize_tool(Principal("writer", "p", frozenset(scopes)), name, {"project_id": "p"})
    assert error.value.http_status == 403


@pytest.mark.parametrize("field,value", [
    ("created_by", "other"), ("classification", "public"), ("status", "active"),
    ("source", {}), ("title", "  \n"), ("content", "\t"), ("title", "x" * 201),
    ("expires_at", "2026-10-01"), ("expires_at", "2026-02-30T00:00:00Z"),
    ("expires_at", "2026-10-01T00:00:00"), ("tags", ["x"] * 17),
    ("content", "nul\x00"), ("title", "surrogate\ud800"), ("project_id", "nul\x00"),
    ("expires_at", "9999-12-31T23:59:59-23:59"), ("expires_at", "2026-10-01T00:00:00+12:99"),
])
def test_proposal_rejects_forged_metadata_and_invalid_input(field, value):
    with pytest.raises(MemoryToolError):
        validate_tool_arguments("memory_experience_propose", {**proposal(), field: value})


async def test_dispatch_binds_actor_and_normalizes_idempotency_material(monkeypatch):
    monkeypatch.setattr("isekai_memory.projects.service.access", AsyncMock(return_value=(None, None)))
    calls = []

    async def capture(**kwargs):
        calls.append(kwargs)
        return {"memory_id": "record", "already_exists": False}

    monkeypatch.setattr(service.repository, "propose", capture)
    arguments = {**proposal(), "title": " cafe\u0301 ", "tags": ["lease", " retry "]}
    principal = Principal("actual-token-user", "p", frozenset({"write"}))
    await dispatch_tool("memory_experience_propose", arguments, principal)
    await dispatch_tool("memory_experience_propose", {**arguments, "title": "café", "tags": ["retry", "lease"]}, principal)
    assert calls[0]["actor_id"] == "actual-token-user"
    assert calls[0]["submission_digest"] == calls[1]["submission_digest"]
    assert calls[0]["title"] == "café"
    assert calls[0]["tags"] == ["lease", "retry"]
    assert "classification" not in calls[0]


async def test_normalization_cannot_overflow_storage_field_limits():
    # U+0344 expands to two combining marks under NFC.
    with pytest.raises(MemoryToolError):
        await dispatch_tool("memory_experience_propose", {**proposal(), "title": "\u0344" * 101})


@pytest.mark.parametrize("query", ["!!!", " ", " ".join(f"term{i}" for i in range(17)), "\ufb03" * 200])
async def test_search_rejects_unbounded_or_empty_terms_without_db(monkeypatch, query):
    async def unexpected(*args):
        pytest.fail("invalid search must not reach persistence")

    monkeypatch.setattr(retrieval, "fetch_rows", unexpected)
    with pytest.raises(MemoryToolError):
        await dispatch_tool("memory_search", {"project_id": "p", "query": query})


async def test_search_budget_includes_serialized_provenance(monkeypatch):
    rows = [
        {"id": uuid4(), "project_id": "p", "version": 2, "classification": "internal", "kind": "lesson",
         "title": "기억", "content": 'quote"\\\n' * 65, "tags": [], "source_handoff_id": uuid4(),
         "source_payload_digest": "sha256:" + "b" * 64, "source_lock_digest": "sha256:" + "a" * 64}
        for _ in range(6)
    ]
    captured = {}

    async def search(request, strategy):
        captured["classifications"] = list(request.classifications)
        return rows

    monkeypatch.setattr(retrieval, "fetch_rows", search)
    result = await service.search({"project_id": "p", "query": "기억", "max_chars": 2000})
    actual_size = len(json.dumps(result["items"], ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    assert 0 < result["returned"] < len(rows)
    assert result["truncated"]
    assert actual_size == result["result_chars"] <= 2000
    assert captured["classifications"] == ["public", "internal"]
    assert result["usage"] == "reference_only"


async def test_search_timeout_is_controlled(monkeypatch):
    async def timeout(*args):
        raise asyncpg.QueryCanceledError("statement timeout")

    monkeypatch.setattr(retrieval, "fetch_rows", timeout)
    with pytest.raises(MemoryToolError) as error:
        await service.search({"project_id": "p", "query": "lease"})
    assert error.value.http_status == 503
    assert error.value.data["error_code"] == "MEM-EXPERIENCE-0006"


@pytest.mark.parametrize("arguments", [
    {"cursor": "cursor", "offset": 0}, {"cursor": ""}, {"cursor": "x" * 2049},
    {"status": "deleted"}, {"limit": 0},
])
def test_queue_cursor_contract(arguments):
    with pytest.raises(MemoryToolError):
        validate_tool_arguments("memory_experience_list", {"project_id": "p", **arguments})


@pytest.mark.parametrize("cursor", ["!", "e30", "bnVsbA", "W10", "x" * 2049, 42])
def test_invalid_cursor_is_controlled(cursor):
    from isekai_memory.experience.pagination import decode
    with pytest.raises(MemoryToolError) as error:
        decode(cursor, ["queue", "p", "pending"])
    assert error.value.data["error_code"] == "MEM-EXPERIENCE-0010"


def test_generated_cursor_fits_even_for_maximum_unicode_project_id():
    from datetime import UTC, datetime

    from isekai_memory.experience.pagination import decode, encode
    row = {"id": uuid4(), "created_at": datetime.now(UTC)}
    scope = ["queue", "\U0001f310" * 128, "superseded"]
    cursor = encode(row, scope)
    assert len(cursor) <= 2048
    assert decode(cursor, scope) == (row["created_at"], row["id"])


async def test_old_submission_digest_is_unchanged_and_revision_is_distinct(monkeypatch):
    import hashlib
    calls = []

    async def capture(**kwargs):
        calls.append(kwargs)
        return {}

    monkeypatch.setattr(service.repository, "propose", capture)
    args = proposal()
    material = {key: args[key] for key in ("source_handoff_id", "kind", "title", "content")}
    material.update(tags=[], expires_at=None)
    expected = "sha256:" + hashlib.sha256(json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    await service.propose(args, actor_id="writer")
    await service.revise({**args, "memory_id": str(uuid4()), "expected_version": 2}, actor_id="admin")
    assert calls[0]["submission_digest"] == expected
    assert calls[1]["submission_digest"] != expected
    assert calls[0]["content_fingerprint"] == calls[1]["content_fingerprint"]
