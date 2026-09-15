"""Authenticated M9 overview/list against an explicitly selected synthetic DB."""

import asyncio
import json
import os
import secrets
from uuid import uuid4

import asyncpg
import pytest

from isekai_memory.continuity import overview
from isekai_memory.server.auth import hash_token
from isekai_memory.store import queries
from tests.test_continuity_postgres import checkpoint, configure, publish, reassignment, status, take
from tests.test_experience_postgres import harness as harness  # noqa: F401

pytestmark = pytest.mark.skipif(not os.environ.get("MEMORY_TEST_DATABASE_URL"), reason="requires disposable PostgreSQL")


async def setup(h):
    raw = secrets.token_urlsafe(32)
    h.tokens["receiver"] = raw
    await queries.create_token(token_hash=hash_token(raw), project_id=h.project, user_id="receiver",
                               scopes=["read", "write"], expires_at=None)
    await configure(h, default_recipient_user_ids=["admin", "receiver"])


async def seed(h, **options):
    saved, _ = await checkpoint(h, **options)
    published, _ = await publish(h, saved["checkpoint_id"])
    return saved, published


async def listing(h, view, role="admin", **options):
    return await h.call("memory_collaboration_list", {"view": view, **options}, role=role)


async def snapshot(h):
    tables = ("memory_continuity_policies", "memory_checkpoints", "memory_continuity_bundles",
              "memory_continuity_deliveries", "memory_continuity_units", "memory_continuity_receipts",
              "memory_continuity_claims", "memory_continuity_events")
    return {table: await h.pool.fetchval(
        f"SELECT jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text) FROM {table} t WHERE project_id=$1", h.project
    ) for table in tables}


async def test_empty_overview_without_policy_and_unavailable_telemetry(harness):
    h = harness
    for role in ("admin", "writer", "read"):
        result = await h.call("memory_collaboration_overview", {}, role=role)
        assert result["actor_id"] == role
        assert result["scope"]["kind"] == "mine"
        assert result["continuity_policy"] == {"configured": False, "version": 0, "enabled": False}
        assert all(value["value"] == 0 for value in result["counts"].values())
        assert all(value["value"] is None for value in result["telemetry"].values())
        assert result["telemetry"]["presence"]["status"] == result["telemetry"]["idle"]["status"] == "separate_query"
        assert result["telemetry"]["token_usage"]["status"] == "separate_query"
        assert result["telemetry"]["token_usage"]["reason"] == "use_usage_tools"
        assert result["capabilities"]["presence"] and result["capabilities"]["idle"]
        assert result["identity"]["project_admin"] is (role == "admin")
        assert ("memory_continuity_reassign" in result["allowed_tools"]) is (role == "admin")
        assert ("memory_continuity_ack" in result["allowed_tools"]) is (role != "read")


async def test_mine_vs_admin_project_visibility_and_counts(harness):
    h = harness
    await setup(h)
    await seed(h)
    expected = {
        "admin": {"work": 1, "inbox": 1, "sent": 0, "checkpoints": 0},
        "receiver": {"work": 1, "inbox": 1, "sent": 0, "checkpoints": 0},
        "writer": {"work": 1, "inbox": 0, "sent": 1, "checkpoints": 1},
        "read": {"work": 0, "inbox": 0, "sent": 0, "checkpoints": 0},
    }
    for role, counts in expected.items():
        result = await h.call("memory_collaboration_overview", {}, role=role)
        assert {key: count["value"] for key, count in result["counts"].items()} == counts
        for view, count in counts.items():
            page = await listing(h, view, role=role)
            assert len(page["items"]) == count
            assert page["cache_policy"] == "no_store" and page["project_id"] == h.project
    result = await h.call("memory_collaboration_overview", {"scope": "project"})
    assert {key: count["value"] for key, count in result["counts"].items()} == {
        "work": 1, "inbox": 2, "sent": 1, "checkpoints": 1,
    }
    for name, args in (("memory_collaboration_overview", {}), ("memory_collaboration_list", {"view": "work"})):
        await h.call(name, {**args, "scope": "project"}, role="receiver", ok=False)
        await h.call(name, args, role="other", ok=False)


async def test_metadata_and_polls_do_not_change_deliveries_claims_or_storage(harness):
    h = harness
    await setup(h)
    _, published = await seed(h)
    unit = (await status(h, published["bundle_id"]))["units"][0]
    await take(h, unit["id"])
    before = await snapshot(h)
    for _ in range(2):
        for view in overview.VIEWS:
            page = await listing(h, view, scope="project", include_inactive=True, include_acknowledged=True)
            serialized = json.dumps(page)
            for forbidden in ('"snapshot":', '"continuation":', '"claim_token_digest":', '"claim_token":', '"content_base64":'):
                assert forbidden not in serialized
        await h.call("memory_collaboration_overview", {"scope": "project"})
    assert await snapshot(h) == before
    row = (await listing(h, "work"))["items"][0]
    assert row["ownership"] == "valid" and row["execution_state"] == "unobserved"


async def test_classification_filter_applies_to_counts_and_all_rows(harness):
    h = harness
    await setup(h)
    await seed(h)
    await seed(h, classification="restricted")
    for maximum, count in (("public", 0), ("internal", 1), ("restricted", 2)):
        result = await h.call("memory_collaboration_overview", {"scope": "project", "max_classification": maximum})
        assert result["counts"]["checkpoints"]["value"] == count
        for view in ("work", "sent", "checkpoints"):
            page = await listing(h, view, scope="project", max_classification=maximum)
            assert len(page["items"]) == count


