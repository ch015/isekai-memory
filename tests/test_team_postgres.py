"""M6 real project isolation, revocation, pushed-source drift, exchange and feedback."""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import asyncpg
import pytest

from isekai_memory.experience.persistence import lock_project
from isekai_memory.retrieval.citations import canonical, digest
from isekai_memory.server.errors import MemoryToolError
from isekai_memory.team import feedback, grants, knowledge
from tests.test_experience_postgres import harness as harness  # noqa: F401
from tests.test_generation_postgres import source
from tests.test_skills_postgres import approve, export, propose
from tests.test_team import import_args, native_skill

pytestmark = pytest.mark.skipif(not os.environ.get("MEMORY_TEST_DATABASE_URL"), reason="requires disposable PostgreSQL")


def future(days=1):
    return (datetime.now(UTC) + timedelta(days=days)).isoformat()


def wiki_args(**overrides):
    args = {"provider": "pushed_wiki_v1", "source_key": "wiki/page", "source_revision": "rev1", "expected_version": 0,
            "classification": "internal", "title": "Receipt guide", "content": "Verify the original receipt.", "valid_until": future(), **overrides}
    args["content_digest"] = digest(canonical({k: args[k] for k in ("title", "content")}))
    return args


async def wiki(h, **overrides):
    args = wiki_args(**overrides)
    return await h.call("memory_knowledge_sync", args), args


async def grant(h, kind, asset_id, version, **overrides):
    args = {"asset_kind": kind, "asset_id": asset_id, "asset_version": version, "consumer_project_id": h.project + "-other",
            "max_classification": "internal", "expires_at": future(), "idempotency_key": uuid4().hex, **overrides}
    return await h.call("memory_grant_create", args), args


async def shared(h, gid, *, ok=True, **overrides):
    return await h.call("memory_shared_read", {"project_id": h.project + "-other", "grant_id": gid, "grant_version": 1, **overrides}, role="other", ok=ok)


async def test_exact_grant_reads_are_consumer_only_and_revocable_without_copies(harness):
    h = harness
    memory, _ = await h.propose()
    await h.approve(memory["memory_id"])
    receipt, args = await grant(h, "experience", memory["memory_id"], 2)
    value = await shared(h, receipt["grant_id"])
    assert value["asset"]["data"]["content"] and value["usage"] == "reference_only" and value["cache_policy"] == "no_store"
    assert "source" not in value["asset"]["data"] and "created_by" not in value["asset"]["data"]
    await h.call("memory_shared_read", {"grant_id": receipt["grant_id"], "grant_version": 1}, ok=False)
    await h.call("memory_read", {"project_id": h.project + "-other", "memory_id": memory["memory_id"]}, role="other", ok=False)
    await h.call("memory_grant_create", {**args, "project_id": h.project + "-other", "consumer_project_id": "third"}, role="other", ok=False)
    revoked = {"grant_id": receipt["grant_id"], "expected_version": 1}
    await h.call("memory_grant_revoke", revoked)
    assert (await h.call("memory_grant_revoke", revoked))["already_applied"]
    await h.call("memory_grant_revoke", revoked, role="admin2", ok=False)
    await shared(h, receipt["grant_id"], ok=False)
    assert (await h.call("memory_grant_create", args))["grant_id"] == receipt["grant_id"]
    await shared(h, receipt["grant_id"], ok=False)  # Replay must not resurrect access.
    assert await h.pool.fetchval("SELECT count(*) FROM memory_experiences WHERE project_id=$1", h.project + "-other") == 0


async def test_waiting_shared_read_rechecks_after_owner_commits_revocation(harness):
    h = harness
    doc, _ = await wiki(h)
    receipt, _ = await grant(h, "knowledge", doc["document_id"], 1)
    async with h.pool.acquire() as conn, conn.transaction():
        await lock_project(conn, h.project)
        task = asyncio.create_task(grants.read({"project_id": h.project + "-other", "grant_id": receipt["grant_id"], "grant_version": 1}))
        await conn.execute("UPDATE memory_asset_grants SET version=2,revoked_at=clock_timestamp(),revoked_by='owner' WHERE id=$1::uuid", receipt["grant_id"])
        await asyncio.sleep(0.03)
    with pytest.raises(MemoryToolError):
        await task


