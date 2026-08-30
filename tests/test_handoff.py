from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from isekai_memory.config import Settings
from isekai_memory.handoff.service import push_handoff
from isekai_memory.handoff.validation import validate_envelopes
from isekai_memory.server.errors import MemoryToolError
from tests.helpers import handoff_arguments


def test_envelope_correlation_is_enforced() -> None:
    arguments = handoff_arguments()
    arguments["result_envelope"]["task_id"] = "other-task"
    with pytest.raises(MemoryToolError, match="correlation mismatch"):
        validate_envelopes(arguments)


@pytest.mark.asyncio
async def test_push_passes_datetime_and_derived_actor(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    async def insert_handoff(**kwargs):
        captured.update(kwargs)
        return {"id": uuid4(), "created_at": datetime.now(UTC), "expires_at": kwargs["expires_at"]}

    monkeypatch.setattr("isekai_memory.handoff.service.queries.insert_handoff", insert_handoff)
    result = await push_handoff(handoff_arguments(), settings=Settings(), from_user="token-user")
    assert result["already_exists"] is False
    assert isinstance(captured["expires_at"], datetime)
    assert captured["from_user"] == "token-user"
    assert captured["payload_digest"].startswith("sha256:")


@pytest.mark.asyncio
async def test_retry_returns_existing_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}
    identity = uuid4()
    created = datetime.now(UTC)

    async def insert_handoff(**kwargs):
        captured.update(kwargs)
        return None

    async def existing(**kwargs):
        return {"id": identity, "payload_digest": captured["payload_digest"], "created_at": created, "expires_at": created}

    monkeypatch.setattr("isekai_memory.handoff.service.queries.insert_handoff", insert_handoff)
    monkeypatch.setattr("isekai_memory.handoff.service.queries.get_handoff_by_attempt", existing)
    result = await push_handoff(handoff_arguments(), settings=Settings(), from_user="token-user")
    assert result == {
        "handoff_id": str(identity),
        "created_at": created.isoformat(),
        "expires_at": created.isoformat(),
        "already_exists": True,
    }
