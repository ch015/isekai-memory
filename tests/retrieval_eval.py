"""Repeatable synthetic relevance/latency evaluation on an explicit test database.

Run MEMORY_TEST_DATABASE_URL=... python -m tests.retrieval_eval. Creates unique
projects only; does not migrate, truncate, delete or contact an embedding service.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import time
from pathlib import Path
from uuid import uuid4

from isekai_memory.config import Settings
from isekai_memory.main import dispatch_tool
from isekai_memory.registry.verification import canonical_bytes, digest_bytes
from isekai_memory.retrieval.citations import canonical, digest
from isekai_memory.retrieval.service import search
from isekai_memory.store.database import close_pool, health_check, init_pool
from tests.helpers import handoff_arguments

FIXTURE = Path(__file__).parent / "fixtures" / "retrieval_v1.json"
LOCK = "sha256:" + "2" * 64


def metrics(ranked: list[str], relevance: dict[str, int], k: int) -> dict:
    relevant = {key for key, grade in relevance.items() if grade > 0}
    selected = list(dict.fromkeys(ranked))[:k]
    dcg = sum((2 ** relevance.get(key, 0) - 1) / math.log2(rank + 2) for rank, key in enumerate(selected))
    ideal = sum(
        (2**grade - 1) / math.log2(rank + 2) for rank, grade in enumerate(sorted(relevance.values(), reverse=True)[:k])
    )
    return {
        "recall_at_k": len(set(selected) & relevant) / len(relevant) if relevant else None,
        "ndcg_at_k": dcg / ideal if ideal else None,
        "mrr": next((1 / (rank + 1) for rank, key in enumerate(selected) if key in relevant), 0) if relevant else None,
        "empty_correct": not selected if not relevant else None,
    }


async def seed(pool, fixture):
    project = "retrieval-eval-" + uuid4().hex
    identities = {}
    sources = {}
    for document in fixture["documents"]:
        scope = project + ("-other" if document.get("project") == "other" else "")
        classification = document.get("classification", "internal")
        lock = "sha256:" + "9" * 64 if document.get("lock") == "other" else LOCK
        source_key = (scope, classification, lock)
        if source_key not in sources:
            source_args = handoff_arguments()
            attempt = uuid4().hex
            source_args.update(
                project_id=scope, phase_attempt_id=attempt, classification=classification, lock_snapshot_digest=lock
            )
            for field in ("task_envelope", "result_envelope"):
                source_args[field]["phase_attempt_id"] = attempt
            source_args["task_envelope"]["lock_snapshot_digest"] = lock
            source_args["envelope_digest"] = digest_bytes(
                canonical_bytes(source_args["task_envelope"]) + canonical_bytes(source_args["result_envelope"])
            )
            sources[source_key] = (await dispatch_tool("memory_handoff_push", source_args))["handoff_id"]
        args = {
            "project_id": scope,
            "source_handoff_id": sources[source_key],
            "idempotency_key": document["id"],
            "kind": document.get("kind", "fact"),
            "title": document["title"],
            "content": document["content"],
            "tags": document.get("tags", []),
        }
        memory_id = (await dispatch_tool("memory_experience_propose", args))["memory_id"]
        identities[memory_id] = document["id"]
        state = document.get("state", "active")
        review = {"project_id": scope, "memory_id": memory_id, "expected_version": 1}
        if state == "pending":
            continue
        await dispatch_tool(
            "memory_experience_review", {**review, "action": "reject" if state == "rejected" else "approve"}
        )
        if state in {"archived", "forgotten"}:
            await dispatch_tool(
                "memory_experience_review",
                {**review, "action": "archive" if state == "archived" else "forget", "expected_version": 2},
            )
        if state in {"expired", "future"}:
            async with pool.acquire() as conn:
                update = (
                    "expires_at=now()-interval '1 day'" if state == "expired" else "valid_from=now()+interval '1 day'"
                )
                await conn.execute("UPDATE memory_experiences SET " + update + " WHERE id=$1::uuid", memory_id)
        if state == "superseded":
            child = await dispatch_tool(
                "memory_experience_revise",
                {
                    **{key: value for key, value in args.items() if key != "source_handoff_id"},
                    "memory_id": memory_id,
                    "expected_version": 2,
                    "idempotency_key": "replacement",
                    "title": "Unrelated replacement",
                    "content": "Revised unrelated context.",
                },
            )
            identities[child["memory_id"]] = "replacement"
            await dispatch_tool(
                "memory_experience_review", {**review, "memory_id": child["memory_id"], "action": "approve"}
            )
    return project, identities


async def evaluate(pool, *, repeats=3):
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    project, identities = await seed(pool, fixture)
    report = {
        "dataset": fixture["version"],
        "dataset_digest": digest(canonical(fixture)),
        "judgments": fixture["judgments"],
        "documents": len(identities),
        "queries": len(fixture["queries"]),
        "k": 3,
        "repeats": repeats,
        "strategies": {},
    }
    async with pool.acquire() as conn:
        before = [
            dict(row) for row in await conn.fetch("SELECT * FROM handoffs WHERE project_id=$1 ORDER BY id", project)
        ]
    for strategy in ("postgres_lexical", "postgres_weighted_lexical"):
        cases, durations, sizes = [], [], []
        for case in fixture["queries"]:
            args = {
                "project_id": project,
                "query": case["query"],
                "source_lock_digest": LOCK,
                "limit": 3,
                "max_chars": 16000,
            }
            args.update({key: case[key] for key in ("kind", "max_classification") if key in case})
            forbidden = {
                doc["id"]
                for doc in fixture["documents"]
                if (
                    doc.get("state", "active") != "active"
                    or doc.get("project") == "other"
                    or doc.get("lock") == "other"
                    or (doc.get("classification") == "restricted" and args.get("max_classification") != "restricted")
                    or ("kind" in args and doc.get("kind", "fact") != args["kind"])
                )
            }
            for _ in range(repeats):
                started = time.perf_counter()
                result = await search(args, strategy=strategy)
                durations.append((time.perf_counter() - started) * 1000)
                sizes.append(result["result_chars"])
                ranked = [identities[item["memory_id"]] for item in result["items"]]
                assert not set(ranked) & forbidden, "Visibility must be applied before top-K"
                assert result["result_chars"] == len(canonical(result["items"])) <= args["max_chars"]
            cases.append(
                {
                    "id": case["id"],
                    "language": case["language"],
                    "ranked": ranked,
                    **metrics(ranked, case["relevance"], 3),
                }
            )
        averages = {
            name: sum(case[name] for case in cases if case[name] is not None)
            / sum(case[name] is not None for case in cases)
            for name in ("recall_at_k", "ndcg_at_k", "mrr", "empty_correct")
        }
        report["strategies"][strategy] = {
            **averages,
            "p95_ms": sorted(durations)[math.ceil(0.95 * len(durations)) - 1],
            "max_result_chars": max(sizes),
            "forbidden_hits": 0,
            "cases": cases,
        }
    async with pool.acquire() as conn:
        assert [
            dict(row) for row in await conn.fetch("SELECT * FROM handoffs WHERE project_id=$1 ORDER BY id", project)
        ] == before
    report["handoff_unchanged"] = True
    return report


async def main():
    dsn = os.environ.get("MEMORY_TEST_DATABASE_URL")
    if not dsn:
        raise SystemExit("MEMORY_TEST_DATABASE_URL must explicitly select a disposable migrated database")
    pool = await init_pool(Settings(database_url=dsn))
    try:
        await health_check()
        print(json.dumps(await evaluate(pool), ensure_ascii=False, indent=2))
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