async def test_grant_conflicts_boundaries_and_source_retirement(harness):
    h = harness
    memory, _ = await h.propose()
    args = {"asset_kind": "experience", "asset_id": memory["memory_id"], "asset_version": 1, "consumer_project_id": h.project + "-other",
            "expires_at": future(), "max_classification": "internal", "idempotency_key": "one"}
    await h.call("memory_grant_create", args, ok=False)
    await h.approve(memory["memory_id"])
    for extra in ({"expires_at": future(31)}, {"expires_at": future(-1)}, {"consumer_project_id": h.project}, {"max_classification": "public"}):
        await h.call("memory_grant_create", {**args, "asset_version": 2, **extra}, ok=False)
    args.update(asset_version=2)
    outcomes = await asyncio.gather(*[grants.create({"project_id": h.project, **args}, actor_id="admin") for _ in range(3)])
    assert len({r["grant_id"] for r in outcomes}) == 1
    await h.call("memory_grant_create", {**args, "consumer_project_id": "different"}, ok=False)
    await h.call("memory_experience_review", {"memory_id": memory["memory_id"], "action": "archive", "expected_version": 2})
    await shared(h, outcomes[0]["grant_id"], ok=False)


async def test_knowledge_drift_deletion_receipts_class_floor_and_no_search_pollution(harness):
    h = harness
    doc, args = await wiki(h)
    receipt, _ = await grant(h, "knowledge", doc["document_id"], 1)
    await shared(h, receipt["grant_id"])
    changed = wiki_args(source_revision="rev2", expected_version=1, content="Updated receipt policy.", classification="confidential")
    assert (await h.call("memory_knowledge_sync", changed))["version"] == 2
    assert (await h.call("memory_knowledge_sync", args))["already_applied"]
    await shared(h, receipt["grant_id"], ok=False)
    await h.call("memory_knowledge_read", {"document_id": doc["document_id"]}, role="read", ok=False)
    value = await h.call("memory_knowledge_read", {"document_id": doc["document_id"], "max_classification": "confidential"}, role="read")
    assert value["knowledge"]["freshness"] == "publisher_reported" and not value["knowledge"]["provider_revision_verified"]
    assert (await h.call("memory_search", {"query": "receipt"}, role="read"))["items"] == []
    await h.call("memory_knowledge_sync", wiki_args(source_revision="rev3", expected_version=2), ok=False)
    await h.call("memory_knowledge_delete", {"document_id": doc["document_id"], "expected_version": 2})
    row = await h.pool.fetchrow("SELECT * FROM memory_knowledge_documents WHERE id=$1::uuid", doc["document_id"])
    assert row["content"] == row["title"] == "" and row["version"] == 3
    assert (await h.call("memory_knowledge_delete", {"document_id": doc["document_id"], "expected_version": 2}))["already_applied"]
    await h.call("memory_knowledge_sync", wiki_args(source_revision="rev2", expected_version=3, classification="confidential"), ok=False)
    await h.call("memory_knowledge_sync", wiki_args(source_revision="rev3", expected_version=3, classification="confidential"))
    await shared(h, receipt["grant_id"], ok=False)
    await h.call("memory_knowledge_read", {"document_id": doc["document_id"], "expected_version": 1, "max_classification": "restricted"}, ok=False)


async def test_knowledge_sync_cas_expiry_digest_and_unsafe_provider_inputs(harness):
    h = harness
    args = wiki_args()
    results = await asyncio.gather(*[knowledge.sync({"project_id": h.project, **args}, actor_id="admin") for _ in range(3)])
    assert len({r["document_id"] for r in results}) == 1
    for extra in ({"expected_version": 1}, {"service_url": "http://127.0.0.1/private"}, {"provider": "remote"},
                  {"source_revision": "rev2", "expected_version": 1, "content_digest": "sha256:" + "0" * 64}):
        await h.call("memory_knowledge_sync", {**args, **extra}, ok=False)
    for days in (-1, 8):
        await h.call("memory_knowledge_sync", wiki_args(source_key=uuid4().hex, valid_until=future(days)), ok=False)
    doc_id = results[0]["document_id"]
    receipt, _ = await grant(h, "knowledge", doc_id, 1)
    await h.pool.execute("UPDATE memory_knowledge_documents SET valid_until=clock_timestamp()-interval '1 second' WHERE id=$1::uuid", doc_id)
    await h.call("memory_knowledge_read", {"document_id": doc_id}, role="read", ok=False)
    await shared(h, receipt["grant_id"], ok=False)


