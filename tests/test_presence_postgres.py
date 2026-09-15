"""Real project/user/session isolation, read-only views and anti-replay checks."""

import asyncio
import json
import os
import secrets
from uuid import uuid4

import asyncpg
import pytest

from isekai_memory.continuity import presence, presence_reads
from tests.test_collaboration_overview_postgres import snapshot
from tests.test_continuity_postgres import checkpoint, configure, publish, status
from tests.test_experience_postgres import harness as harness  # noqa: F401

pytestmark = pytest.mark.skipif(not os.environ.get("MEMORY_TEST_DATABASE_URL"), reason="requires disposable PostgreSQL")


async def enable(h, **overrides):
    before = await h.call("memory_presence_policy_get", {})
    args = {"expected_version": before["policy_version"], "policy": {**before["policy"], "enabled": True, **overrides},
            "idempotency_key": uuid4().hex, "reason": "synthetic observation"}
    return await h.call("memory_presence_policy_set", args), args


async def register(h, *, role="writer", **overrides):
    args = {"client_instance_id": str(uuid4()), "session_token": secrets.token_urlsafe(32), "host_kind": "codex",
            "session_kind": "controller", "classification": "internal", **overrides}
    result = await h.call("memory_presence_register", args, role=role)
    return result, {"session_id": result["session_id"], "session_token": args["session_token"]}, args


def report_args(auth, *, state="idle", sequence=1, state_sequence=1, **overrides):
    return {**auth, "sequence": sequence, "state_sequence": state_sequence, "reported_state": state,
            "observation_scope": "controller", "state_observation_available": state != "unknown",
            "active_work_count": int(state == "running"), "policy_version": 1,
            "classification": "internal", "work_unit_id": None, "checkpoint_id": None, **overrides}


async def report(h, auth, *, role="writer", **options):
    args = report_args(auth, **options)
    return await h.call("memory_presence_heartbeat", args, role=role), args


async def row(h, session_id):
    return dict(await h.pool.fetchrow("SELECT * FROM memory_presence_sessions WHERE id=$1", session_id))


async def age(h, auth, *, idle=600, seen=3):
    await h.pool.execute("""
        UPDATE memory_presence_sessions SET state_since_at=clock_timestamp()-$2::integer*interval '1 second',
            idle_since_at=clock_timestamp()-$2::integer*interval '1 second',
            last_seen_at=clock_timestamp()-$3::integer*interval '1 second' WHERE id=$1
    """, auth["session_id"], idle, seen)


async def test_disabled_default_policy_and_admin_versioned_configuration(harness):
    h = harness
    assert (await h.call("memory_presence_policy_get", {}, role="read"))["policy"]["enabled"] is False
    args = {"client_instance_id": str(uuid4()), "session_token": "a"*32, "host_kind": "codex",
            "session_kind": "worker", "classification": "internal"}
    await h.call("memory_presence_register", args, role="writer", ok=False)
    configured, request = await enable(h)
    assert configured["version"] == 1
    assert (await h.call("memory_presence_policy_set", request))["replayed"]
    await h.call("memory_presence_policy_set", request, role="writer", ok=False)
    await h.call("memory_presence_policy_set", {**request, "idempotency_key": uuid4().hex}, ok=False)
    await h.call("memory_presence_policy_set", {**request, "expected_version": 1, "idempotency_key": uuid4().hex,
                 "policy": {**request["policy"], "heartbeat_seconds": 60, "stale_after_seconds": 60}}, ok=False)


async def test_registration_retries_do_not_refresh_and_never_return_private_tokens(harness):
    h = harness
    await enable(h)
    registered, auth, args = await register(h)
    before = await row(h, auth["session_id"])
    replay = await h.call("memory_presence_register", args, role="writer")
    assert replay["replayed"] and replay["session_id"] == registered["session_id"]
    assert await row(h, auth["session_id"]) == before
    await h.call("memory_presence_register", {**args, "session_token": "z"*32}, role="writer", ok=False)
    page = await h.call("memory_presence_list", {}, role="writer")
    assert len(page["items"]) == 1 and page["items"][0]["effective_state"] == "unknown"
    for forbidden in ("session_token", "register_digest", "report_digest", "client_instance_id"):
        assert forbidden not in json.dumps(page)
    assert auth["session_token"] not in json.dumps(registered)


async def test_sequence_duplicates_conflicts_ordering_and_cross_actor_token(harness):
    h = harness
    await enable(h)
    _, auth, _ = await register(h)
    _, args = await report(h, auth)
    before = await row(h, auth["session_id"])
    results = await asyncio.gather(*[h.call("memory_presence_heartbeat", args, role="writer") for _ in range(4)])
    assert all(result["replayed"] for result in results)
    assert await row(h, auth["session_id"]) == before
    await h.call("memory_presence_heartbeat", {**args, "reported_state": "blocked"}, role="writer", ok=False)
    await report(h, auth, sequence=2)
    await h.call("memory_presence_heartbeat", args, role="writer", ok=False)
    for role in ("admin", "read", "other"):
        await h.call("memory_presence_heartbeat", report_args(auth, sequence=3), role=role, ok=False)
    await h.call("memory_presence_heartbeat", report_args({**auth, "session_token": "z"*32}, sequence=3), role="writer", ok=False)


