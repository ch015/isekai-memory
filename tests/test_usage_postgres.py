"""Real authenticated usage ledger isolation, revisions and bounded read semantics."""
import asyncio
import json
import os
import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import asyncpg
import pytest

from isekai_memory.continuity import usage, usage_reads
from isekai_memory.continuity.usage_metrics import normalize
from tests.test_experience_postgres import harness as harness  # noqa: F401
from tests.test_usage import metric

pytestmark = pytest.mark.skipif(not os.environ.get("MEMORY_TEST_DATABASE_URL"), reason="requires disposable PostgreSQL")


async def enable(h, **overrides):
    value = await h.call("memory_usage_policy_get", {})
    args = {"policy": {**value["policy"], "enabled": True, **overrides}, "expected_version": value["policy_version"],
            "idempotency_key": uuid4().hex, "reason": "Synthetic usage validation"}
    return await h.call("memory_usage_policy_set", args), args


async def register(h, *, role="writer", **overrides):
    args = {"execution_attempt_id": str(uuid4()), "meter_epoch": str(uuid4()), "session_token": secrets.token_urlsafe(32),
            "host_kind": "codex", "host_version": "synthetic", "adapter_version": "v1", "provider": "unknown",
            "model_id": "unknown", "classification": "internal", "observation_scope": "exclusive_run",
            "parent_session_id": None, "work_binding": None, **overrides}
    value = await h.call("memory_usage_register", args, role=role)
    return value, {"session_id": value["session_id"], "session_token": args["session_token"]}, args


def request(auth, *, total=100, sequence=1, **overrides):
    return {**auth, "sequence": sequence, "metrics": metric(total), "semantics_version": 1, "completion_state": "final",
            "coverage": "complete", "source_occurred_at": None, **overrides}


async def report(h, auth, *, role="writer", **options):
    args = request(auth, **options)
    return await h.call("memory_usage_report", args, role=role), args


async def state(h, auth):
    return dict(await h.pool.fetchrow("SELECT * FROM memory_usage_sessions WHERE id=$1", auth["session_id"]))


async def summary(h, *, role="writer", **options):
    return await h.call("memory_usage_summary", options, role=role)


async def test_disabled_independent_policy_cas_receipts_and_auth(harness):
    h = harness
    assert not (await h.call("memory_usage_policy_get", {}, role="writer"))["policy"]["enabled"]
    assert not (await h.call("memory_presence_policy_get", {}))["policy"]["enabled"]
    configured, args = await enable(h)
    assert configured["version"] == 1
    assert (await h.call("memory_usage_policy_set", args))["replayed"]
    await h.call("memory_usage_policy_set", {**args, "idempotency_key": uuid4().hex}, ok=False)
    await h.call("memory_usage_policy_set", args, role="writer", ok=False)
    await h.call("memory_usage_policy_set", {**args, "policy": {**args["policy"], "timezone": "Invalid/Zone"}}, ok=False)
    _, auth, registration = await register(h)
    await enable(h, enabled=False)
    assert (await h.call("memory_usage_register", registration, role="writer"))["replayed"]
    await h.call("memory_usage_register", {**registration, "execution_attempt_id": str(uuid4())}, role="writer", ok=False)
    await h.call("memory_usage_report", request(auth), role="writer", ok=False)


async def test_registration_is_private_actor_owned_and_one_observer_per_attempt(harness):
    h = harness
    await enable(h)
    value, auth, args = await register(h)
    before = await state(h, auth)
    assert (await h.call("memory_usage_register", args, role="writer"))["session_id"] == value["session_id"]
    assert await state(h, auth) == before
    for override in ({"session_token": "z"*32}, {"meter_epoch": str(uuid4())}, {"model_id": "other"}):
        await h.call("memory_usage_register", {**args, **override}, role="writer", ok=False)
    for role in ("admin", "read", "other"):
        await h.call("memory_usage_report", request(auth), role=role, ok=False)
    await h.call("memory_usage_report", request({**auth, "session_token": "z"*32}), role="writer", ok=False)
    page = await h.call("memory_usage_list", {}, role="writer")
    serialized = json.dumps(page)
    for key in ("session_token", "register_digest", "claim_token", auth["session_token"]):
        assert key not in serialized
    assert page["items"][0]["metrics"]["total_tokens"]["omission_reason"] == "awaiting_result"
    assert (await summary(h))["summary"]["reported"]["total_tokens"]["value"] is None


