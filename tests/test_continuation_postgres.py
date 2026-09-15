"""M8 project/recipient fencing, immutable packets and legacy safety on PostgreSQL."""

import asyncio
import os
import secrets
from copy import deepcopy
from datetime import timedelta
from uuid import uuid4

import pytest

from isekai_memory.handoff.service import _compute_envelope_digest, _digest
from isekai_memory.server.auth import hash_token
from isekai_memory.store import queries
from tests.helpers import continuation_package, handoff_arguments
from tests.test_experience_postgres import harness as harness  # noqa: F401

pytestmark = pytest.mark.skipif(not os.environ.get("MEMORY_TEST_DATABASE_URL"), reason="requires disposable PostgreSQL")


def addressed_args():
    args = handoff_arguments()
    args["phase_attempt_id"] = "m8-" + uuid4().hex
    for field in ("task_envelope", "result_envelope"):
        args[field]["phase_attempt_id"] = args["phase_attempt_id"]
    args["envelope_digest"] = _compute_envelope_digest(args["task_envelope"], args["result_envelope"])
    args.update(recipient_user_id="admin", continuation=continuation_package())
    return args


async def publish(h, **overrides):
    args = {**addressed_args(), **overrides}
    # Harness selects its unique test project instead of the fixture's project.
    args.pop("project_id")
    return await h.call("memory_handoff_push", args, role="writer"), args


async def take(h, hid, role="admin"):
    args = {"handoff_id": hid, "claim_token": secrets.token_urlsafe(32)}
    row = await h.call("memory_handoff_claim", {**args, "accept_handoff_version": 2}, role=role)
    return {**args, "claim_generation": row["claim_generation"]}, row


async def test_recipient_inbox_and_status_are_distinct_from_project_privacy(harness):
    h = harness
    source, _ = await publish(h)
    hid = source["handoff_id"]
    for role in ("writer", "admin2", "read"):
        assert (await h.call("memory_handoff_inbox", {}, role=role))["items"] == []
        status = await h.call("memory_handoff_status", {"handoff_id": hid}, role=role)
        assert status["handoff"]["recipient_user_id"] == "admin" and not status["handoff"]["can_claim"]
        assert "continuation" not in status["handoff"]
    available = (await h.call("memory_handoff_inbox", {}))["items"][0]
    assert available["handoff_version"] == 2 and available["can_claim"]
    assert (await h.call("memory_handoff_inbox", {"view": "sent"}, role="writer"))["items"][0]["handoff_id"] == hid


async def test_legacy_consumers_cannot_accidentally_take_enhanced_work(harness):
    h = harness
    source, _ = await publish(h)
    hid = source["handoff_id"]
    assert await h.call("memory_handoff_list", {}) == []
    await h.call("memory_handoff_pull", {"handoff_id": hid}, ok=False)
    await h.call("memory_handoff_claim", {"handoff_id": hid, "claim_token": secrets.token_urlsafe(32)}, ok=False)
    assert await h.pool.fetchval("SELECT claim_generation FROM handoffs WHERE id=$1::uuid", hid) == 0
    _, received = await take(h, hid)
    assert received["handoff_version"] == 2


async def test_non_recipient_cannot_claim_even_with_admin_and_version_opt_in(harness):
    h = harness
    source, _ = await publish(h)
    hid = source["handoff_id"]
    for role in ("writer", "admin2"):
        await h.call("memory_handoff_claim", {"handoff_id": hid, "claim_token": secrets.token_urlsafe(32),
                                              "accept_handoff_version": 2}, role=role, ok=False)
    assert await h.pool.fetchval("SELECT claim_generation FROM handoffs WHERE id=$1::uuid", hid) == 0


