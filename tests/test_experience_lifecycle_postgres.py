"""M2 acceptance: revisions, suppression, erasure and scoped pagination on PG."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import asyncpg
import pytest

from tests.test_experience_postgres import harness as harness

pytestmark = pytest.mark.skipif(not os.environ.get("MEMORY_TEST_DATABASE_URL"), reason="requires disposable PostgreSQL")


async def revision(h, parent, *, content="정정: preserve fencing generation with receipts.", **overrides):
    arguments = {
        "memory_id": parent,
        "expected_version": 2,
        "idempotency_key": uuid4().hex,
        "kind": "decision",
        "title": "인증 모듈 정정",
        "content": content,
        **overrides,
    }
    return await h.call("memory_experience_revise", arguments), arguments


async def review(h, memory_id, action, version, *, ok=True):
    return await h.call(
        "memory_experience_review", {"memory_id": memory_id, "action": action, "expected_version": version}, ok=ok
    )


async def test_revision_switches_active_family_and_preserves_receipts(harness):
    h = harness
    original, args = await h.propose()
    parent = original["memory_id"]
    await h.approve(parent)
    child, edit = await revision(h, parent)
    child_id = child["memory_id"]
    assert (await h.call("memory_read", {"memory_id": parent}, role="read"))["memory"]["content"] == args["content"]
    approved = await h.approve(child_id)
    assert approved["related_memory_id"] == parent
    assert (await h.approve(child_id))["already_applied"]
    assert (await h.call("memory_experience_revise", edit))["already_exists"]
    await h.call("memory_read", {"memory_id": parent}, role="read", ok=False)
    found = (await h.call("memory_search", {"query": "인증 모듈"}, role="read"))["items"]
    assert [item["memory_id"] for item in found] == [child_id]
    audit = await h.call("memory_experience_history", {"memory_id": parent})
    rows = {row["memory_id"]: row for row in audit["items"]}
    assert rows[parent]["content"] == args["content"] and rows[parent]["status"] == "superseded"
    assert rows[child_id]["revision_root_id"] == parent and rows[child_id]["revision_number"] == 2
    assert rows[child_id]["is_correction"] and rows[child_id]["created_by"] == "admin"
    assert rows[parent]["events"][-1]["related_memory_id"] == child_id
    assert audit["suppression"]["reason"] == "superseded"
    blocked = await h.call(
        "memory_experience_propose", {**args, "idempotency_key": uuid4().hex}, role="writer", ok=False
    )
    assert blocked["error"]["error_code"] == "MEM-EXPERIENCE-0007"
    assert (await h.approve(parent))["already_applied"]  # Receipt, not reactivation.
    assert (await h.call("memory_experience_list", {"status": "active"}))["items"][0]["memory_id"] == child_id


async def test_competing_replacements_only_one_wins(harness):
    h = harness
    original, _ = await h.propose()
    parent = original["memory_id"]
    await h.approve(parent)
    first, _ = await revision(h, parent, content="Correction A")
    second, _ = await revision(h, parent, content="Correction B")

    async def submit(memory_id):
        return await h.client.post(
            "/tools/memory_experience_review",
            headers={"Authorization": "Bearer " + h.tokens["admin"]},
            json={"project_id": h.project, "memory_id": memory_id, "action": "approve", "expected_version": 1},
        )

    outcomes = await asyncio.gather(submit(first["memory_id"]), submit(second["memory_id"]))
    assert sorted(response.status_code for response in outcomes) == [200, 409]
    loser = next(response.json() for response in outcomes if response.status_code == 409)
    assert loser["error"]["error_code"] == "MEM-EXPERIENCE-0008"
    assert len((await h.call("memory_experience_list", {"status": "active"}))["items"]) == 1
    async with h.pool.acquire() as conn:
        assert (
            await conn.fetchval("SELECT count(*) FROM memory_experience_events WHERE memory_id=$1::uuid", parent) == 2
        )


@pytest.mark.parametrize("action", ["archive", "forget"])
async def test_parent_retirement_invalidates_pending_correction(harness, action):
    h = harness
    original, _ = await h.propose()
    await h.approve(original["memory_id"])
    child, edit = await revision(h, original["memory_id"])
    await review(h, original["memory_id"], action, 2)
    blocked = await review(h, child["memory_id"], "approve", 1, ok=False)
    assert blocked["error"]["error_code"] == "MEM-EXPERIENCE-0008"
    assert (await h.call("memory_experience_revise", edit))["already_exists"]
    await h.call("memory_experience_revise", {**edit, "idempotency_key": uuid4().hex}, ok=False)


async def test_revision_never_lowers_classification_and_metadata_is_immutable(harness):
    h = harness
    source = await h.source("restricted")
    original, _ = await h.propose(source["handoff_id"])
    await h.approve(original["memory_id"])
    public = await h.source("public")
    child, args = await revision(h, original["memory_id"], source_handoff_id=public["handoff_id"])
    await h.approve(child["memory_id"])
    await h.call("memory_read", {"memory_id": child["memory_id"]}, role="read", ok=False)
    current = (
        await h.call("memory_read", {"memory_id": child["memory_id"], "max_classification": "restricted"}, role="read")
    )["memory"]
    assert current["classification"] == "restricted" and current["source"]["classification"] == "public"
    for forged in ({"is_correction": False}, {"supersedes_id": original["memory_id"]}, {"classification": "public"}):
        await h.call("memory_experience_revise", {**args, **forged}, ok=False)
    async with h.pool.acquire() as conn:
        for sql in ("SET content='overwritten'", "SET classification='public'", "SET revision_number=99"):
            with pytest.raises(asyncpg.CheckViolationError):
                await conn.execute("UPDATE memory_experiences " + sql + " WHERE id=$1::uuid", child["memory_id"])


async def test_title_only_revision_does_not_suppress_unchanged_claim(harness):
    h = harness
    original, args = await h.propose()
    await h.approve(original["memory_id"])
    child, _ = await revision(h, original["memory_id"], content=args["content"])
    await h.approve(child["memory_id"])
    assert (await h.call("memory_experience_history", {"memory_id": original["memory_id"]}))["suppression"] is None


async def test_suppression_blocks_actor_key_title_variants_but_not_new_source_revision(harness):
    h = harness
    original, args = await h.propose(content="ＳＡＦＥ  Retry\nReceipts")
    duplicate, _ = await h.propose(args["source_handoff_id"], content="safe retry receipts")
    await review(h, original["memory_id"], "reject", 1)
    assert (await review(h, duplicate["memory_id"], "approve", 1, ok=False))["error"][
        "error_code"
    ] == "MEM-EXPERIENCE-0007"
    for role in ("writer", "admin"):
        blocked = await h.call(
            "memory_experience_propose",
            {
                **args,
                "idempotency_key": uuid4().hex,
                "title": "New label",
                "content": "safe retry receipts",
                "tags": ["new"],
            },
            role=role,
            ok=False,
        )
        assert blocked["error"]["error_code"] == "MEM-EXPERIENCE-0007"
    assert (await h.call("memory_experience_propose", args, role="writer"))["already_exists"]
    await h.propose(args["source_handoff_id"], content="Changed claim")
    # The digest covers the complete handoff payload, including attempt identity,
    # not just raw_output. A new attempt is a new evidence revision by contract.
    new_source = await h.source()
    await h.propose(new_source["handoff_id"], content="safe retry receipts")


async def test_release_is_explicit_replayable_and_cannot_release_newer_rejection(harness):
    h = harness
    original, args = await h.propose()
    memory_id = original["memory_id"]
    await review(h, memory_id, "reject", 1)
    audit = await h.call("memory_experience_history", {"memory_id": memory_id})
    release = {"memory_id": memory_id, "expected_suppression_version": audit["suppression"]["version"]}
    assert not (await h.call("memory_experience_suppression_release", release))["already_released"]
    assert (await h.call("memory_experience_suppression_release", release))["already_released"]
    await h.call("memory_experience_suppression_release", release, role="admin2", ok=False)
    await h.call("memory_read", {"memory_id": memory_id}, role="read", ok=False)
    newer, _ = await h.propose(args["source_handoff_id"])
    await review(h, newer["memory_id"], "reject", 1)
    blocked = await h.call("memory_experience_suppression_release", release, ok=False)
    assert blocked["error"]["error_code"] == "MEM-EXPERIENCE-0009"
    assert (await h.call("memory_experience_history", {"memory_id": memory_id}))["suppression"]["version"] == 3


async def test_forget_erases_plaintext_and_releases_only_own_source_dependency(harness):
    h = harness
    original, args = await h.propose(tags=["private-label"])
    duplicate, other_args = await h.propose(args["source_handoff_id"], content="Independent evidence")
    memory_id = original["memory_id"]
    await h.approve(memory_id)
    await review(h, memory_id, "forget", 2)
    assert (await review(h, memory_id, "forget", 2))["already_applied"]
    assert (await h.approve(memory_id))["already_applied"]
    audit = await h.call("memory_experience_history", {"memory_id": memory_id})
    tombstone = audit["items"][0]
    assert tombstone["title"] == tombstone["content"] == "[forgotten]"
    assert tombstone["source"] == {} and tombstone["tags"] == [] and tombstone["source_handoff_id"] is None
    assert [event["action"] for event in tombstone["events"]] == ["approve", "forget"]
    await h.call("memory_read", {"memory_id": memory_id}, role="read", ok=False)
    assert (await h.call("memory_search", {"query": "private-label"}, role="read"))["items"] == []
    async with h.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT search_text,search_document::text,submission_digest FROM memory_experiences WHERE id=$1::uuid",
            memory_id,
        )
        assert row["search_text"] == row["search_document"] == "" and row["submission_digest"]
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await conn.execute("DELETE FROM handoffs WHERE id=$1::uuid", args["source_handoff_id"])
    await review(h, duplicate["memory_id"], "forget", 1)
    async with h.pool.acquire() as conn:
        await conn.execute("DELETE FROM handoffs WHERE id=$1::uuid", args["source_handoff_id"])
    for proposal in (args, other_args):
        assert (await h.call("memory_experience_propose", proposal, role="writer"))["already_exists"]


async def test_validity_rejects_future_approval_and_filters_both_endpoints(harness):
    h = harness
    now = datetime.now(UTC)
    future = (now + timedelta(days=1)).isoformat()
    expired = (now - timedelta(days=1)).isoformat()
    original, args = await h.propose(valid_from=future)
    blocked = await review(h, original["memory_id"], "approve", 1, ok=False)
    assert blocked["error"]["error_code"] == "MEM-EXPERIENCE-0004"
    await h.call(
        "memory_experience_propose",
        {**args, "idempotency_key": uuid4().hex, "expires_at": future},
        role="writer",
        ok=False,
    )
    current, _ = await h.propose(valid_from=expired, expires_at=future)
    await h.approve(current["memory_id"])
    async with h.pool.acquire() as conn:
        await conn.execute(
            "UPDATE memory_experiences SET valid_from=now()+interval '1 hour' WHERE id=$1::uuid", current["memory_id"]
        )
    await h.call("memory_read", {"memory_id": current["memory_id"]}, role="read", ok=False)
    assert (await h.call("memory_search", {"query": "인증 모듈"}, role="read"))["items"] == []


async def test_keyset_queue_tolerates_front_insert_and_binds_scope(harness):
    h = harness
    source = await h.source()
    ids = []
    for n in range(5):
        item, _ = await h.propose(source["handoff_id"], title=f"Candidate {n}")
        ids.append(item["memory_id"])
    first = await h.call("memory_experience_list", {"limit": 2})
    front, _ = await h.propose(source["handoff_id"], title="New front")
    collected = [item["memory_id"] for item in first["items"]]
    page = first
    while page["has_more"]:
        page = await h.call("memory_experience_list", {"limit": 2, "cursor": page["next_cursor"]})
        collected.extend(item["memory_id"] for item in page["items"])
        assert page["next_offset"] is None
    assert set(collected) == set(ids) and len(collected) == len(set(collected))
    assert front["memory_id"] not in collected
    for bad in ({"status": "active"}, {"project_id": h.project + "-other"}, {"offset": 0}):
        await h.call(
            "memory_experience_list",
            {"cursor": first["next_cursor"], **bad},
            role="other" if "project_id" in bad else "admin",
            ok=False,
        )
    await h.call("memory_experience_list", {"cursor": "not-a-cursor"}, ok=False)


async def test_history_cursor_family_and_new_admin_tools_are_scoped(harness):
    h = harness
    original, _ = await h.propose()
    await h.approve(original["memory_id"])
    child, revise_args = await revision(h, original["memory_id"])
    first = await h.call("memory_experience_history", {"memory_id": original["memory_id"], "limit": 1})
    second = await h.call(
        "memory_experience_history", {"memory_id": child["memory_id"], "limit": 1, "cursor": first["next_cursor"]}
    )
    assert len({first["items"][0]["memory_id"], second["items"][0]["memory_id"]}) == 2
    other, _ = await h.propose()
    await h.call(
        "memory_experience_history", {"memory_id": other["memory_id"], "cursor": first["next_cursor"]}, ok=False
    )
    for name, args in (
        ("memory_experience_history", {"memory_id": original["memory_id"]}),
        ("memory_experience_revise", revise_args),
        (
            "memory_experience_suppression_release",
            {"memory_id": original["memory_id"], "expected_suppression_version": 1},
        ),
    ):
        await h.call(name, args, role="writer", ok=False)
        await h.call(name, args, role="other", ok=False)
        await h.call(name, {**args, "project_id": h.project + "-other"}, role="other", ok=False)
