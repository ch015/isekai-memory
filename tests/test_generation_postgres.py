"""Real PostgreSQL queue recovery, governance, provenance and snapshot acceptance."""

import asyncio
import os
from uuid import uuid4

import pytest

from isekai_memory.config import Settings
from isekai_memory.experience import service as experiences
from isekai_memory.generation import queue, worker
from isekai_memory.generation.contracts import RECIPE, Candidate
from isekai_memory.registry.verification import canonical_bytes, digest_bytes
from isekai_memory.store.database import close_pool, init_pool
from tests.helpers import handoff_arguments
from tests.test_experience_postgres import harness as harness  # noqa: F401

pytestmark = pytest.mark.skipif(not os.environ.get("MEMORY_TEST_DATABASE_URL"), reason="requires disposable PostgreSQL")


def settings(**overrides):
    return Settings(generation_enabled=True, **overrides)


async def source(h, summary="Recorded result", *, classification="internal", phase="implement"):
    args = handoff_arguments()
    args.update(project_id=h.project, classification=classification, phase_id=phase, phase_attempt_id=uuid4().hex)
    args["task_envelope"]["phase_attempt_id"] = args["phase_attempt_id"]
    args["result_envelope"]["phase_attempt_id"] = args["phase_attempt_id"]
    args["result_envelope"]["summary"] = summary
    args["envelope_digest"] = digest_bytes(canonical_bytes(args["task_envelope"]) + canonical_bytes(args["result_envelope"]))
    return (await h.call("memory_handoff_push", args, role="writer"))["handoff_id"]


async def enqueue(h, **args):
    return await h.call("memory_generation_enqueue", {"kind": "extract", **args})


async def jobrow(h, job_id):
    return dict(await h.pool.fetchrow("SELECT * FROM memory_generation_jobs WHERE id=$1::uuid", job_id))


async def expire(h, job):
    await h.pool.execute("UPDATE memory_generation_jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE id=$1", job["id"])


async def snapshot(h, **view):
    result = await enqueue(h, kind="summary", **view)
    await worker.run(settings(), project_id=h.project)
    return result, await h.call("memory_summary_read", view, role="read")


async def test_extraction_is_pending_atomic_and_independent_of_handoff_delivery(harness):
    h = harness
    source_id = await source(h)
    before = dict(await h.pool.fetchrow("SELECT * FROM handoffs WHERE id=$1::uuid", source_id))
    enqueued = await enqueue(h)
    assert not enqueued["has_more"] and len(enqueued["jobs"]) == 1
    result = await worker.run(settings(), project_id=h.project)
    item = result["results"][0]
    assert item["status"] == "succeeded" and item["code"] == "proposed" and result["cost_microusd"] == 0
    assert (await h.call("memory_search", {"query": "Recorded"}, role="read"))["items"] == []
    pending = (await h.call("memory_experience_list", {}))["items"][0]
    assert pending["memory_id"] == item["memory_id"] and pending["created_by"] == "generation:" + item["job_id"]
    assert pending["content"] == "Recorded result"
    await h.approve(item["memory_id"])
    _, summary = await snapshot(h, phase_id="implement")
    assert summary["status"] == "ready" and summary["items"][0]["memory_id"] == item["memory_id"]
    assert summary["items"][0]["citation"]["schema_version"] == 1
    assert dict(await h.pool.fetchrow("SELECT * FROM handoffs WHERE id=$1::uuid", source_id)) == before
    assert await enqueue(h) == {"jobs": [], "has_more": False, "coverage": "durable_source_receipts"}
    assert (await worker.run(settings(), project_id=h.project))["processed"] == 0
    row = await jobrow(h, item["job_id"])
    assert row["enqueued_by"] == "admin" and row["recipe"] == RECIPE
    attempt = await h.pool.fetchrow("SELECT * FROM memory_generation_attempts WHERE job_id=$1", row["id"])
    assert attempt["cost_microusd"] == 0 and attempt["input_chars"] > 0 and attempt["finished_at"]


async def test_receipt_scan_is_concurrent_idempotent_and_covers_late_old_sources(harness):
    h = harness
    for _ in range(3):
        await source(h)
    batches = await asyncio.gather(enqueue(h, limit=1), enqueue(h, limit=1), enqueue(h, limit=1))
    assert len({b["jobs"][0]["job_id"] for b in batches}) == 3
    assert sum(b["has_more"] for b in batches) == 2
    late = await source(h)
    await h.pool.execute("UPDATE handoffs SET created_at='2000-01-01' WHERE id=$1::uuid", late)
    batch = await enqueue(h)
    assert len(batch["jobs"]) == 1
    assert (await jobrow(h, batch["jobs"][0]["job_id"]))["source_key"] == late