async def test_skill_grants_respect_lock_classification_and_source_erasure(harness):
    h = harness
    revision, args = await propose(h)
    await approve(h, revision)
    receipt, _ = await grant(h, "skill", revision["revision_id"], 2)
    value = await shared(h, receipt["grant_id"])
    assert value["asset"]["data"]["body"] == args["body"]
    assert "approved_at" not in value["asset"]["data"]
    await shared(h, receipt["grant_id"], ok=False, source_lock_digest="sha256:" + "0" * 64)
    await shared(h, receipt["grant_id"], ok=False, max_classification="public")
    await h.call("memory_experience_review", {"memory_id": args["sources"][0]["memory_id"], "expected_version": 2, "action": "forget"})
    await shared(h, receipt["grant_id"], ok=False)


async def test_export_import_quarantine_forget_and_conflict_receipts(harness):
    h = harness
    revision, _ = await propose(h)
    await approve(h, revision)
    exported = await export(h, revision)
    args = {k: exported[k] for k in ("archive_base64", "archive_digest", "manifest_digest", "artifact_digest")}
    args.update(classification="internal", idempotency_key="native-import", project_id=h.project + "-other")
    imported = await h.call("memory_skill_import", args, role="other")
    assert imported["status"] == "quarantined" and not imported["trusted"]
    inspected = await h.call("memory_skill_import_inspect", {"project_id": h.project + "-other", "import_id": imported["import_id"]}, role="other")
    assert inspected["payload"]["source_claims"]["project_id"] == h.project and inspected["usage"] == "review_only"
    listed = (await h.call("memory_skill_import_list", {"project_id": h.project + "-other"}, role="other"))["items"]
    assert len(listed) == 1 and "payload" not in listed[0]
    await h.call("memory_skill_read", {"project_id": h.project + "-other", "revision_id": imported["import_id"]}, role="other", ok=False)
    assert await h.pool.fetchval("SELECT count(*) FROM memory_skill_revisions WHERE project_id=$1", h.project + "-other") == 0
    assert (await h.call("memory_skill_import", args, role="other"))["already_exists"]
    await h.call("memory_skill_import", {**args, "idempotency_key": "other-key"}, role="other", ok=False)
    await h.call("memory_skill_import", {**args, "classification": "restricted"}, role="other", ok=False)
    await h.call("memory_skill_import_forget", {"project_id": h.project + "-other", "import_id": imported["import_id"], "expected_version": 1}, role="other")
    erased = await h.call("memory_skill_import_inspect", {"project_id": h.project + "-other", "import_id": imported["import_id"]}, role="other")
    assert erased["payload"] == {} and erased["status"] == "forgotten"
    assert (await h.call("memory_skill_import", args, role="other"))["already_exists"]
    assert (await h.call("memory_skill_import_inspect", {"project_id": h.project + "-other", "import_id": imported["import_id"]}, role="other"))["payload"] == {}


async def test_import_same_claimed_identity_different_bytes_is_conflict(harness):
    h = harness
    skill = native_skill()
    args = import_args(skill)
    args["project_id"] = h.project
    await h.call("memory_skill_import", args)
    skill["body"]["title"] = "Changed but same claimed identity"
    skill["content_digest"] = digest(canonical({k: skill[k] for k in ("body", "sources", "classification")}))
    changed = import_args(skill)
    changed.update(project_id=h.project, idempotency_key="another")
    await h.call("memory_skill_import", changed, ok=False)
    await h.call("memory_skill_import_inspect", {"import_id": str(uuid4())}, ok=False)


