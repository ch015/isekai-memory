"""Durable event DB contracts: visibility before pagination, transaction ordering, retention and revocation."""
import asyncio
import secrets
from uuid import uuid4

from isekai_memory.continuity import events
from isekai_memory.continuity.common import transaction
from tests.test_continuity_postgres import checkpoint, configure, publish, reassignment, status
from tests.test_experience_postgres import harness as harness  # noqa: F401
from tests.test_experience_postgres import pytestmark as pytestmark


async def feed(h, cursor=None, role="writer", **args):
    if cursor:
        args["cursor"] = cursor
    return await h.call("memory_collaboration_events", args, role=role)


async def test_initial_then_page_scoped_committed_metadata_without_hidden_count(harness):
    h = harness
    await configure(h)
    initial = await feed(h)
    assert initial["reset_required"] and initial["reset_reason"] == "initial" and initial["items"] == []
    hidden, _ = await checkpoint(h, classification="restricted")
    first, args = await checkpoint(h)
    second, _ = await checkpoint(h)
    await h.call("memory_checkpoint_save", args, role="writer")  # exact receipt, no extra event
    page = await feed(h, initial["next_cursor"], limit=1)
    assert [row["target_id"] for row in page["items"]] == [first["checkpoint_id"]]
    assert page["has_more"] and not page["reset_required"]
    more = await feed(h, page["next_cursor"], limit=1)
    assert [row["target_id"] for row in more["items"]] == [second["checkpoint_id"]]
    assert not more["has_more"] and not (await feed(h, more["next_cursor"]))["items"]
    assert hidden["checkpoint_id"] not in str(page) + str(more)
    assert all(set(row) == {"id", "topic", "target_id", "classification", "revision", "occurred_at"} for row in page["items"])
    assert not {"position", "total", "hidden_count", "audience", "details"} & set(page)
    await h.call("memory_collaboration_events", {"cursor": initial["next_cursor"]}, role="admin2", ok=False)
    await h.call("memory_collaboration_events", {"scope": "project"}, role="writer", ok=False)
    await h.call("memory_collaboration_events", {"cursor": initial["next_cursor"], "max_classification": "restricted"}, role="writer", ok=False)
    await h.call("memory_collaboration_events", {}, role="other", ok=False)
    reader = await feed(h, role="read")
    assert reader["items"] == [] and not (await feed(h, reader["next_cursor"], role="read"))["items"]


async def test_reassignment_hides_old_details_and_sends_only_minimal_access_signal(harness):
    h = harness
    await configure(h)
    saved, _ = await checkpoint(h)
    published, _ = await publish(h, saved["checkpoint_id"])
    initial = await feed(h, role="admin2")
    current = await status(h, published["bundle_id"])
    selected = next(row for row in current["deliveries"] if row["recipient_user_id"] == "admin")
    await h.call("memory_continuity_ack", {"delivery_id": selected["id"], "idempotency_key": uuid4().hex})
    changed = await reassignment(h, published["bundle_id"], recipient_user_ids=["admin"],
        work_units=[{"key": "continue", "summary": "replacement-private-summary", "assignee_user_ids": ["admin"]}])
    await h.call("memory_continuity_reassign", changed)
    page = await feed(h, initial["next_cursor"], role="admin2")
    assert len(page["items"]) == 1 and page["items"][0]["topic"] == "access_changed"
    assert page["items"][0]["target_id"] is None and published["bundle_id"] not in str(page)
    assert "replacement-private-summary" not in str(page)


async def test_forget_notifies_receivers_without_preserving_erased_source_references(harness):
    h = harness
    await configure(h)
    saved, _ = await checkpoint(h)
    await publish(h, saved["checkpoint_id"])
    initial = await feed(h, role="admin2")
    await h.call("memory_checkpoint_forget", {"checkpoint_id": saved["checkpoint_id"], "idempotency_key": uuid4().hex, "reason": "erase fixture"})
    page = await feed(h, initial["next_cursor"], role="admin2")
    assert [(row["topic"], row["target_id"]) for row in page["items"]] == [("access_changed", None)]
    assert saved["checkpoint_id"] not in str(page)