async def test_leased_job_survives_connection_restart_and_stale_worker_cannot_commit(harness):
    h = harness
    await source(h)
    await enqueue(h)
    first = await queue.claim(h.project, lease_seconds=60)
    assert await queue.claim(h.project, lease_seconds=60) is None
    await expire(h, first)
    await close_pool()
    h.pool = await init_pool(Settings(database_url=os.environ["MEMORY_TEST_DATABASE_URL"], db_pool_min=1, db_pool_max=6))
    second = await queue.claim(h.project, lease_seconds=60)
    assert second["id"] == first["id"] and second["attempts"] == 2 and second["lease_token"] != first["lease_token"]
    assert not await queue.fail(first, "old_failure", retryable=False)
    stale = await worker.process(first, settings())
    assert stale["status"] == "lease_lost"
    assert await h.pool.fetchval("SELECT count(*) FROM memory_experiences WHERE project_id=$1", h.project) == 0
    assert (await worker.process(second, settings()))["code"] == "proposed"
    attempts = await h.pool.fetch("SELECT outcome_code FROM memory_generation_attempts WHERE job_id=$1 ORDER BY attempt", first["id"])
    assert [r["outcome_code"] for r in attempts] == ["lease_expired", "proposed"]


async def test_exhausted_crash_leases_become_dead_letters(harness):
    h = harness
    await source(h)
    await enqueue(h)
    for _ in range(3):
        job = await queue.claim(h.project, lease_seconds=60)
        await expire(h, job)
    assert await queue.claim(h.project, lease_seconds=60) is None
    dead = (await h.call("memory_generation_list", {}))["items"][0]
    assert dead["status"] == "dead" and dead["attempts"] == 3 and dead["error_code"] == "lease_expired"
    assert "lease_token" not in dead


async def test_retry_backoff_redrive_fencing_and_receipt_replay(harness):
    h = harness
    await source(h)
    await enqueue(h)
    for attempt in range(3):
        job = await queue.claim(h.project, lease_seconds=60)
        assert job["attempts"] == attempt + 1
        assert await queue.fail(job, "timeout", retryable=True)
        assert await queue.claim(h.project, lease_seconds=60) is None
        await h.pool.execute("UPDATE memory_generation_jobs SET available_at=clock_timestamp() WHERE id=$1", job["id"])
    dead = await jobrow(h, job["id"])
    args = {"job_id": str(job["id"]), "expected_version": dead["version"]}
    receipt = await h.call("memory_generation_retry", args)
    assert not receipt["already_applied"]
    await h.call("memory_generation_retry", args, role="admin2", ok=False)
    assert (await worker.run(settings(), project_id=h.project))["results"][0]["code"] == "proposed"
    assert (await h.call("memory_generation_retry", args))["already_applied"]
    await h.pool.execute("UPDATE memory_generation_jobs SET status='dead',attempts=30,max_attempts=30 WHERE id=$1", job["id"])
    newer = await jobrow(h, job["id"])
    await h.call("memory_generation_retry", {**args, "expected_version": newer["version"]}, ok=False)


async def test_proposal_and_completion_rollback_together(harness, monkeypatch):
    h = harness
    await source(h)
    await enqueue(h)
    original = experiences.propose

    async def crash_after_insert(*args, **kwargs):
        await original(*args, **kwargs)
        raise RuntimeError("simulated crash; must never be persisted")

    monkeypatch.setattr(experiences, "propose", crash_after_insert)
    result = await worker.run(settings(), project_id=h.project)
    assert result["results"][0]["error_code"] == "processing_failed"
    assert await h.pool.fetchval("SELECT count(*) FROM memory_experiences WHERE project_id=$1", h.project) == 0
    monkeypatch.setattr(experiences, "propose", original)
    await h.pool.execute("UPDATE memory_generation_jobs SET available_at=clock_timestamp() WHERE project_id=$1", h.project)
    assert (await worker.run(settings(), project_id=h.project))["results"][0]["code"] == "proposed"