async def test_feedback_one_actor_version_observation_requires_reported_evidence(harness):
    h = harness
    doc, _ = await wiki(h)
    args = {"asset_kind": "knowledge", "asset_id": doc["document_id"], "asset_version": 1,
            "usefulness": "helpful", "outcome": "succeeded", "idempotency_key": "outcome"}
    await h.call("memory_feedback_record", args, role="writer", ok=False)
    sid = await source(h)
    args["handoff_id"] = sid
    await h.call("memory_feedback_record", {**args, "outcome": "failed"}, role="writer", ok=False)
    values = await asyncio.gather(*[feedback.record({"project_id": h.project, **args}, actor_id="writer") for _ in range(3)])
    assert len({v["feedback_id"] for v in values}) == 1
    await h.call("memory_feedback_record", {**args, "idempotency_key": "stuff-the-ballot"}, role="writer", ok=False)
    await h.call("memory_feedback_record", {**args, "usefulness": "not_helpful"}, role="writer", ok=False)
    items = (await h.call("memory_feedback_list", {"asset_id": doc["document_id"]}))["items"]
    assert len(items) == 1 and items[0]["actor_id"] == "writer" and items[0]["evidence_digest"]
    await h.call("memory_knowledge_delete", {"document_id": doc["document_id"], "expected_version": 1})
    assert (await h.call("memory_feedback_record", args, role="writer"))["already_exists"]
    assert await h.pool.fetchval("SELECT status FROM memory_knowledge_documents WHERE id=$1::uuid", doc["document_id"]) == "deleted"


async def test_shared_feedback_revalidates_grant_and_never_leaks_to_owner(harness):
    h = harness
    doc, _ = await wiki(h)
    receipt, _ = await grant(h, "knowledge", doc["document_id"], 1)
    args = {"project_id": h.project + "-other", "asset_kind": "knowledge", "asset_id": doc["document_id"], "asset_version": 1,
            "usefulness": "uncertain", "outcome": "not_attempted", "idempotency_key": "shared-feedback"}
    await h.call("memory_feedback_record", args, role="other", ok=False)
    args.update(grant_id=receipt["grant_id"], grant_version=1)
    await h.call("memory_feedback_record", {**args, "asset_id": str(uuid4())}, role="other", ok=False)
    await h.call("memory_feedback_record", args, role="other")
    assert (await h.call("memory_feedback_list", {}))["items"] == []
    await h.call("memory_grant_revoke", {"grant_id": receipt["grant_id"], "expected_version": 1})
    assert (await h.call("memory_feedback_record", args, role="other"))["already_exists"]
    await h.call("memory_feedback_record", {**args, "idempotency_key": "new"}, role="other", ok=False)


async def test_admin_inventory_cursor_scope_and_no_plaintext(harness):
    h = harness
    for i in range(3):
        await wiki(h, source_key=f"page-{i}")
    page = await h.call("memory_knowledge_list", {"limit": 1})
    assert len(page["items"]) == 1 and "content" not in page["items"][0]
    rest = await h.call("memory_knowledge_list", {"limit": 2, "cursor": page["next_cursor"]})
    assert len(rest["items"]) == 2 and rest["next_cursor"] is None
    await h.call("memory_grant_list", {"cursor": page["next_cursor"]}, ok=False)
    await h.call("memory_knowledge_list", {"project_id": h.project + "-other", "cursor": page["next_cursor"]}, role="other", ok=False)


async def test_db_guards_preserve_feedback_grant_and_erasure_receipts(harness):
    h = harness
    doc, _ = await wiki(h)
    receipt, _ = await grant(h, "knowledge", doc["document_id"], 1)
    await h.call("memory_grant_revoke", {"grant_id": receipt["grant_id"], "expected_version": 1})
    with pytest.raises(asyncpg.RaiseError):
        await h.pool.execute("UPDATE memory_asset_grants SET version=1,revoked_at=NULL,revoked_by=NULL WHERE id=$1::uuid", receipt["grant_id"])
    with pytest.raises(asyncpg.RaiseError):
        await h.pool.execute("DELETE FROM memory_knowledge_events WHERE document_id=$1::uuid", doc["document_id"])


