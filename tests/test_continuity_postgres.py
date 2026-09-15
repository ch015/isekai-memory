"""Real multi-user continuity tests with synthetic project-scoped tokens."""

import asyncio
import os
import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from isekai_memory.continuity.common import digest
from isekai_memory.server.auth import hash_token
from isekai_memory.store import queries
from tests.test_continuity import captured, policy_body
from tests.test_experience_postgres import harness as harness  # noqa: F401

pytestmark = pytest.mark.skipif(not os.environ.get("MEMORY_TEST_DATABASE_URL"), reason="requires disposable PostgreSQL")


async def configure(h, **overrides):
    args = {"policy": policy_body(**overrides), "expected_version": 0, "idempotency_key": uuid4().hex, "reason": "project continuity setup"}
    return await h.call("memory_continuity_policy_set", args), args


async def checkpoint(h, **overrides):
    package, snapshot = captured()
    args = {"work_id": "work-" + uuid4().hex, "expected_version": 0, "continuation": package, "snapshot": snapshot,
            "classification": "internal", "lock_snapshot_digest": "sha256:" + "a" * 64, "idempotency_key": uuid4().hex, **overrides}
    return await h.call("memory_checkpoint_save", args, role="writer"), args


async def publish(h, source_id, **overrides):
    args = {"source_kind": "checkpoint", "source_id": source_id, "expected_policy_version": 1,
            "idempotency_key": uuid4().hex, "reason": "recover work", **overrides}
    return await h.call("memory_continuity_publish", args), args


async def status(h, bundle_id, **kwargs):
    return await h.call("memory_continuity_status", {"bundle_id": bundle_id}, **kwargs)


async def take(h, unit_id, *, role="admin"):
    args = {"unit_id": unit_id, "claim_token": secrets.token_urlsafe(32)}
    result = await h.call("memory_continuity_claim", args, role=role)
    return {**args, "claim_generation": result["claim_generation"]}, result


async def reassignment(h, bundle_id, **overrides):
    current = await status(h, bundle_id)
    args = {"bundle_id": bundle_id, "expected_version": current["bundle"]["version"],
            "expected_generations": {unit["unit_key"]: unit["claim_generation"] for unit in current["units"]},
            "recipient_user_ids": ["admin", "admin2"],
            "work_units": [{"key": u["unit_key"], "summary": u["summary"], "assignee_user_ids": u["assignee_user_ids"]} for u in current["units"]],
            "idempotency_key": uuid4().hex, "reason": "recipient unavailable", **overrides}
    return args


async def test_policy_admin_scope_overrides_receipts_and_members(harness):
    h = harness
    assert (await h.call("memory_continuity_policy_get", {}))["configured"] is False
    configured, args = await configure(h)
    assert configured["version"] == 1
    assert (await h.call("memory_continuity_policy_set", args))["replayed"]
    await h.call("memory_continuity_policy_set", args, role="writer", ok=False)
    await h.call("memory_continuity_policy_set", {**args, "reason": "conflicting retry"}, ok=False)
    await h.call("memory_continuity_policy_set", {**args, "idempotency_key": uuid4().hex}, role="admin2", ok=False)
    await h.call("memory_continuity_policy_get", {}, role="other", ok=False)
    people = await h.call("memory_continuity_members", {})
    assert {row["user_id"] for row in people["items"]} == {"admin", "admin2", "writer"}
    assert all(set(row) == {"user_id"} for row in people["items"])
    history = await h.call("memory_continuity_history", {})
    assert history["items"][0]["details"]["policy"] == args["policy"]


@pytest.mark.parametrize("users", [["read"], ["missing"], ["other"]])
async def test_unavailable_policy_recipients_are_rejected(harness, users):
    h = harness
    await h.call("memory_continuity_policy_set", {"policy": policy_body(default_recipient_user_ids=users),
                 "expected_version": 0, "reason": "test", "idempotency_key": uuid4().hex}, ok=False)
    assert (await h.call("memory_continuity_policy_get", {}))["version"] == 0


