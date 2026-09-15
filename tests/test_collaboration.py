"""M7 input, identity, pagination and metadata contracts without a database."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from isekai_memory.config import Settings
from isekai_memory.experience.pagination import encode
from isekai_memory.handoff import collaboration
from isekai_memory.handoff.tools import COLLABORATION_SCOPES
from isekai_memory.main import ToolDispatcher
from isekai_memory.server.auth import Principal, authorize_tool
from isekai_memory.server.errors import MemoryToolError
from isekai_memory.server.tools import TOOL_MAP
from isekai_memory.server.validation import validate_tool_arguments


def renew_args():
    return {"project_id": "project-1", "handoff_id": str(uuid4()), "claim_token": "x" * 32,
            "claim_generation": 1, "lease_expires_at": "2030-01-01T00:00:00Z"}


@pytest.mark.parametrize("tool", COLLABORATION_SCOPES)
def test_all_collaboration_tools_are_catalogued_and_project_scoped(tool):
    assert tool in TOOL_MAP
    principal = Principal("alice", "project-1", frozenset({"read", "write"}))
    authorize_tool(principal, tool, {"project_id": "project-1"})
    with pytest.raises(MemoryToolError):
        authorize_tool(principal, tool, {"project_id": "project-2"})
    with pytest.raises(MemoryToolError):
        authorize_tool(principal, tool, {})


def test_readers_can_observe_but_not_renew():
    principal = Principal("alice", "project-1", frozenset({"read"}))
    for name in ("memory_handoff_inbox", "memory_handoff_status"):
        authorize_tool(principal, name, {"project_id": "project-1"})
    with pytest.raises(MemoryToolError):
        authorize_tool(principal, "memory_handoff_renew", renew_args())


@pytest.mark.parametrize("extra", [
    {"actor_id": "bob"}, {"from_user": "bob"}, {"claimed_by": "bob"}, {"view": "all"},
    {"limit": 0}, {"limit": 101}, {"limit": True}, {"cursor": ""}, {"cursor": "x" * 2049},
    {"max_classification": "secret"},
])
def test_inbox_rejects_unsafe_or_unbounded_inputs(extra):
    with pytest.raises(MemoryToolError):
        validate_tool_arguments("memory_handoff_inbox", {"project_id": "project-1", **extra})


@pytest.mark.parametrize("extra", [
    {"lease_expires_at": "2030-01-01T00:00:00"}, {"lease_expires_at": "tomorrow"},
    {"lease_expires_at": "2030-13-01T00:00:00Z"}, {"lease_expires_at": "2030-01-01T00:00:60Z"},
    {"claim_generation": 0}, {"claim_generation": True}, {"claim_token": "short"},
    {"lease_seconds": 300}, {"actor_id": "bob"},
])
def test_renew_requires_bounded_absolute_deadline_and_fencing(extra):
    with pytest.raises(MemoryToolError):
        validate_tool_arguments("memory_handoff_renew", {**renew_args(), **extra})


@pytest.mark.asyncio
async def test_dispatcher_derives_inbox_actor(monkeypatch):
    captured = {}

    async def inbox(arguments, *, actor_id):
        captured.update(arguments=arguments, actor_id=actor_id)
        return {"items": []}

    monkeypatch.setattr(collaboration, "inbox", inbox)
    args = {"project_id": "project-1"}
    result = await ToolDispatcher(Settings())("memory_handoff_inbox", args, Principal("alice", "project-1", frozenset({"read"})))
    assert result == {"items": []} and captured["actor_id"] == "alice"


@pytest.mark.asyncio
async def test_renew_hashes_token_and_normalizes_timezone(monkeypatch):
    captured = {}

    async def renew_lease(**kwargs):
        captured.update(kwargs)
        return {"extended": True}

    monkeypatch.setattr(collaboration.store, "renew_lease", renew_lease)
    args = {**renew_args(), "lease_expires_at": "2030-01-01t09:00:00+09:00"}
    await ToolDispatcher(Settings())("memory_handoff_renew", args, Principal("alice", "project-1", frozenset({"write"})))
    assert captured["actor_id"] == "alice" and captured["generation"] == 1
    assert len(captured["token_digest"]) == 64 and "claim_token" not in captured
    assert captured["deadline"] == datetime(2030, 1, 1, tzinfo=UTC)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    {"project_id": "other"}, {"view": "sent"}, {"unit_id": "unit"}, {"max_classification": "restricted"},
])
async def test_cursor_cannot_cross_query_scope(change):
    scope = ["handoff-inbox-v1", "project-1", "alice", "available", "", "internal"]
    cursor = encode({"id": uuid4(), "created_at": datetime.now(UTC)}, scope)
    with pytest.raises(MemoryToolError) as caught:
        await collaboration.inbox({"project_id": "project-1", "cursor": cursor, **change}, actor_id="alice")
    assert caught.value.data["error_code"] == "MEM-HANDOFF-0009"


@pytest.mark.asyncio
async def test_cursor_cannot_cross_actor_and_malformed_cursor_has_handoff_error():
    cursor = encode({"id": uuid4(), "created_at": datetime.now(UTC)},
                    ["handoff-inbox-v1", "project-1", "alice", "available", "", "internal"])
    for value in (cursor, "invalid!", "e30"):
        with pytest.raises(MemoryToolError) as caught:
            await collaboration.inbox({"project_id": "project-1", "cursor": value}, actor_id="bob")
        assert caught.value.data["error_code"] == "MEM-HANDOFF-0009"


@pytest.mark.parametrize("status,lease_offset,retention_offset,expected", [
    ("pending", None, 60, "available"), ("claimed", 30, 60, "leased"),
    ("claimed", 0, 60, "lease_expired"), ("claimed", -1, 60, "lease_expired"),
    ("claimed", None, 60, "legacy_claimed"), ("acknowledged", 30, -1, "acknowledged"),
    ("pending", None, 0, "expired"), ("claimed", 30, -1, "expired"),
    ("expired", None, 60, "expired"),
])
def test_delivery_state_boundaries(status, lease_offset, retention_offset, expected):
    now = datetime.now(UTC)
    row = {"status": status, "expires_at": now + timedelta(seconds=retention_offset),
           "claim_lease_expires_at": None if lease_offset is None else now + timedelta(seconds=lease_offset)}
    assert collaboration.delivery_state(row, now) == expected