async def test_head_lock_prevents_late_commit_skip_and_rollbacks_publish_nothing(harness):
    h = harness
    initial = await feed(h)
    first = await h.pool.acquire()
    second = await h.pool.acquire()
    one, two = first.transaction(), second.transaction()
    await one.start()
    await two.start()
    try:
        await events.append(first, h.project, "policy_changed", "signal", None, "public", [], revision=1, broadcast=True)
        waiting = asyncio.create_task(events.append(second, h.project, "policy_changed", "signal", None, "public", [], revision=2, broadcast=True))
        await asyncio.sleep(0.05)
        assert not waiting.done()
        assert not (await feed(h, initial["next_cursor"]))["items"]
        await one.commit()
        await waiting
        middle = await feed(h, initial["next_cursor"])
        assert [row["revision"] for row in middle["items"]] == [1]
        await two.commit()
        final = await feed(h, middle["next_cursor"])
        assert [row["revision"] for row in final["items"]] == [2]
    finally:
        if first.is_in_transaction():
            await one.rollback()
        if second.is_in_transaction():
            await two.rollback()
        await h.pool.release(first)
        await h.pool.release(second)
    async with h.pool.acquire() as conn:
        tx = conn.transaction()
        await tx.start()
        await events.append(conn, h.project, "policy_changed", "signal", None, "public", [], revision=3, broadcast=True)
        await tx.rollback()
    assert not (await feed(h, final["next_cursor"]))["items"]


async def test_retention_hard_cap_catchup_reset_and_source_audit_preserved(harness, monkeypatch):
    h = harness
    await configure(h)
    initial = await feed(h)
    monkeypatch.setattr(events, "MAX_EVENTS", 2)
    async with transaction(h.project) as conn:
        for revision in range(1, 5):
            await events.append(conn, h.project, "policy_changed", "signal", None, "public", [], revision=revision, broadcast=True)
    async with h.pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM memory_collaboration_events WHERE project_id=$1", h.project) == 2
        audit = await conn.fetchval("SELECT count(*) FROM memory_continuity_events WHERE project_id=$1", h.project)
        await conn.execute("UPDATE memory_collaboration_events SET created_at=clock_timestamp()-interval '8 days' WHERE project_id=$1", h.project)
    reset = await feed(h, initial["next_cursor"])
    assert reset["reset_required"] and reset["reset_reason"] == "retention_gap" and reset["items"] == []
    args = {"reason": "synthetic retention cleanup", "idempotency_key": uuid4().hex}
    pruned = await h.call("memory_collaboration_events_prune", args)
    assert pruned["pruned"] == 2 and not pruned["audit_erased"]
    assert (await h.call("memory_collaboration_events_prune", args))["replayed"]
    await h.call("memory_collaboration_events_prune", args, role="writer", ok=False)
    async with h.pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM memory_continuity_events WHERE project_id=$1", h.project) == audit + 1


async def test_key_rotation_requires_resync_without_cursor_authority_or_body_leak(harness):
    h = harness
    initial = await feed(h)
    async with h.pool.acquire() as conn:
        old = await conn.fetchval("SELECT secret FROM memory_event_cursor_key WHERE singleton=1")
        await conn.execute("UPDATE memory_event_cursor_key SET secret=$1 WHERE singleton=1", secrets.token_bytes(32))
    try:
        page = await feed(h, initial["next_cursor"])
        assert page["reset_required"] and page["reset_reason"] == "cursor_unusable" and page["items"] == []
    finally:
        async with h.pool.acquire() as conn:
            await conn.execute("UPDATE memory_event_cursor_key SET secret=$1 WHERE singleton=1", old)


async def test_presence_classification_raise_invalidates_old_scope_without_new_session_reference(harness):
    from tests.test_presence_postgres import enable, register, report
    h = harness
    await enable(h)
    _, auth, _ = await register(h)
    initial = await feed(h)
    await report(h, auth)
    state = await feed(h, initial["next_cursor"])
    assert [item["topic"] for item in state["items"]] == ["session_state_changed"]
    await report(h, auth, sequence=2, state_sequence=1, classification="restricted")
    changed = await feed(h, state["next_cursor"])
    assert [(row["topic"], row["target_id"]) for row in changed["items"]] == [("access_changed", None)]
    assert auth["session_id"] not in str(changed)