async def test_checkpoint_cas_snapshot_provenance_and_scope(harness):
    h = harness
    await configure(h)
    saved, args = await checkpoint(h)
    assert (await h.call("memory_checkpoint_save", args, role="writer"))["replayed"]
    await h.call("memory_checkpoint_save", {**args, "idempotency_key": uuid4().hex}, role="writer", ok=False)
    body = await h.call("memory_checkpoint_read", {"checkpoint_id": saved["checkpoint_id"]})
    assert body["source"]["from_user"] == "writer"
    assert digest(body["source"]) == saved["payload_digest"] == body["payload_digest"]
    assert body["snapshot"] == args["snapshot"]
    await h.call("memory_checkpoint_read", {"checkpoint_id": saved["checkpoint_id"]}, role="read", ok=False)
    await h.call("memory_checkpoint_read", {"checkpoint_id": saved["checkpoint_id"]}, role="other", ok=False)
    listed = await h.call("memory_checkpoint_list", {}, role="writer")
    assert len(listed["items"]) == 1 and "snapshot" not in listed["items"][0]
    await h.call("memory_checkpoint_list", {"from_user_id": "admin"}, role="writer", ok=False)


async def test_fanout_independent_delivery_context_ack_and_one_unit_owner(harness):
    h = harness
    await configure(h)
    saved, _ = await checkpoint(h)
    published, args = await publish(h, saved["checkpoint_id"])
    bundle_id = published["bundle_id"]
    assert (await h.call("memory_continuity_publish", args))["replayed"]
    current = await status(h, bundle_id, role="writer")
    assert current["intake"] == {"total": 2, "acknowledged": 0}
    assert len(current["units"]) == 1
    deliveries = {d["recipient_user_id"]: str(d["id"]) for d in current["deliveries"]}
    for role in ("admin", "admin2"):
        inbox = await h.call("memory_continuity_inbox", {}, role=role)
        assert len(inbox["items"]) == 1
        read = await h.call("memory_continuity_read", {"delivery_id": deliveries[role]}, role=role)
        assert digest(read["source"]) == read["source_digest"] == saved["payload_digest"]
    await h.call("memory_continuity_read", {"delivery_id": deliveries["admin2"]}, ok=False)
    await h.call("memory_continuity_ack", {"delivery_id": deliveries["admin"], "idempotency_key": "ack-one"})
    assert (await h.call("memory_continuity_inbox", {}))["items"] == []
    assert len((await h.call("memory_continuity_inbox", {}, role="admin2"))["items"]) == 1
    assert (await status(h, bundle_id))["intake"] == {"total": 2, "acknowledged": 1}
    unit_id = current["units"][0]["id"]
    owner, claimed = await take(h, unit_id)
    await h.call("memory_continuity_claim", {"unit_id": unit_id, "claim_token": secrets.token_urlsafe(32)}, role="admin2", ok=False)
    assert (await h.call("memory_continuity_claim", {k: v for k, v in owner.items() if k != "claim_generation"}))["replayed"]
    assert claimed["automatic_resume"] is False


async def test_three_successors_can_own_distinct_units(harness):
    h = harness
    h.tokens["third"] = secrets.token_urlsafe(32)
    await queries.create_token(token_hash=hash_token(h.tokens["third"]), project_id=h.project, user_id="third", scopes=["read", "write"], expires_at=None)
    users = ["admin", "admin2", "third"]
    await configure(h, default_recipient_user_ids=users)
    saved, _ = await checkpoint(h)
    units = [{"key": "work-" + role, "summary": "Owned by " + role, "assignee_user_ids": [role]} for role in users]
    published, _ = await publish(h, saved["checkpoint_id"], work_units=units)
    current = await status(h, published["bundle_id"])
    results = await asyncio.gather(*[take(h, u["id"], role=u["assignee_user_ids"][0]) for u in current["units"]])
    assert len(results) == 3 and all(row[1]["claim_generation"] == 1 for row in results)
    assert (await status(h, published["bundle_id"]))["intake"] == {"total": 3, "acknowledged": 0}


