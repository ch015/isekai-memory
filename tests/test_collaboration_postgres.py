"""M7 authenticated multi-user delivery tests against an explicit disposable DB."""

import asyncio
import json
import os
import secrets
from datetime import timedelta

import pytest

from isekai_memory.server.auth import hash_token
from isekai_memory.store import queries
from tests.test_experience_postgres import harness as harness  # noqa: F401

pytestmark = pytest.mark.skipif(not os.environ.get("MEMORY_TEST_DATABASE_URL"), reason="requires disposable PostgreSQL")


async def claim(h, handoff_id=None, role="admin", **extra):
    if handoff_id is None:
        handoff_id = (await h.source())["handoff_id"]
    args = {"handoff_id": handoff_id, "claim_token": secrets.token_urlsafe(32), **extra}
    result = await h.call("memory_handoff_claim", args, role=role)
    return {"handoff_id": handoff_id, "claim_token": args["claim_token"],
            "claim_generation": result["claim_generation"]}, result


async def deadline(h, seconds=600):
    now = await h.pool.fetchval("SELECT clock_timestamp()")
    return (now + timedelta(seconds=seconds)).isoformat()


async def get_state(h, handoff_id, role="read", **kwargs):
    result = await h.call("memory_handoff_status", {"handoff_id": handoff_id, **kwargs}, role=role)
    assert result["cache_policy"] == "no_store"
    return result["handoff"]


async def test_multiuser_inbox_and_sent_receipt_without_consuming(harness):
    h = harness
    source = await h.source()
    hid = source["handoff_id"]
    inbox = await h.call("memory_handoff_inbox", {}, role="read")
    assert inbox["items"][0]["handoff_id"] == hid
    assert inbox["items"][0]["delivery_state"] == "available"
    assert (await get_state(h, hid))["can_claim"]
    assert (await h.call("memory_handoff_inbox", {"view": "sent"}, role="admin"))["items"] == []
    assert len((await h.call("memory_handoff_inbox", {"view": "sent"}, role="writer"))["items"]) == 1
    args, _ = await claim(h, hid)
    assert (await h.call("memory_handoff_inbox", {}, role="read"))["items"] == []
    assert (await h.call("memory_handoff_inbox", {"view": "claimed"}, role="writer"))["items"] == []
    assert (await h.call("memory_handoff_inbox", {"view": "claimed"}))["items"][0]["claimed_by"] == "admin"
    await h.call("memory_handoff_ack", args)
    sent = (await h.call("memory_handoff_inbox", {"view": "sent"}, role="writer"))["items"][0]
    assert sent["delivery_state"] == "acknowledged" and not sent["can_claim"]
    assert sent["claimed_by"] == "admin"


async def test_expired_lease_becomes_discoverable_and_old_owner_is_fenced(harness):
    h = harness
    args, _ = await claim(h)
    hid = args["handoff_id"]
    await h.pool.execute("UPDATE handoffs SET claim_lease_expires_at=clock_timestamp()-interval '1 second' WHERE id=$1::uuid", hid)
    entry = (await h.call("memory_handoff_inbox", {}, role="writer"))["items"][0]
    assert entry["delivery_state"] == "lease_expired" and entry["can_claim"]
    assert (await h.call("memory_handoff_inbox", {"view": "claimed"}))["items"] == []
    new_args, _ = await claim(h, hid, role="writer")
    assert new_args["claim_generation"] > args["claim_generation"]
    await h.call("memory_handoff_renew", {**args, "lease_expires_at": await deadline(h)}, ok=False)
    await h.call("memory_handoff_ack", args, ok=False)
    await h.call("memory_handoff_nack", {**args, "reason_code": "retryable"}, ok=False)
    await h.call("memory_handoff_ack", new_args, role="writer")


async def test_competing_users_have_exactly_one_claim_winner(harness):
    h = harness
    hid = (await h.source())["handoff_id"]
    roles = ["admin", "admin2", "writer"]
    results = await asyncio.gather(*[
        queries.claim_handoff_lease(handoff_id=hid, project_id=h.project, claimed_by=role,
                                   claim_token_digest=hash_token(secrets.token_urlsafe(32)), lease_seconds=300)
        for role in roles
    ])
    assert sum(value is not None for value in results) == 1
    assert (await get_state(h, hid))["delivery_state"] == "leased"