async def test_absolute_revisions_replay_exact_old_receipts_and_counter_conflicts(harness):
    h = harness
    await enable(h)
    _, auth, _ = await register(h)
    first, args = await report(h, auth, total=100, completion_state="in_progress")
    second, latest = await report(h, auth, total=150, sequence=2)
    before = await state(h, auth)
    for expected, body in ((first, args), (second, latest)):
        repeats = await asyncio.gather(*[h.call("memory_usage_report", body, role="writer") for _ in range(4)])
        assert all(item == {**expected, "replayed": True} for item in repeats)
    assert await state(h, auth) == before
    assert (await summary(h))["summary"]["reported"]["total_tokens"]["value"] == 150
    await h.call("memory_usage_report", {**latest, "metrics": metric(160)}, role="writer", ok=False)
    await h.call("memory_usage_report", request(auth, total=140, sequence=3), role="writer", ok=False)
    await h.call("memory_usage_report", request(auth, total=160, sequence=3, completion_state="in_progress"), role="writer", ok=False)
    await report(h, auth, total=160, sequence=3)
    assert (await summary(h))["summary"]["reported"]["total_tokens"]["value"] == 160
    assert await h.pool.fetchval("SELECT count(*) FROM memory_usage_receipts WHERE session_id=$1", auth["session_id"]) == 3


async def test_estimate_replacement_unknown_zero_and_complete_validation(harness):
    h = harness
    await enable(h)
    _, auth, _ = await register(h)
    await report(h, auth, metrics=metric(180, "estimated"), completion_state="in_progress")
    value = (await summary(h))["summary"]
    assert value["reported"]["total_tokens"]["value"] is None
    assert value["estimated"]["total_tokens"]["value"] == 180
    await report(h, auth, total=120, sequence=2)
    value = (await summary(h))["summary"]
    assert value["reported"]["total_tokens"]["value"] == 120 and value["estimated"]["total_tokens"]["value"] is None
    await h.call("memory_usage_report", request(auth, sequence=3, metrics=metric(200, "estimated")), role="writer", ok=False)
    _, unknown, _ = await register(h)
    await h.call("memory_usage_report", request(unknown, metrics=normalize({}).as_dict()), role="writer", ok=False)
    await report(h, unknown, total=0)
    value = (await summary(h))["summary"]["reported"]["total_tokens"]
    assert value["value"] == 120 and value["known_units"] == 2


async def test_full_set_scope_classification_filters_groups_and_paging(harness):
    h = harness
    await enable(h)
    for role, total, options in (("writer", 100, {}), ("writer", 50, {"host_kind": "claude", "model_id": "fixture-model"}),
                                 ("admin", 70, {}), ("writer", 1000, {"classification": "restricted"})):
        _, auth, _ = await register(h, role=role, **options)
        await report(h, auth, role=role, total=total)
    own = await summary(h, group_by="host")
    assert own["summary"]["reported"]["total_tokens"]["value"] == 150 and len(own["groups"]) == 2
    assert (await summary(h, role="admin", scope="project", group_by="user"))["summary"]["reported"]["total_tokens"]["value"] == 220
    assert (await summary(h, max_classification="restricted"))["summary"]["reported"]["total_tokens"]["value"] == 1150
    assert (await summary(h, model_id="fixture-model"))["summary"]["reported"]["total_tokens"]["value"] == 50
    assert (await summary(h, role="read"))["summary"]["reported"]["total_tokens"]["value"] is None
    await h.call("memory_usage_summary", {"scope": "project"}, role="writer", ok=False)
    await h.call("memory_usage_summary", {"user_id": "admin"}, role="writer", ok=False)
    first = await h.call("memory_usage_list", {"limit": 1}, role="writer")
    second = await h.call("memory_usage_list", {"limit": 1, "cursor": first["next_cursor"]}, role="writer")
    assert first["has_more"] and not second["has_more"] and first["items"][0]["id"] != second["items"][0]["id"]
    for changes in ({"scope": "project"}, {"model_id": "fixture-model"}, {"timezone": "Asia/Seoul"}):
        await h.call("memory_usage_list", {"cursor": first["next_cursor"], **changes}, role="writer", ok=False)