async def test_claim_get_and_ack_roundtrip_preserves_the_portable_package(harness):
    h = harness
    source, original = await publish(h)
    args, received = await take(h, source["handoff_id"])
    assert received["continuation"] == original["continuation"]
    assert received["continuation_digest"] == _digest(original["continuation"])
    assert received["preflight"]["status"] == "verification_required"
    assert not received["preflight"]["automatic_resume"]
    identity = {k: args[k] for k in ("handoff_id", "claim_token")}
    recovered = await h.call("memory_handoff_get_claimed", identity)
    assert recovered["continuation"] == received["continuation"]
    assert recovered["payload_digest"] == received["payload_digest"]
    await h.call("memory_handoff_get_claimed", identity, role="admin2", ok=False)
    await h.call("memory_handoff_ack", args)
    assert (await h.call("memory_handoff_ack", args))["already_acknowledged"]
    await h.call("memory_handoff_get_claimed", identity, ok=False)


async def test_packet_recipient_sender_and_legacy_upgrade_conflicts_are_immutable(harness):
    h = harness
    source, args = await publish(h)
    original = dict(await h.pool.fetchrow("SELECT * FROM handoffs WHERE id=$1::uuid", source["handoff_id"]))
    assert (await h.call("memory_handoff_push", args, role="writer"))["already_exists"]
    altered = deepcopy(args["continuation"])
    altered["next_steps"] = ["Changed instructions"]
    for extra in ({"recipient_user_id": "admin2"}, {"continuation": altered}):
        await h.call("memory_handoff_push", {**args, **extra}, role="writer", ok=False)
    await h.call("memory_handoff_push", args, role="admin", ok=False)
    legacy_args = {k: v for k, v in args.items() if k not in ("recipient_user_id", "continuation")}
    await h.call("memory_handoff_push", legacy_args, role="writer", ok=False)
    assert dict(await h.pool.fetchrow("SELECT * FROM handoffs WHERE id=$1::uuid", source["handoff_id"])) == original


@pytest.mark.parametrize("recipient", ["missing", "other", "read", "revoked", "expired", "write-only"])
async def test_recipient_must_have_live_project_read_write_authority(harness, recipient):
    h = harness
    if recipient in {"revoked", "expired", "write-only"}:
        now = await h.pool.fetchval("SELECT clock_timestamp()")
        row = await queries.create_token(token_hash=hash_token(secrets.token_urlsafe(32)), project_id=h.project,
                                         user_id=recipient, scopes=["write"] if recipient == "write-only" else ["read", "write"],
                                         expires_at=now-timedelta(seconds=1) if recipient == "expired" else None)
        if recipient == "revoked":
            await queries.revoke_token(token_id=str(row["id"]))
    args = addressed_args()
    args.pop("project_id")
    error = await h.call("memory_handoff_push", {**args, "recipient_user_id": recipient}, role="writer", ok=False)
    assert error["error"]["error_code"] == "MEM-HANDOFF-0013"
    assert await h.pool.fetchval("SELECT count(*) FROM handoffs WHERE project_id=$1", h.project) == 0


async def test_successful_publish_replay_survives_recipient_revocation_without_creating_new_delivery(harness):
    h = harness
    source, args = await publish(h)
    row = await queries.get_token_by_hash(token_hash=hash_token(h.tokens["admin"]))
    await queries.revoke_token(token_id=str(row["id"]))
    result = await h.call("memory_handoff_push", args, role="writer")
    assert result["handoff_id"] == source["handoff_id"] and result["already_exists"]
    # A different project administrator cannot take over the unreachable recipient.
    await h.call("memory_handoff_claim", {"handoff_id": source["handoff_id"], "claim_token": secrets.token_urlsafe(32),
                                          "accept_handoff_version": 2}, role="admin2", ok=False)


async def test_expiry_and_nack_do_not_drop_recipient_fencing(harness):
    h = harness
    source, _ = await publish(h)
    args, _ = await take(h, source["handoff_id"])
    await h.pool.execute("UPDATE handoffs SET claim_lease_expires_at=clock_timestamp()-interval '1 second' WHERE id=$1::uuid", args["handoff_id"])
    assert (await h.call("memory_handoff_inbox", {}, role="admin2"))["items"] == []
    assert (await h.call("memory_handoff_inbox", {}))["items"][0]["delivery_state"] == "lease_expired"
    await h.call("memory_handoff_claim", {"handoff_id": args["handoff_id"], "claim_token": secrets.token_urlsafe(32),
                                          "accept_handoff_version": 2}, role="admin2", ok=False)
    replacement, _ = await take(h, args["handoff_id"])
    assert replacement["claim_generation"] > args["claim_generation"]
    await h.call("memory_handoff_ack", args, ok=False)
    await h.call("memory_handoff_nack", {**replacement, "reason_code": "retryable"})
    assert (await h.call("memory_handoff_inbox", {}, role="writer"))["items"] == []
    assert (await h.call("memory_handoff_inbox", {}))["items"][0]["can_claim"]