async def test_renew_is_monotonic_replayable_and_preserves_payload_and_generation(harness):
    h = harness
    args, initial = await claim(h)
    hid = args["handoff_id"]
    before = dict(await h.pool.fetchrow("SELECT * FROM handoffs WHERE id=$1::uuid", hid))
    request = {**args, "lease_expires_at": await deadline(h)}
    results = await asyncio.gather(*[h.call("memory_handoff_renew", request) for _ in range(5)])
    assert sum(r["extended"] for r in results) == 1
    assert all(r["lease_expires_at"] == request["lease_expires_at"] for r in results)
    assert all(r["claim_generation"] == initial["claim_generation"] for r in results)
    after = dict(await h.pool.fetchrow("SELECT * FROM handoffs WHERE id=$1::uuid", hid))
    assert {k: v for k, v in before.items() if k != "claim_lease_expires_at"} == {
        k: v for k, v in after.items() if k != "claim_lease_expires_at"}
    shorter = await h.call("memory_handoff_renew", {**args, "lease_expires_at": initial["lease_expires_at"]})
    assert not shorter["extended"] and shorter["lease_expires_at"] == request["lease_expires_at"]
    await h.call("memory_handoff_ack", args)
    await h.call("memory_handoff_renew", request, ok=False)


async def test_renew_cannot_exceed_retention_or_max_duration(harness):
    h = harness
    args, _ = await claim(h, lease_seconds=30)
    hid = args["handoff_id"]
    expires = await deadline(h, 90)
    await h.pool.execute("UPDATE handoffs SET expires_at=$2::text::timestamptz WHERE id=$1::uuid", hid, expires)
    error = await h.call("memory_handoff_renew", {**args, "lease_expires_at": await deadline(h, 4000)}, ok=False)
    assert error["error"]["error_code"] == "MEM-HANDOFF-0011"
    renewed = await h.call("memory_handoff_renew", {**args, "lease_expires_at": await deadline(h, 600)})
    assert renewed["lease_expires_at"] == expires
    assert (await get_state(h, hid))["expires_at"] == expires


@pytest.mark.parametrize("kind", ["actor", "token", "generation", "expired", "retention", "nacked", "acknowledged", "legacy"])
async def test_renew_rejects_non_owner_or_inactive_claim(harness, kind):
    h = harness
    args, _ = await claim(h)
    hid = args["handoff_id"]
    role = "admin"
    if kind == "actor":
        role = "admin2"
    elif kind == "token":
        args["claim_token"] = secrets.token_urlsafe(32)
    elif kind == "generation":
        args["claim_generation"] += 1
    elif kind == "expired":
        await h.pool.execute("UPDATE handoffs SET claim_lease_expires_at=clock_timestamp()-interval '1 second' WHERE id=$1::uuid", hid)
    elif kind == "retention":
        await h.pool.execute("UPDATE handoffs SET expires_at=clock_timestamp()-interval '1 second' WHERE id=$1::uuid", hid)
    elif kind == "nacked":
        await h.call("memory_handoff_nack", {**args, "reason_code": "retryable"})
    elif kind == "acknowledged":
        await h.call("memory_handoff_ack", args)
    else:
        await h.pool.execute("UPDATE handoffs SET claim_lease_expires_at=NULL, claim_token_digest=NULL WHERE id=$1::uuid", hid)
    before = dict(await h.pool.fetchrow("SELECT * FROM handoffs WHERE id=$1::uuid", hid))
    result = await h.call("memory_handoff_renew", {**args, "lease_expires_at": await deadline(h)}, role=role, ok=False)
    assert result["error"]["error_code"] == "MEM-HANDOFF-0010"
    assert dict(await h.pool.fetchrow("SELECT * FROM handoffs WHERE id=$1::uuid", hid)) == before


async def test_inbox_cursor_paginates_ties_and_is_actor_bound(harness):
    h = harness
    ids = [(await h.source())["handoff_id"] for _ in range(5)]
    await h.pool.execute("UPDATE handoffs SET created_at=TIMESTAMPTZ '2026-01-01T00:00:00Z' WHERE project_id=$1", h.project)
    first = await h.call("memory_handoff_inbox", {"limit": 2}, role="writer")
    second = await h.call("memory_handoff_inbox", {"limit": 2, "cursor": first["next_cursor"]}, role="writer")
    third = await h.call("memory_handoff_inbox", {"limit": 2, "cursor": second["next_cursor"]}, role="writer")
    assert [r["handoff_id"] for page in (first, second, third) for r in page["items"]] == sorted(ids, reverse=True)
    assert not third["has_more"] and third["next_cursor"] is None
    assert first["cache_policy"] == "no_store"
    await h.call("memory_handoff_inbox", {"cursor": first["next_cursor"]}, role="admin", ok=False)
    await h.call("memory_handoff_inbox", {"cursor": first["next_cursor"], "view": "sent"}, role="writer", ok=False)