async def test_period_half_open_final_move_fallback_and_stable_retry_bucket(harness):
    h = harness
    await enable(h)
    _, auth, _ = await register(h)
    await report(h, auth, completion_state="in_progress")
    old = (await state(h, auth))["bucket_at"]
    end = old-timedelta(days=1)
    final, args = await report(h, auth, sequence=2, source_occurred_at=end.isoformat())
    assert datetime.fromisoformat(final["bucket_at"]) == end
    window = {"period": "custom", "start_at": end.isoformat(), "end_at": (end+timedelta(seconds=1)).isoformat()}
    assert (await summary(h, **window))["summary"]["reported"]["total_tokens"]["value"] == 100
    before = {"period": "custom", "start_at": (end-timedelta(seconds=1)).isoformat(), "end_at": end.isoformat()}
    assert (await summary(h, **before))["summary"]["observed_units"] == 0
    assert (await summary(h))["summary"]["observed_units"] == 0
    assert (await h.call("memory_usage_report", args, role="writer"))["bucket_at"] == final["bucket_at"]
    await h.call("memory_usage_report", request(auth, sequence=3, source_occurred_at=old.isoformat()), role="writer", ok=False)
    _, fallback, _ = await register(h)
    await report(h, fallback, source_occurred_at="2000-01-01T00:00:00Z")
    assert (await state(h, fallback))["bucket_basis"] == "server_first_received"


async def test_readonly_stable_soft_alerts_and_filtered_alert_suppression(harness):
    h = harness
    await enable(h, project_alert_tokens=50, user_alert_tokens=80)
    _, auth, _ = await register(h)
    await report(h, auth)
    first = await summary(h, role="admin", scope="project")
    second = await summary(h, role="admin", scope="project")
    assert len(first["alerts"]) == 2 and first["alerts"] == second["alerts"]
    assert all(item["action"] == "inform_only" for item in first["alerts"])
    assert len((await summary(h))["alerts"]) == 1
    assert not (await summary(h, host_kind="codex"))["alerts"]
    assert not (await summary(h, period="week"))["alerts"]


async def test_bounded_registration_revisions_reports_aggregation_and_replay(harness, monkeypatch):
    h = harness
    await enable(h)
    _, auth, args = await register(h)
    monkeypatch.setattr(usage, "MAX_REGISTER_MINUTE", 1)
    await h.call("memory_usage_register", {**args, "execution_attempt_id": str(uuid4())}, role="writer", ok=False)
    assert (await h.call("memory_usage_register", args, role="writer"))["replayed"]
    monkeypatch.setattr(usage, "MAX_REVISIONS", 1)
    first, body = await report(h, auth)
    await h.call("memory_usage_report", request(auth, sequence=2), role="writer", ok=False)
    assert (await h.call("memory_usage_report", body, role="writer")) == {**first, "replayed": True}
    monkeypatch.setattr(usage_reads, "MAX_AGGREGATE_UNITS", 0)
    await h.call("memory_usage_summary", {}, role="writer", ok=False)


async def test_parent_actor_binding_classification_and_no_automatic_rollup(harness):
    h = harness
    await enable(h)
    _, parent, _ = await register(h, classification="restricted")
    _, child, args = await register(h, parent_session_id=parent["session_id"], classification="public")
    assert (await state(h, child))["classification"] == "restricted"
    await h.call("memory_usage_register", {**args, "execution_attempt_id": str(uuid4())}, role="admin", ok=False)
    await report(h, parent, total=10)
    await report(h, child, total=30)
    assert (await summary(h))["summary"]["observed_units"] == 0
    assert (await summary(h, max_classification="restricted"))["summary"]["reported"]["total_tokens"]["value"] == 40


