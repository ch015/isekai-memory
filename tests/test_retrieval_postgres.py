"""Provider visibility, citation revalidation and shared judged retrieval fixture."""

import os
from uuid import UUID

import pytest

from isekai_memory.retrieval import postgres
from isekai_memory.retrieval.contracts import Candidate, RetrievalRequest
from tests.retrieval_eval import evaluate
from tests.test_experience_postgres import harness as harness

pytestmark = pytest.mark.skipif(not os.environ.get("MEMORY_TEST_DATABASE_URL"), reason="requires disposable PostgreSQL")


async def test_provider_nominations_cannot_inject_retired_text_or_cross_project(harness, monkeypatch):
    h = harness
    active, _ = await h.propose()
    pending, _ = await h.propose()
    await h.approve(active["memory_id"])

    class AdversarialProvider:
        async def candidates(self, conn, request):
            return [Candidate(UUID(pending["memory_id"]), 100), Candidate(UUID(active["memory_id"]), 1)]

    monkeypatch.setitem(postgres._PROVIDERS, "adversarial-test", AdversarialProvider())
    request = RetrievalRequest(h.project, "receipt", ("receipt",), ("public", "internal"), None, None, 3)
    rows = await postgres.fetch_rows(request, "adversarial-test")
    assert [str(row["id"]) for row in rows] == [active["memory_id"]]
    other = RetrievalRequest(h.project + "-other", "receipt", ("receipt",), ("public", "internal"), None, None, 3)
    assert await postgres.fetch_rows(other, "adversarial-test") == []


async def test_search_and_read_citations_match_and_retirement_denies_read(harness):
    h = harness
    proposal, _ = await h.propose()
    memory_id = proposal["memory_id"]
    await h.approve(memory_id)
    found = (await h.call("memory_search", {"query": "인증 모듈"}, role="read"))["items"][0]
    read = (await h.call("memory_read", {"memory_id": memory_id}, role="read"))["memory"]
    assert read["citation"] == found["citation"] and found["project_id"] == h.project
    assert found["source_payload_digest"] == read["source"]["payload_digest"]
    await h.call("memory_experience_review", {"memory_id": memory_id, "action": "archive", "expected_version": 2})
    await h.call("memory_read", {"memory_id": memory_id}, role="read", ok=False)


async def test_judged_retrieval_fixture_has_no_visibility_leaks(harness):
    report = await evaluate(harness.pool, repeats=1)
    baseline = report["strategies"]["postgres_lexical"]
    candidate = report["strategies"]["postgres_weighted_lexical"]
    assert baseline["forbidden_hits"] == candidate["forbidden_hits"] == 0
    assert baseline["recall_at_k"] >= 0.75
    assert candidate["recall_at_k"] >= baseline["recall_at_k"]
    assert candidate["ndcg_at_k"] >= baseline["ndcg_at_k"]
    assert report["handoff_unchanged"]