async def test_idle_heartbeat_autosave_policy_change_and_reconnect(harness):
    h = harness
    await enable(h)
    _, auth, _ = await register(h)
    await report(h, auth)
    await age(h, auth, idle=600)
    before = await row(h, auth["session_id"])
    await report(h, auth, sequence=2)
    assert (await row(h, auth["session_id"]))["idle_since_at"] == before["idle_since_at"]
    users = await h.call("memory_presence_users", {}, role="writer")
    assert users["items"][0]["is_idle"] and users["items"][0]["idle_seconds"] >= 600
    await enable(h, idle_after_seconds=1200)
    assert (await h.call("memory_presence_users", {}, role="writer"))["items"][0]["effective_state"] == "waiting"
    await age(h, auth, idle=600, seen=65)
    assert (await h.call("memory_presence_users", {}, role="writer"))["items"][0]["effective_state"] == "partially_unknown"
    await report(h, auth, sequence=3, policy_version=2)
    result = (await h.call("memory_presence_list", {}, role="writer"))["items"][0]
    assert result["idle_seconds"] < 5 and result["effective_state"] == "waiting"


async def test_mutation_state_sequence_and_observation_scope(harness):
    h = harness
    await enable(h)
    _, auth, _ = await register(h)
    await report(h, auth)
    await h.call("memory_presence_heartbeat", report_args(auth, sequence=2, state_sequence=2), role="writer", ok=False)
    await h.call("memory_presence_heartbeat", report_args(auth, state="running", sequence=2), role="writer", ok=False)
    await report(h, auth, state="running", sequence=2, state_sequence=2)
    for options in ({"state": "idle", "active_work_count": 1}, {"state": "running", "active_work_count": 0},
                    {"state": "idle", "observation_scope": "worker"}, {"state": "idle", "state_observation_available": False}):
        await h.call("memory_presence_heartbeat", report_args(auth, sequence=3, state_sequence=3, **options), role="writer", ok=False)


async def test_user_aggregation_is_not_session_page_and_retains_mixed_uncertainty(harness):
    h = harness
    await enable(h)
    _, first, _ = await register(h)
    _, second, _ = await register(h, host_kind="claude")
    for auth, duration in ((first, 720), (second, 480)):
        await report(h, auth)
        await age(h, auth, idle=duration)
    assert len((await h.call("memory_presence_list", {"limit": 1}, role="writer"))["items"]) == 1
    aggregate = (await h.call("memory_presence_users", {"limit": 1}, role="writer"))["items"][0]
    assert aggregate["is_idle"] and aggregate["open_sessions"] == 2 and 480 <= aggregate["idle_seconds"] < 485
    await report(h, first, state="running", sequence=2, state_sequence=2)
    await age(h, second, seen=70)
    aggregate = (await h.call("memory_presence_users", {}, role="writer"))["items"][0]
    assert aggregate["effective_state"] == "running" and aggregate["has_uncertainty"]


async def test_end_does_not_renew_or_reanimate_and_disabled_policy_still_allows_end(harness):
    h = harness
    await enable(h)
    _, auth, registration = await register(h)
    await report(h, auth)
    await enable(h, enabled=False)
    ended = await h.call("memory_presence_end", {**auth, "sequence": 2}, role="writer")
    assert ended["ended_at"] is not None
    assert (await h.call("memory_presence_end", {**auth, "sequence": 2}, role="writer"))["replayed"]
    assert (await h.call("memory_presence_register", registration, role="writer"))["ended_at"] is not None
    await h.call("memory_presence_heartbeat", report_args(auth, sequence=3), role="writer", ok=False)
    assert (await h.call("memory_presence_list", {}, role="writer"))["items"] == []
    assert (await h.call("memory_presence_users", {}, role="writer"))["items"][0]["effective_state"] == "ended"
    with pytest.raises(asyncpg.RaiseError):
        await h.pool.execute("UPDATE memory_presence_sessions SET sequence=sequence+1 WHERE id=$1", auth["session_id"])


async def test_scope_classification_parent_binding_and_no_read_mutations(harness):
    h = harness
    await enable(h)
    _, parent, _ = await register(h, classification="restricted")
    await register(h, parent_session_id=parent["session_id"], classification="public")
    await register(h, role="admin")
    for view in ("list", "users"):
        assert len((await h.call("memory_presence_" + view, {}, role="read"))["items"]) == (1 if view == "users" else 0)
        await h.call("memory_presence_" + view, {"scope": "project"}, role="writer", ok=False)
        await h.call("memory_presence_" + view, {"scope": "project"}, role="other", ok=False)
    assert (await h.call("memory_presence_list", {}, role="writer"))["items"] == []
    args = {"scope": "project", "max_classification": "restricted"}
    before = await snapshot(h)
    assert len((await h.call("memory_presence_list", args))["items"]) == 3
    assert len((await h.call("memory_presence_users", args))["items"]) == 2
    assert await snapshot(h) == before
    await h.call("memory_presence_register", {"client_instance_id": str(uuid4()), "session_token": "z"*32,
                 "host_kind": "kiro", "session_kind": "worker", "classification": "internal", "parent_session_id": parent["session_id"]}, ok=False)