async def test_retention_tombstones_receipts_and_downgrade_guards(harness):
    h = harness
    await enable(h, retention_days=1)
    _, auth, registration = await register(h)
    reported, report_args = await report(h, auth, source_occurred_at=(datetime.now(UTC)-timedelta(days=2)).isoformat())
    assert (await summary(h, period="week"))["summary"]["observed_units"] == 0
    args = {"idempotency_key": uuid4().hex, "reason": "Synthetic expiry", "limit": 1}
    retired = await h.call("memory_usage_prune", args)
    assert retired["retired"] == 1 and (await h.call("memory_usage_prune", args))["replayed"]
    stored = await state(h, auth)
    assert stored["retired_at"] and stored["metrics"] is None and stored["model_id"] == "unknown"
    await h.call("memory_usage_register", registration, role="writer", ok=False)
    await h.call("memory_usage_report", report_args, role="writer", ok=False)
    with pytest.raises(asyncpg.RaiseError):
        await h.pool.execute("DELETE FROM memory_usage_sessions WHERE id=$1", auth["session_id"])
    with pytest.raises(asyncpg.RaiseError):
        await h.pool.execute("UPDATE memory_usage_receipts SET sequence=2 WHERE session_id=$1", auth["session_id"])
    assert reported["sequence"] == 1


async def test_work_requires_exact_active_private_claim_and_late_usage_stays_with_old_actor(harness):
    from tests.test_continuity_postgres import checkpoint, configure, publish, take

    h = harness
    await enable(h)
    await configure(h, allow_emergency_takeover=True)
    saved, _ = await checkpoint(h, classification="restricted")
    published, _ = await publish(h, saved["checkpoint_id"])
    current = await h.call("memory_continuity_status", {"bundle_id": published["bundle_id"], "max_classification": "restricted"})
    unit = current["units"][0]
    claim, _ = await take(h, unit["id"])
    binding = {"work_unit_id": unit["id"], "claim_token": claim["claim_token"], "claim_generation": claim["claim_generation"]}
    _, auth, args = await register(h, role="admin", classification="public", work_binding=binding)
    assert (await state(h, auth))["classification"] == "restricted"
    before = dict(await h.pool.fetchrow("SELECT * FROM memory_continuity_units WHERE id=$1", unit["id"]))
    await report(h, auth, role="admin", total=10)
    assert dict(await h.pool.fetchrow("SELECT * FROM memory_continuity_units WHERE id=$1", unit["id"])) == before
    for change in ({"claim_token": "z"*32}, {"claim_generation": 2}, {"work_unit_id": str(uuid4())}):
        await h.call("memory_usage_register", {**args, "execution_attempt_id": str(uuid4()),
                     "work_binding": {**binding, **change}}, role="admin", ok=False)
    await h.call("memory_continuity_reassign", {
        "bundle_id": published["bundle_id"], "expected_version": 1,
        "expected_generations": {unit["unit_key"]: claim["claim_generation"]},
        "recipient_user_ids": ["admin2"],
        "work_units": [{"key": unit["unit_key"], "summary": unit["summary"], "assignee_user_ids": ["admin2"]}],
        "emergency_takeover": True, "takeover_unit_keys": [unit["unit_key"]],
        "confirm_running_work_may_continue": True, "reason": "Synthetic takeover", "idempotency_key": uuid4().hex})
    await report(h, auth, role="admin", total=20, sequence=2)
    await h.call("memory_usage_report", request(auth, total=30, sequence=3), role="admin2", ok=False)
    assert (await summary(h, role="admin", max_classification="restricted"))["summary"]["reported"]["total_tokens"]["value"] == 20
    assert (await summary(h, role="admin2", max_classification="restricted"))["summary"]["observed_units"] == 0
    await h.call("memory_checkpoint_forget", {"checkpoint_id": saved["checkpoint_id"], "reason": "Synthetic source erasure",
                                           "idempotency_key": uuid4().hex})
    page = await h.call("memory_usage_list", {"max_classification": "restricted"}, role="admin")
    assert page["items"][0]["work_unit_id"] is None
    assert page["items"][0]["metrics"]["total_tokens"]["value"] == 20


async def test_report_rate_limit_keeps_existing_receipt_replay_and_does_not_commit_partial(harness, monkeypatch):
    h = harness
    await enable(h)
    _, auth, _ = await register(h)
    first, args = await report(h, auth)
    monkeypatch.setattr(usage, "MAX_REPORT_MINUTE", 0)
    await h.call("memory_usage_report", request(auth, sequence=2, total=200), role="writer", ok=False)
    assert (await h.call("memory_usage_report", args, role="writer")) == {**first, "replayed": True}
    assert (await state(h, auth))["sequence"] == 1