async def test_project_classification_and_schema_authority(harness):
    h = harness
    hid = (await h.source(classification="confidential"))["handoff_id"]
    assert (await h.call("memory_handoff_inbox", {}, role="read"))["items"] == []
    await h.call("memory_handoff_status", {"handoff_id": hid}, role="read", ok=False)
    await h.call("memory_handoff_status", {"handoff_id": hid, "project_id": h.project + "-other"}, role="other", ok=False)
    assert (await h.call("memory_handoff_inbox", {"project_id": h.project + "-other", "max_classification": "restricted"}, role="other"))["items"] == []
    assert (await get_state(h, hid, max_classification="confidential"))["classification"] == "confidential"
    assert (await h.call("memory_handoff_inbox", {"unit_id": "unrelated", "max_classification": "restricted"}))["items"] == []
    await h.call("memory_handoff_inbox", {"actor_id": "admin"}, role="writer", ok=False)
    args, _ = await claim(h, hid)
    await h.call("memory_handoff_renew", {**args, "lease_expires_at": await deadline(h)}, role="read", ok=False)


async def test_metadata_is_bounded_and_never_contains_private_claim_capabilities(harness):
    h = harness
    args, _ = await claim(h)
    hid = args["handoff_id"]
    await h.pool.execute("UPDATE handoffs SET task_summary=repeat('가',4096), handoff_note=repeat('나',16384) WHERE id=$1::uuid", hid)
    value = await get_state(h, hid)
    assert len(value["task_summary"]) == len(value["handoff_note"]) == 512 and value["preview_truncated"]
    for name in ("claim_token", "claim_token_digest", "raw_output", "task_envelope", "result_envelope", "artifacts_produced"):
        assert name not in value
    assert args["claim_token"] not in json.dumps(value)
    assert value["payload_digest"].startswith("sha256:")


async def test_legacy_and_retention_expired_claims_are_not_available(harness):
    h = harness
    legacy = (await h.source())["handoff_id"]
    await h.call("memory_handoff_pull", {"handoff_id": legacy})
    expired = (await h.source())["handoff_id"]
    await h.pool.execute("UPDATE handoffs SET expires_at=clock_timestamp()-interval '1 second' WHERE id=$1::uuid", expired)
    assert (await h.call("memory_handoff_inbox", {}))["items"] == []
    assert (await get_state(h, legacy))["delivery_state"] == "legacy_claimed"
    assert (await get_state(h, expired))["delivery_state"] == "expired"
    assert len((await h.call("memory_handoff_inbox", {"view": "sent"}, role="writer"))["items"]) == 2


async def test_revoked_token_loses_inbox_access(harness):
    h = harness
    row = await queries.get_token_by_hash(token_hash=hash_token(h.tokens["writer"]))
    await queries.revoke_token(token_id=str(row["id"]))
    response = await h.client.post("/tools/memory_handoff_inbox", json={"project_id": h.project},
                                   headers={"Authorization": "Bearer " + h.tokens["writer"]})
    assert response.status_code == 401


async def test_waiting_renew_rechecks_expiry_after_row_lock(harness):
    h = harness
    args, _ = await claim(h)
    request = {**args, "lease_expires_at": await deadline(h)}
    async with h.pool.acquire() as conn, conn.transaction():
        await conn.fetchrow("SELECT id FROM handoffs WHERE id=$1::uuid FOR UPDATE", args["handoff_id"])
        waiting = asyncio.create_task(h.call("memory_handoff_renew", request, ok=False))
        await conn.execute("UPDATE handoffs SET claim_lease_expires_at=clock_timestamp()-interval '1 second' WHERE id=$1::uuid", args["handoff_id"])
        await asyncio.sleep(0.03)
    assert (await waiting)["error"]["error_code"] == "MEM-HANDOFF-0010"