async def test_scoped_pagination_refresh_and_count_not_page_length(harness):
    h = harness
    await setup(h)
    for _ in range(3):
        await seed(h)
    found, cursor = [], None
    while True:
        page = await listing(h, "sent", role="writer", limit=1, **({"cursor": cursor} if cursor else {}))
        found.extend(row["id"] for row in page["items"])
        if not page["has_more"]:
            break
        cursor = page["next_cursor"]
    assert len(found) == len(set(found)) == 3
    summary = await h.call("memory_collaboration_overview", {}, role="writer")
    assert summary["counts"]["sent"]["value"] == 3
    page = await listing(h, "sent", role="writer", limit=1)
    cursor = page["next_cursor"]
    for options, role in (({"view": "work"}, "writer"), ({"scope": "project"}, "admin"),
                          ({"max_classification": "restricted"}, "writer"), ({}, "receiver"),
                          ({"include_inactive": True}, "writer")):
        await h.call("memory_collaboration_list", {"view": "sent", "cursor": cursor, **options}, role=role, ok=False)
    _, latest = await seed(h)
    assert (await listing(h, "sent", role="writer", limit=1))["items"][0]["id"] == latest["bundle_id"]


async def test_acknowledgement_and_revoked_recipient_are_not_reexposed(harness):
    h = harness
    await setup(h)
    _, published = await seed(h)
    inbox = await listing(h, "inbox", role="receiver")
    await h.call("memory_continuity_ack", {"delivery_id": inbox["items"][0]["id"], "idempotency_key": "ack"}, role="receiver")
    assert (await listing(h, "inbox", role="receiver"))["items"] == []
    assert (await listing(h, "inbox", role="receiver", include_acknowledged=True))["items"][0]["effective_state"] == "acknowledged"
    assert len((await listing(h, "inbox"))["items"]) == 1
    changed = await reassignment(h, published["bundle_id"])
    changed["work_units"] = [{**unit, "assignee_user_ids": ["admin", "admin2"]} for unit in changed["work_units"]]
    await h.call("memory_continuity_reassign", changed)
    for view in ("inbox", "work"):
        assert (await listing(h, view, role="receiver", include_inactive=True, include_acknowledged=True))["items"] == []


async def test_expired_lease_is_derived_without_mutation(harness):
    h = harness
    await setup(h)
    _, published = await seed(h)
    unit = (await status(h, published["bundle_id"]))["units"][0]
    await take(h, unit["id"])
    await h.pool.execute("UPDATE memory_continuity_units SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE id=$1", unit["id"])
    before = await snapshot(h)
    row = (await listing(h, "work"))["items"][0]
    assert row["state"] == "claimed" and row["effective_state"] == "lease_expired" and row["ownership"] == "expired"
    assert await snapshot(h) == before
    await h.pool.execute("UPDATE memory_continuity_bundles SET expires_at=clock_timestamp()-interval '1 second' WHERE id=$1", published["bundle_id"])
    assert (await listing(h, "work"))["items"] == []
    row = (await listing(h, "work", include_inactive=True))["items"][0]
    assert row["effective_state"] == "expired" and row["ownership"] == "unavailable"


async def test_forgotten_checkpoint_metadata_without_erased_bodies(harness):
    h = harness
    await setup(h)
    saved, _ = await seed(h)
    await h.call("memory_checkpoint_forget", {"checkpoint_id": saved["checkpoint_id"], "reason": "test erasure",
                                            "idempotency_key": uuid4().hex})
    assert (await listing(h, "checkpoints", role="writer"))["items"] == []
    row = (await listing(h, "checkpoints", role="writer", include_inactive=True))["items"][0]
    assert row["effective_state"] == "forgotten" and "snapshot" not in row
    assert (await listing(h, "sent", role="writer", include_inactive=True))["items"][0]["effective_state"] == "revoked"


async def test_bounded_counts_mark_partial_not_exact_page_counts(harness, monkeypatch):
    h = harness
    await setup(h)
    for _ in range(3):
        await seed(h)
    monkeypatch.setattr(overview, "COUNT_LIMIT", 2)
    result = await h.call("memory_collaboration_overview", {}, role="writer")
    assert result["counts"]["sent"] == {"value": None, "lower_bound": 2, "coverage": "partial"}
    assert result["counts"]["inbox"] == {"value": 0, "lower_bound": 0, "coverage": "complete"}
    assert result["coverage"] == "partial"


async def test_database_read_only_guard_and_no_mutation_advisory_lock(harness):
    h = harness
    async with overview.read_transaction() as conn:
        assert await conn.fetchval("SHOW transaction_read_only") == "on"
        assert await conn.fetchval("SHOW transaction_isolation") == "repeatable read"
        with pytest.raises(asyncpg.ReadOnlySQLTransactionError):
            await conn.execute("UPDATE memory_continuity_policies SET version=version WHERE project_id=$1", h.project)
    async with h.pool.acquire() as conn, conn.transaction():
        await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended($1,0))", "isekai-continuity:" + h.project)
        result = await asyncio.wait_for(h.call("memory_collaboration_overview", {}), timeout=1)
        assert result["counts"]["work"]["value"] == 0


async def test_token_revocation_no_stale_success(harness):
    h = harness
    await h.call("memory_collaboration_overview", {}, role="read")
    record = await queries.get_token_by_hash(token_hash=hash_token(h.tokens["read"]))
    await queries.revoke_token(token_id=str(record["id"]))
    # Authentication failures occur before the MCP tool body, as HTTP 401.
    response = await h.client.post("/mcp", headers={"Authorization": "Bearer " + h.tokens["read"]},
                                   json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {}})
    assert response.status_code == 401