async def test_admin_reassign_fences_removed_owner_and_preserves_other_ack(harness):
    h = harness
    await configure(h)
    saved, _ = await checkpoint(h)
    published, _ = await publish(h, saved["checkpoint_id"])
    bid = published["bundle_id"]
    current = await status(h, bid)
    old_delivery = next(d["id"] for d in current["deliveries"] if d["recipient_user_id"] == "admin")
    stable_delivery = next(d["id"] for d in current["deliveries"] if d["recipient_user_id"] == "admin2")
    await h.call("memory_continuity_ack", {"delivery_id": stable_delivery, "idempotency_key": "received"}, role="admin2")
    claim, _ = await take(h, current["units"][0]["id"])
    args = await reassignment(h, bid, recipient_user_ids=["admin2"], work_units=[{
        "key": "continue", "summary": current["units"][0]["summary"], "assignee_user_ids": ["admin2"]}])
    await h.call("memory_continuity_reassign", args, ok=False)
    async with h.pool.acquire() as conn:
        await conn.execute("UPDATE memory_continuity_units SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE id=$1::uuid", claim["unit_id"])
    moved = await h.call("memory_continuity_reassign", args)
    assert moved["version"] == 2
    assert (await h.call("memory_continuity_reassign", args))["replayed"]
    await h.call("memory_continuity_read", {"delivery_id": old_delivery}, ok=False)
    await h.call("memory_continuity_renew", {**claim, "lease_expires_at": (datetime.now(UTC) + timedelta(seconds=60)).isoformat()}, ok=False)
    await h.call("memory_continuity_release", {**claim, "action": "complete", "reason": "stale", "idempotency_key": "stale"}, ok=False)
    new_claim, _ = await take(h, claim["unit_id"], role="admin2")
    assert new_claim["claim_generation"] > claim["claim_generation"]
    after = await status(h, bid)
    kept = next(d for d in after["deliveries"] if d["id"] == stable_delivery)
    assert kept["acknowledged_at"] is not None and kept["routing_version"] == 1
    assert after["bundle"]["source_digest"] == saved["payload_digest"]


async def test_emergency_requires_policy_confirmation_and_only_fences_named_units(harness):
    h = harness
    await configure(h, allow_emergency_takeover=True)
    saved, _ = await checkpoint(h)
    units = [{"key": role, "summary": role, "assignee_user_ids": [role]} for role in ("admin", "admin2")]
    published, _ = await publish(h, saved["checkpoint_id"], work_units=units)
    current = await status(h, published["bundle_id"])
    claims = {u["unit_key"]: (await take(h, u["id"], role=u["unit_key"]))[0] for u in current["units"]}
    args = await reassignment(h, published["bundle_id"], emergency_takeover=True, takeover_unit_keys=["admin"])
    await h.call("memory_continuity_reassign", args, ok=False)
    args["confirm_running_work_may_continue"] = True
    assert (await h.call("memory_continuity_reassign", args))["running_processes_stopped"] is False
    after = await status(h, published["bundle_id"])
    assert next(u for u in after["units"] if u["unit_key"] == "admin")["state"] == "available"
    assert next(u for u in after["units"] if u["unit_key"] == "admin2")["claim_generation"] == claims["admin2"]["claim_generation"]


async def test_checkpoint_erasure_revokes_delivery_and_leases_but_preserves_hash(harness):
    h = harness
    await configure(h)
    saved, args = await checkpoint(h)
    published, _ = await publish(h, saved["checkpoint_id"])
    current = await status(h, published["bundle_id"])
    claim, _ = await take(h, current["units"][0]["id"])
    erase = {"checkpoint_id": saved["checkpoint_id"], "reason": "retention cleanup", "idempotency_key": "erase"}
    await h.call("memory_checkpoint_forget", erase, role="writer", ok=False)
    await h.call("memory_checkpoint_forget", erase)
    assert (await h.call("memory_checkpoint_forget", erase))["replayed"]
    await h.call("memory_checkpoint_read", {"checkpoint_id": saved["checkpoint_id"]}, ok=False)
    await h.call("memory_continuity_release", {**claim, "action": "complete", "reason": "stale", "idempotency_key": "stale"}, ok=False)
    assert (await h.call("memory_continuity_inbox", {}))["items"] == []
    async with h.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM memory_checkpoints WHERE id=$1::uuid", saved["checkpoint_id"])
        assert row["continuation"] == {} and row["snapshot"] is None and row["payload_digest"] == saved["payload_digest"]
    # A historical save receipt cannot resurrect erased bytes.
    assert (await h.call("memory_checkpoint_save", args, role="writer"))["replayed"]


