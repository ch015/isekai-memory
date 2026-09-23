"""Multi-user authorization, portable provenance and bounded delivery regression tests."""

import os
import secrets

import pytest

from isekai_memory.retrieval.citations import BINDING_FIELDS, canonical, digest
from isekai_memory.server.auth import hash_token
from isekai_memory.store import queries
from tests.helpers import handoff_arguments
from tests.test_continuity import policy_body
from tests.test_experience_postgres import harness as harness  # noqa: F401
from tests.test_project_directory import metadata

pytestmark = pytest.mark.skipif(not os.environ.get("MEMORY_TEST_DATABASE_URL"), reason="requires disposable PostgreSQL")


def arguments(h):
    return {**handoff_arguments(), "project_id": h.project}


async def test_directory_and_scoped_tokens_obey_current_membership(harness):
    h = harness
    await h.call("memory_project_register", metadata(h.project))
    raw = secrets.token_urlsafe(32)
    h.tokens["directory"] = raw
    await queries.create_token(token_hash=hash_token(raw), project_id="directory", user_id="writer",
                               scopes=["read", "write", "projects"], expires_at=None)
    assignment = {"user_id": "writer", "role": "write", "expected_revision": 1}
    await h.call("memory_project_assign", assignment)
    assert (await h.call("memory_project_get", {}, role="directory"))["role"] == "write"
    users = (await h.call("memory_continuity_members", {}))["items"]
    assert {item["user_id"] for item in users} == {"admin", "writer"}
    await h.call("memory_continuity_policy_set", {
        "policy": policy_body(default_recipient_user_ids=["writer"]), "expected_version": 0,
        "idempotency_key": "policy", "reason": "assigned directory user can receive",
    })
    # Remove the per-project credential to prove eligibility is supplied by the directory token itself.
    async with h.pool.acquire() as conn:
        await conn.execute("UPDATE access_tokens SET revoked_at=now() WHERE token_hash=$1", hash_token(h.tokens["writer"]))
    assert "writer" in {x["user_id"] for x in (await h.call("memory_continuity_members", {}))["items"]}
    source = await h.call("memory_handoff_push", {**arguments(h), "recipient_user_id": "writer"})
    assert (await h.call("memory_handoff_claim", {"handoff_id": source["handoff_id"],
        "claim_token": secrets.token_urlsafe(32), "accept_handoff_version": 2}, role="directory"))["claimed_by"] == "writer"
    # Re-enable the synthetic scoped credential; membership must now fence BOTH paths.
    async with h.pool.acquire() as conn:
        await conn.execute("UPDATE access_tokens SET revoked_at=NULL WHERE token_hash=$1", hash_token(h.tokens["writer"]))
    await h.call("memory_project_assign", {**assignment, "role": "read", "expected_revision": 2})
    for role in ("writer", "directory"):
        assert (await h.call("memory_project_get", {}, role=role))["role"] == "read"
        await h.call("memory_handoff_push", arguments(h), role=role, ok=False)
    await h.call("memory_project_assign", {**assignment, "role": "remove", "expected_revision": 3})
    for role in ("writer", "directory"):
        await h.call("memory_handoff_list", {}, role=role, ok=False)
        await h.call("memory_handoff_push", arguments(h), role=role, ok=False)
    assert (await h.call("memory_continuity_members", {}))["items"] == [{"user_id": "admin"}]


async def test_compatibility_is_immutable_and_citation_bound(harness):
    h = harness
    portable = "sha256:" + "c" * 64
    args = {**arguments(h), "compatibility_digest": portable}
    pushed = await h.call("memory_handoff_push", args, role="writer")
    assert (await h.call("memory_handoff_push", args, role="writer"))["already_exists"]
    await h.call("memory_handoff_push", {**args, "compatibility_digest": "sha256:" + "d" * 64}, role="writer", ok=False)
    claim = await h.call("memory_handoff_claim", {"handoff_id": pushed["handoff_id"], "claim_token": secrets.token_urlsafe(32)})
    assert claim["compatibility_digest"] == portable
    proposal, _ = await h.propose(pushed["handoff_id"])
    await h.approve(proposal["memory_id"])
    query = {"query": "인증 모듈", "source_lock_digest": "sha256:" + "e" * 64}
    assert (await h.call("memory_search", query))["items"] == []
    result = await h.call("memory_search", {**query, "compatibility_digest": portable})
    item = result["items"][0]
    assert result["citation_schema_version"] == item["citation"]["schema_version"] == 2
    assert item["source_lock_digest"] == args["lock_snapshot_digest"]  # provenance is never rewritten
    bound = {**{key: item[key] for key in BINDING_FIELDS}, "compatibility_digest": portable,
             **{key: value for key, value in item["citation"].items() if key != "binding_digest"}}
    assert digest(canonical(bound)) == item["citation"]["binding_digest"]
    assert (await h.call("memory_search", {**query, "compatibility_digest": "sha256:" + "f" * 64}))["items"] == []
    await h.call("memory_experience_review", {"memory_id": proposal["memory_id"], "expected_version": 2, "action": "archive"})
    assert (await h.call("memory_search", {**query, "compatibility_digest": portable}))["items"] == []


async def test_pending_pages_are_bounded_and_can_exclude_sender(harness):
    h = harness
    ids = {(await h.source())["handoff_id"] for _ in range(4)}
    assert await h.call("memory_handoff_list", {"exclude_own": True}, role="writer") == []
    first = await h.call("memory_handoff_list", {"limit": 2}, role="admin")
    second = await h.call("memory_handoff_list", {"limit": 2, "after_id": first[-1]["id"]}, role="admin")
    assert len(first) == len(second) == 2
    assert {item["id"] for item in first + second} == ids
    assert await h.call("memory_handoff_list", {"limit": 2, "after_id": second[-1]["id"]}, role="admin") == []