@pytest.mark.parametrize("action", ["reject", "forget", "correction"])
async def test_automatic_generation_respects_source_suppression_and_manual_corrections(harness, action):
    h = harness
    sid = await source(h, "A paraphrase of the rejected claim")
    proposal, _ = await h.propose(sid)
    mid = proposal["memory_id"]
    if action == "correction":
        await h.approve(mid)
        await h.call("memory_experience_revise", {"memory_id": mid, "expected_version": 2,
                     "idempotency_key": uuid4().hex, "kind": "fact", "title": "Correction", "content": "Manual truth"})
    else:
        await h.call("memory_experience_review", {"memory_id": mid, "expected_version": 1, "action": action})
    await enqueue(h)
    result = await worker.run(settings(), project_id=h.project)
    assert result["results"][0]["code"] == "protected_source"
    assert await h.pool.fetchval("SELECT count(*) FROM memory_experiences WHERE project_id=$1 AND created_by LIKE 'generation:%'", h.project) == 0


async def test_same_source_normalized_duplicate_is_not_reproposed(harness):
    h = harness
    sid = await source(h, "Already recorded")
    await h.propose(sid, kind="fact", content="ALREADY    recorded")
    await enqueue(h)
    assert (await worker.run(settings(), project_id=h.project))["results"][0]["code"] == "duplicate"


@pytest.mark.parametrize(("overrides", "code"), [
    ({"generation_max_input_chars": 256}, "input_budget"),
    ({"generation_max_output_chars": 256}, "output_budget"),
])
async def test_generation_input_output_budgets_dead_letter_without_partial_proposal(harness, overrides, code):
    h = harness
    await source(h, "a" * 300)
    await enqueue(h)
    result = await worker.run(settings(**overrides), project_id=h.project)
    assert result["results"][0]["error_code"] == code
    assert (await h.call("memory_generation_list", {}))["items"][0]["status"] == "dead"
    assert (await h.call("memory_experience_list", {}))["items"] == []


async def test_changed_or_deleted_source_does_not_generate(harness):
    h = harness
    sid = await source(h)
    await enqueue(h)
    await h.pool.execute("DELETE FROM handoffs WHERE id=$1::uuid", sid)
    assert (await worker.run(settings(), project_id=h.project))["results"][0]["error_code"] == "source_changed"


async def test_provider_executes_without_transaction_and_invalid_candidate_cannot_activate(harness):
    h = harness
    await source(h)
    await enqueue(h)
    job = await queue.claim(h.project, lease_seconds=60)

    class InvalidProvider:
        recipe = RECIPE

        async def extract(self, source):
            async with h.pool.acquire() as conn, conn.transaction():
                assert await conn.fetchval("SELECT pg_try_advisory_xact_lock(hashtextextended($1,0))", "isekai-experience:" + h.project)
            return Candidate("procedure", "malformed", "\x00invalid")

    assert (await worker.process(job, settings(), provider=InvalidProvider()))["error_code"] == "invalid_candidate"
    assert (await h.call("memory_search", {"query": "invalid"}))["items"] == []


@pytest.mark.parametrize("change", ["archive", "forget", "correction", "expiry", "source_drift", "new_approval"])
async def test_summary_invalidates_on_lifecycle_time_and_source_changes(harness, change):
    h = harness
    proposal, args = await h.propose()
    mid = proposal["memory_id"]
    await h.approve(mid)
    _, before = await snapshot(h)
    assert before["status"] == "ready" and before["source_count"] == 1
    if change in {"archive", "forget"}:
        await h.call("memory_experience_review", {"memory_id": mid, "action": change, "expected_version": 2})
    elif change == "correction":
        correction = await h.call("memory_experience_revise", {"memory_id": mid, "expected_version": 2,
                                 "kind": "lesson", "title": "New", "content": "Corrected", "idempotency_key": uuid4().hex})
        await h.approve(correction["memory_id"])
    elif change == "expiry":
        await h.pool.execute("UPDATE memory_experiences SET expires_at=clock_timestamp()-interval '1 second' WHERE id=$1::uuid", mid)
    elif change == "source_drift":
        await h.pool.execute("UPDATE handoffs SET payload_digest=$2 WHERE id=$1::uuid", args["source_handoff_id"], "sha256:" + "f" * 64)
    else:
        second, _ = await h.propose()
        await h.approve(second["memory_id"])
    after = await h.call("memory_summary_read", {}, role="read")
    assert after["status"] == "stale" and after["items"] == []
    # No source text in snapshots or operational receipts, including after forgetting.
    snapshots = await h.pool.fetch("SELECT dependencies FROM memory_summary_snapshots WHERE project_id=$1", h.project)
    assert all("인증" not in str(row) for row in snapshots)