async def test_promoting_legacy_handoff_blocks_old_intake_without_rewriting_payload(harness):
    h = harness
    await configure(h)
    legacy = await h.source()
    async with h.pool.acquire() as conn:
        before = dict(await conn.fetchrow("SELECT * FROM handoffs WHERE id=$1::uuid", legacy["handoff_id"]))
    published, _ = await publish(h, legacy["handoff_id"], source_kind="handoff")
    assert published["version"] == 1
    assert (await h.call("memory_handoff_list", {})) == []
    assert (await h.call("memory_handoff_inbox", {}))["items"] == []
    await h.call("memory_handoff_pull", {"handoff_id": legacy["handoff_id"]}, ok=False)
    await h.call("memory_handoff_claim", {"handoff_id": legacy["handoff_id"], "claim_token": secrets.token_urlsafe(32)}, ok=False)
    assert (await h.call("memory_handoff_status", {"handoff_id": legacy["handoff_id"]}))["handoff"]["delivery_state"] == "continuity_managed"
    async with h.pool.acquire() as conn:
        after = dict(await conn.fetchrow("SELECT * FROM handoffs WHERE id=$1::uuid", legacy["handoff_id"]))
        # Even a stale server's old SQL cannot consume the promoted source.
        with pytest.raises(Exception, match="immutable"):
            await conn.execute("UPDATE handoffs SET status='claimed',claimed_by='legacy' WHERE id=$1::uuid", legacy["handoff_id"])
    for key in ("payload_digest", "task_envelope", "result_envelope", "recipient_user_id", "envelope_digest"):
        assert before[key] == after[key]


async def test_concurrent_publish_is_one_atomic_fanout_and_receipt(harness):
    h = harness
    await configure(h)
    saved, _ = await checkpoint(h)
    args = {"source_kind": "checkpoint", "source_id": saved["checkpoint_id"], "expected_policy_version": 1,
            "idempotency_key": "same-publish", "reason": "concurrent recovery"}
    results = await asyncio.gather(*[h.call("memory_continuity_publish", args) for _ in range(6)])
    assert len({r["bundle_id"] for r in results}) == 1 and sum(not r["replayed"] for r in results) == 1
    current = await status(h, results[0]["bundle_id"])
    assert len(current["deliveries"]) == 2 and len(current["units"]) == 1


async def test_competing_claimants_and_competing_admins_have_one_winner(harness):
    h = harness
    await configure(h)
    saved, _ = await checkpoint(h)
    published, _ = await publish(h, saved["checkpoint_id"])
    bid = published["bundle_id"]
    current = await status(h, bid)
    uid = current["units"][0]["id"]
    claims = await asyncio.gather(*[h.call("memory_continuity_claim", {"unit_id": uid, "claim_token": secrets.token_urlsafe(32)}, role=role)
                                    for role in ("admin", "admin2")], return_exceptions=True)
    assert sum(isinstance(r, dict) for r in claims) == 1
    assert "active owner" in str(next(r for r in claims if isinstance(r, Exception)))
    args = await reassignment(h, bid)
    mutations = await asyncio.gather(*[h.call("memory_continuity_reassign", {**args, "idempotency_key": role}, role=role)
                                      for role in ("admin", "admin2")], return_exceptions=True)
    assert sum(isinstance(r, dict) for r in mutations) == 1
    assert (await status(h, bid))["bundle"]["version"] == 2


async def test_release_receipts_token_reuse_and_terminal_work(harness):
    h = harness
    await configure(h)
    saved, _ = await checkpoint(h)
    published, _ = await publish(h, saved["checkpoint_id"])
    uid = (await status(h, published["bundle_id"]))["units"][0]["id"]
    claim, _ = await take(h, uid)
    release = {**claim, "action": "release", "reason": "pause", "idempotency_key": "release"}
    assert (await h.call("memory_continuity_release", release))["state"] == "available"
    assert (await h.call("memory_continuity_release", release))["replayed"]
    await h.call("memory_continuity_claim", {"unit_id": uid, "claim_token": claim["claim_token"]}, ok=False)
    new_claim, _ = await take(h, uid, role="admin2")
    assert (await h.call("memory_continuity_release", release))["replayed"]
    assert (await status(h, published["bundle_id"]))["units"][0]["claimed_by"] == "admin2"
    completed = await h.call("memory_continuity_release", {**new_claim, "action": "complete", "reason": "reported done", "idempotency_key": "done"}, role="admin2")
    assert completed["execution_verified"] is False
    await h.call("memory_continuity_claim", {"unit_id": uid, "claim_token": secrets.token_urlsafe(32)}, ok=False)