async def test_simultaneous_publish_and_recipient_claim_have_one_identity_and_winner(harness):
    h = harness
    args = addressed_args()
    args.pop("project_id")
    published = await asyncio.gather(*[h.call("memory_handoff_push", args, role="writer") for _ in range(4)])
    assert len({r["handoff_id"] for r in published}) == 1
    assert sum(not r["already_exists"] for r in published) == 1
    hid = published[0]["handoff_id"]
    claims = await asyncio.gather(*[
        queries.claim_handoff_lease(handoff_id=hid, project_id=h.project, claimed_by=actor, claim_token_digest=hash_token(secrets.token_urlsafe(32)),
                                   lease_seconds=300, accept_handoff_version=2)
        for actor in ("admin2", "admin", "admin", "writer")
    ])
    assert sum(row is not None for row in claims) == 1
    assert next(row for row in claims if row)["claimed_by"] == "admin"


async def test_continuation_without_recipient_is_explicitly_opted_in_broadcast(harness):
    h = harness
    args = addressed_args()
    args.pop("project_id")
    args.pop("recipient_user_id")
    source = await h.call("memory_handoff_push", args, role="writer")
    assert source["handoff_version"] == 2 and source["recipient_user_id"] is None
    for role in ("admin", "writer", "admin2"):
        assert (await h.call("memory_handoff_inbox", {}, role=role))["items"][0]["can_claim"]
    _, received = await take(h, source["handoff_id"], role="admin2")
    assert received["continuation"] == args["continuation"]


async def test_unavailable_workspace_is_a_blocked_package_not_claimed_ready(harness):
    h = harness
    package = continuation_package()
    package["workspace"] = {"state": "unavailable", "reason": "Untracked files exist only on sender's machine"}
    source, _ = await publish(h, continuation=package)
    _, received = await take(h, source["handoff_id"])
    assert received["preflight"]["status"] == "blocked"
    assert "workspace_unavailable" in received["preflight"]["blocked_reasons"]


async def test_recipient_only_handoff_is_guarded_and_has_no_portable_resume_claim(harness):
    h = harness
    args = addressed_args()
    args.pop("project_id")
    args.pop("continuation")
    source = await h.call("memory_handoff_push", args, role="writer")
    _, received = await take(h, source["handoff_id"])
    assert received["continuation"] is None and received["continuation_digest"] is None
    assert received["preflight"]["blocked_reasons"] == ["continuation_missing"]


async def test_v1_payloads_and_claim_wire_shape_remain_unchanged(harness):
    h = harness
    source = await h.source()
    row = await h.call("memory_handoff_claim", {"handoff_id": source["handoff_id"], "claim_token": secrets.token_urlsafe(32)})
    for field in ("handoff_version", "recipient_user_id", "continuation", "continuation_digest", "preflight"):
        assert field not in row


async def test_cross_project_claim_and_packet_read_fail_even_with_valid_recipient_name(harness):
    h = harness
    source, _ = await publish(h)
    args, _ = await take(h, source["handoff_id"])
    await h.call("memory_handoff_get_claimed", {"project_id": h.project + "-other", "handoff_id": args["handoff_id"],
                                                "claim_token": args["claim_token"]}, role="other", ok=False)
    await h.call("memory_handoff_claim", {"project_id": h.project + "-other", "handoff_id": args["handoff_id"],
                                         "claim_token": secrets.token_urlsafe(32), "accept_handoff_version": 2}, role="other", ok=False)