async def test_summary_scope_classification_budget_and_stale_generation(harness):
    h = harness
    for classification, phase in [("public", "implement"), ("restricted", "implement"), ("public", "review")]:
        sid = await source(h, classification=classification, phase=phase)
        proposal, _ = await h.propose(sid)
        await h.approve(proposal["memory_id"])
    _, summary = await snapshot(h, phase_id="implement", max_classification="public")
    assert summary["source_count"] == 1 and summary["items"][0]["classification"] == "public"
    assert (await h.call("memory_summary_read", {"max_classification": "restricted"}))["status"] == "missing"
    assert (await h.call("memory_summary_read", {"phase_id": "implement", "max_classification": "public", "max_chars": 1000}))["result_chars"] <= 1000
    await h.call("memory_summary_read", {}, role="other", ok=False)
    await enqueue(h, kind="summary")
    job = await queue.claim(h.project, lease_seconds=60)
    another, _ = await h.propose()
    await h.approve(another["memory_id"])
    assert (await worker.process(job, settings()))["error_code"] == "source_changed"


async def test_job_pagination_and_admin_auth(harness):
    h = harness
    for _ in range(3):
        await source(h)
    await enqueue(h)
    first = await h.call("memory_generation_list", {"status": "queued", "limit": 2})
    second = await h.call("memory_generation_list", {"status": "queued", "limit": 2, "cursor": first["next_cursor"]})
    assert len(first["items"]) == 2 and len(second["items"]) == 1
    for name, args in [("memory_generation_list", {}), ("memory_generation_enqueue", {"kind": "extract"})]:
        await h.call(name, args, role="writer", ok=False)
        await h.call(name, args, role="other", ok=False)
    await h.call("memory_generation_list", {"status": "dead", "cursor": first["next_cursor"]}, ok=False)


async def test_timeout_is_retryable_and_no_source_text_is_logged(harness):
    h = harness
    await source(h, "private project content")
    await enqueue(h)
    job = await queue.claim(h.project, lease_seconds=60)

    class SlowProvider:
        recipe = RECIPE

        async def extract(self, source):
            await asyncio.sleep(10)

    result = await worker.process(job, settings(generation_timeout_seconds=1), provider=SlowProvider())
    assert result["error_code"] == "timeout"
    row = await jobrow(h, job["id"])
    assert row["status"] == "queued" and "private project content" not in str(row)


async def test_expiry_during_completion_rolls_back_proposal_before_recovery(harness, monkeypatch):
    h = harness
    await source(h)
    await enqueue(h)
    # Internal helper permits a short lease to exercise the final commit fence.
    job = await queue.claim(h.project, lease_seconds=1)
    original = experiences.propose

    async def delayed_insert(*args, **kwargs):
        result = await original(*args, **kwargs)
        await kwargs["connection"].execute("SELECT pg_sleep(1.1)")
        return result

    monkeypatch.setattr(experiences, "propose", delayed_insert)
    assert (await worker.process(job, settings()))["status"] == "lease_lost"
    assert await h.pool.fetchval("SELECT count(*) FROM memory_experiences WHERE project_id=$1", h.project) == 0
    monkeypatch.setattr(experiences, "propose", original)
    assert (await worker.run(settings(), project_id=h.project))["results"][0]["code"] == "proposed"


async def test_summary_reports_bounded_coverage_and_never_ignores_lock(harness):
    h = harness
    sid = await source(h)
    for index in range(51):
        proposal, _ = await h.propose(sid, content=f"Approved fact {index}")
        await h.approve(proposal["memory_id"])
    _, result = await snapshot(h, source_lock_digest="sha256:" + "2" * 64)
    assert result["source_count"] == 51 and result["truncated"] and result["result_chars"] <= 8000
    stored = await h.pool.fetchval("SELECT dependencies FROM memory_summary_snapshots WHERE project_id=$1", h.project)
    assert len(stored) == 50
    _, wrong_lock = await snapshot(h, source_lock_digest="sha256:" + "9" * 64)
    assert wrong_lock["status"] == "ready" and wrong_lock["source_count"] == 0 and wrong_lock["items"] == []