async def test_grant_expiry_and_unknown_version_fail_closed(harness):
    h = harness
    doc, _ = await wiki(h)
    receipt, _ = await grant(h, "knowledge", doc["document_id"], 1,
                             expires_at=(datetime.now(UTC) + timedelta(seconds=0.3)).isoformat())
    await shared(h, receipt["grant_id"], ok=False, grant_version=2)
    await asyncio.sleep(0.35)
    await shared(h, receipt["grant_id"], ok=False)


async def test_retained_handoff_digest_drift_blocks_shared_experience(harness):
    h = harness
    memory, args = await h.propose()
    await h.approve(memory["memory_id"])
    receipt, _ = await grant(h, "experience", memory["memory_id"], 2)
    await h.pool.execute("UPDATE handoffs SET payload_digest=$2 WHERE id=$1::uuid", args["source_handoff_id"], "sha256:" + "f" * 64)
    await shared(h, receipt["grant_id"], ok=False)


async def test_feedback_rejects_foreign_handoff_pending_sources_and_actor_spoofing(harness):
    h = harness
    memory, _ = await h.propose()
    args = {"asset_kind": "experience", "asset_id": memory["memory_id"], "asset_version": 1,
            "usefulness": "helpful", "outcome": "not_attempted", "idempotency_key": "feedback"}
    await h.call("memory_feedback_record", args, role="writer", ok=False)
    await h.approve(memory["memory_id"])
    args.update(asset_version=2)
    await h.call("memory_feedback_record", {**args, "actor_id": "spoof"}, role="writer", ok=False)
    receipt, _ = await grant(h, "experience", memory["memory_id"], 2)
    sid = await source(h)
    await h.call("memory_feedback_record", {**args, "project_id": h.project + "-other", "grant_id": receipt["grant_id"], "grant_version": 1,
                 "outcome": "succeeded", "handoff_id": sid}, role="other", ok=False)
    assert await h.pool.fetchval("SELECT count(*) FROM memory_asset_feedback WHERE project_id=ANY($1::text[])", [h.project, h.project + "-other"]) == 0


async def test_failed_wiki_write_rolls_back_document_and_history(harness, monkeypatch):
    h = harness
    original = asyncpg.Connection.execute

    async def fail_event(self, query, *args, **kwargs):
        if "INSERT INTO memory_knowledge_events" in query:
            raise RuntimeError("simulated process failure")
        return await original(self, query, *args, **kwargs)

    monkeypatch.setattr(asyncpg.Connection, "execute", fail_event)
    with pytest.raises(RuntimeError):
        await knowledge.sync({"project_id": h.project, **wiki_args()}, actor_id="admin")
    assert await h.pool.fetchval("SELECT count(*) FROM memory_knowledge_documents WHERE project_id=$1", h.project) == 0


async def test_import_and_feedback_database_receipts_cannot_be_modified(harness):
    h = harness
    args = import_args()
    args["project_id"] = h.project
    imported = await h.call("memory_skill_import", args)
    with pytest.raises(asyncpg.RaiseError):
        await h.pool.execute("UPDATE memory_skill_imports SET payload='{}'::jsonb WHERE id=$1::uuid", imported["import_id"])
    await h.call("memory_skill_import_forget", {"import_id": imported["import_id"], "expected_version": 1})
    with pytest.raises(asyncpg.RaiseError):
        await h.pool.execute("DELETE FROM memory_skill_imports WHERE id=$1::uuid", imported["import_id"])
    doc, _ = await wiki(h)
    value = await h.call("memory_feedback_record", {"asset_kind": "knowledge", "asset_id": doc["document_id"], "asset_version": 1,
                         "usefulness": "uncertain", "outcome": "not_attempted", "idempotency_key": "one"}, role="writer")
    with pytest.raises(asyncpg.RaiseError):
        await h.pool.execute("UPDATE memory_asset_feedback SET usefulness='helpful' WHERE id=$1::uuid", value["feedback_id"])