async def test_checkpoint_binding_and_monotonic_classification(harness):
    h = harness
    await enable(h)
    await configure(h)
    saved, _ = await checkpoint(h, classification="restricted")
    _, auth, _ = await register(h, classification="public")
    await report(h, auth, checkpoint_id=saved["checkpoint_id"])
    assert (await row(h, auth["session_id"]))["classification"] == "restricted"
    await report(h, auth, sequence=2, classification="public")
    assert (await row(h, auth["session_id"]))["classification"] == "restricted"
    assert (await h.call("memory_presence_list", {}, role="writer"))["items"] == []
    _, other, _ = await register(h, role="admin")
    await h.call("memory_presence_heartbeat", report_args(other, checkpoint_id=saved["checkpoint_id"]), ok=False)
    await h.call("memory_presence_heartbeat", report_args(auth, sequence=3, work_unit_id=str(uuid4()), state_sequence=2), role="writer", ok=False)


async def test_work_binding_is_not_a_claim_and_uuid_case_is_not_activity(harness):
    h = harness
    await enable(h)
    await configure(h)
    saved, _ = await checkpoint(h)
    published, _ = await publish(h, saved["checkpoint_id"])
    original = await status(h, published["bundle_id"])
    unit = original["units"][0]["id"]
    _, auth, _ = await register(h, role="admin")
    await report(h, auth, role="admin", state="running", work_unit_id=unit)
    before = await row(h, auth["session_id"])
    await report(h, auth, role="admin", state="running", sequence=2, work_unit_id=unit.upper())
    after = await row(h, auth["session_id"])
    assert after["state_sequence"] == before["state_sequence"] == 1
    assert after["state_since_at"] == before["state_since_at"]
    latest = await status(h, published["bundle_id"])
    assert {k: v for k, v in latest.items() if k != "observed_at"} == {
        k: v for k, v in original.items() if k != "observed_at"}
    _, sender, _ = await register(h)
    await h.call("memory_presence_heartbeat", report_args(sender, state="running", work_unit_id=unit), role="writer", ok=False)


async def test_page_bindings_and_aggregate_budget(harness, monkeypatch):
    h = harness
    await enable(h)
    for _ in range(3):
        _, auth, _ = await register(h)
        await report(h, auth)
        await age(h, auth)
    page = await h.call("memory_presence_list", {"limit": 1}, role="writer")
    cursor = page["next_cursor"]
    second = await h.call("memory_presence_list", {"limit": 1, "cursor": cursor}, role="writer")
    assert page["items"][0]["id"] != second["items"][0]["id"]
    for options, role in (({"host_kind": "claude"}, "writer"), ({"scope": "project"}, "admin"), ({}, "read")):
        await h.call("memory_presence_list", {"cursor": cursor, **options}, role=role, ok=False)
    await h.call("memory_presence_users", {"cursor": cursor}, role="writer", ok=False)
    monkeypatch.setattr(presence_reads, "AGGREGATE_LIMIT", 2)
    aggregate = (await h.call("memory_presence_users", {}, role="writer"))["items"][0]
    assert aggregate["effective_state"] == "partially_unknown" and aggregate["coverage"] == "partial"


async def test_registration_limits_and_explicit_retirement_tombstone(harness, monkeypatch):
    h = harness
    await enable(h, retention_hours=1)
    _, auth, registration = await register(h)
    monkeypatch.setattr(presence, "MAX_OPEN_PER_USER", 1)
    await h.call("memory_presence_register", {**registration, "client_instance_id": str(uuid4())}, role="writer", ok=False)
    await age(h, auth, idle=7200, seen=7200)
    args = {"idempotency_key": uuid4().hex, "reason": "test retention", "limit": 1}
    await h.call("memory_presence_prune", args, role="writer", ok=False)
    assert (await h.call("memory_presence_prune", args))["retired"] == 1
    assert (await h.call("memory_presence_prune", args))["replayed"]
    retired = await row(h, auth["session_id"])
    assert retired["retired_at"] is not None and retired["host_kind"] == "unknown" and retired["work_unit_id"] is None
    await h.call("memory_presence_register", registration, role="writer", ok=False)
    await h.call("memory_presence_heartbeat", report_args(auth), role="writer", ok=False)
    assert (await h.call("memory_presence_users", {}, role="writer"))["items"][0]["effective_state"] == "not_observed"
    await register(h)