async def test_renewal_is_absolute_and_expired_owner_cannot_revive(harness):
    h = harness
    await configure(h)
    saved, _ = await checkpoint(h)
    published, _ = await publish(h, saved["checkpoint_id"])
    uid = (await status(h, published["bundle_id"]))["units"][0]["id"]
    claim, original = await take(h, uid)
    same = await h.call("memory_continuity_renew", {**claim, "lease_expires_at": original["lease_expires_at"]})
    assert same["extended"] is False
    await h.call("memory_continuity_renew", {**claim, "lease_expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat()}, ok=False)
    async with h.pool.acquire() as conn:
        await conn.execute("UPDATE memory_continuity_units SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE id=$1::uuid", uid)
    await h.call("memory_continuity_renew", {**claim, "lease_expires_at": original["lease_expires_at"]}, ok=False)
    replacement, _ = await take(h, uid, role="admin2")
    assert replacement["claim_generation"] > claim["claim_generation"]


async def test_revoked_recipient_blocks_atomic_publish_but_admin_can_disable(harness):
    h = harness
    _, config_args = await configure(h)
    saved, _ = await checkpoint(h)
    async with h.pool.acquire() as conn:
        await conn.execute("UPDATE access_tokens SET revoked_at=clock_timestamp() WHERE project_id=$1 AND user_id='admin2'", h.project)
    await h.call("memory_continuity_publish", {"source_kind": "checkpoint", "source_id": saved["checkpoint_id"],
                 "expected_policy_version": 1, "idempotency_key": "bad", "reason": "offline recipient"}, ok=False)
    async with h.pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM memory_continuity_bundles WHERE project_id=$1", h.project) == 0
    disabled = {**config_args, "policy": {**config_args["policy"], "enabled": False}, "expected_version": 1, "idempotency_key": "disable"}
    await h.call("memory_continuity_policy_set", disabled)
    package, snapshot = captured()
    await h.call("memory_checkpoint_save", {"work_id": "disabled", "expected_version": 0, "continuation": package, "snapshot": snapshot,
                 "classification": "internal", "lock_snapshot_digest": "sha256:" + "a" * 64, "idempotency_key": "disabled"}, role="writer", ok=False)


async def test_pending_recovery_uses_sender_override_and_never_self_handoff(harness):
    h = harness
    await configure(h, sender_rules=[{"from_user_id": "writer", "recipient_user_ids": ["admin2"], "backup_user_ids": ["admin"]}])
    saved, _ = await checkpoint(h)
    published, _ = await publish(h, saved["checkpoint_id"])
    assert published["recipient_user_ids"] == ["admin2"]
    other, _ = await checkpoint(h)
    args = {"source_kind": "checkpoint", "source_id": other["checkpoint_id"], "expected_policy_version": 1,
            "recipient_user_ids": ["admin"], "idempotency_key": "override", "reason": "unapproved override"}
    await h.call("memory_continuity_publish", args, role="writer", ok=False)
    assert (await h.call("memory_continuity_publish", args))["recipient_user_ids"] == ["admin"]
    last, _ = await checkpoint(h)
    await h.call("memory_continuity_publish", {**args, "source_id": last["checkpoint_id"], "recipient_user_ids": ["writer"], "idempotency_key": "self"}, ok=False)


async def test_cursor_is_actor_scoped_and_metadata_never_contains_snapshot_or_tokens(harness):
    h = harness
    await configure(h)
    for _ in range(3):
        saved, _ = await checkpoint(h)
        await publish(h, saved["checkpoint_id"])
    page = await h.call("memory_continuity_inbox", {"limit": 1})
    assert page["has_more"] and page["next_cursor"]
    await h.call("memory_continuity_inbox", {"limit": 1, "cursor": page["next_cursor"]}, role="admin2", ok=False)
    second = await h.call("memory_continuity_inbox", {"limit": 1, "cursor": page["next_cursor"]})
    assert page["items"][0]["id"] != second["items"][0]["id"]
    current = await status(h, page["items"][0]["bundle_id"])
    assert all("claim_token_digest" not in u and "claim_token" not in u for u in current["units"])
    assert all("snapshot" not in item and "continuation" not in item for item in page["items"])


async def test_checkpoint_retention_and_immutable_provenance(harness):
    h = harness
    await configure(h)
    saved, _ = await checkpoint(h, classification="confidential")
    await h.call("memory_checkpoint_read", {"checkpoint_id": saved["checkpoint_id"]}, ok=False)
    allowed = await h.call("memory_checkpoint_read", {"checkpoint_id": saved["checkpoint_id"], "max_classification": "confidential"})
    assert allowed["source"]["classification"] == "confidential"
    async with h.pool.acquire() as conn:
        with pytest.raises(Exception, match="immutable"):
            await conn.execute("UPDATE memory_checkpoints SET from_user='someone-else' WHERE id=$1::uuid", saved["checkpoint_id"])
        with pytest.raises(Exception, match="immutable"):
            await conn.execute("DELETE FROM memory_continuity_events WHERE project_id=$1", h.project)
