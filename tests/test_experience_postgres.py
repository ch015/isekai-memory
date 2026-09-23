"""Authenticated API integration against a disposable, migrated PostgreSQL DB.

Set MEMORY_TEST_DATABASE_URL explicitly. Tests create unique project IDs; they
never migrate, truncate or delete an existing database. Run Alembic beforehand.
"""

from __future__ import annotations

import asyncio
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import asyncpg
import httpx
import pytest
import pytest_asyncio

from isekai_memory.config import Settings
from isekai_memory.main import ToolDispatcher
from isekai_memory.registry.verification import canonical_bytes, digest_bytes
from isekai_memory.server.auth import hash_token
from isekai_memory.server.http_handler import create_app
from isekai_memory.server.protocol import PROTOCOL_VERSION
from isekai_memory.store import queries
from isekai_memory.store.database import EXPECTED_SCHEMA_REVISION, close_pool, health_check, init_pool
from tests.helpers import handoff_arguments

pytestmark = pytest.mark.skipif(not os.environ.get("MEMORY_TEST_DATABASE_URL"), reason="requires disposable PostgreSQL")


@dataclass
class Harness:
    client: httpx.AsyncClient
    pool: asyncpg.Pool
    project: str
    tokens: dict[str, str]

    async def call(self, name, arguments, *, role="admin", ok=True):
        response = await self.client.post(
            "/mcp",
            headers={
                "Authorization": "Bearer " + self.tokens[role],
                "MCP-Protocol-Version": PROTOCOL_VERSION, "Mcp-Method": "tools/call", "Mcp-Name": name,
            },
            json={
                "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {
                    "name": name, "arguments": {"project_id": self.project, **arguments},
                    "_meta": {
                        "io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION,
                        "io.modelcontextprotocol/clientCapabilities": {},
                    },
                },
            },
        )
        assert response.status_code == 200, response.text
        result = response.json()["result"]
        assert result["isError"] is not ok, result
        return result["structuredContent"]

    async def source(self, classification="internal"):
        args = handoff_arguments()
        args["project_id"] = self.project
        attempt = "attempt-" + uuid4().hex
        args["phase_attempt_id"] = attempt
        args["task_envelope"]["phase_attempt_id"] = attempt
        args["result_envelope"]["phase_attempt_id"] = attempt
        args["envelope_digest"] = digest_bytes(canonical_bytes(args["task_envelope"]) + canonical_bytes(args["result_envelope"]))
        args["classification"] = classification
        return await self.call("memory_handoff_push", args, role="writer")

    async def propose(self, source_id=None, **kwargs):
        if source_id is None:
            source_id = (await self.source())["handoff_id"]
        args = {
            "source_handoff_id": source_id, "idempotency_key": uuid4().hex,
            "kind": "decision", "title": "인증 모듈 결정", "content": "Keep lease receipts for 인증 모듈 재시도.",
            **kwargs,
        }
        return await self.call("memory_experience_propose", args, role="writer"), args

    async def approve(self, memory_id):
        return await self.call("memory_experience_review", {"memory_id": memory_id, "action": "approve", "expected_version": 1})


@pytest_asyncio.fixture
async def harness():
    settings = Settings(database_url=os.environ["MEMORY_TEST_DATABASE_URL"], db_pool_min=1, db_pool_max=6)
    pool = await init_pool(settings)
    try:
        assert (await health_check())["schema_revision"] == EXPECTED_SCHEMA_REVISION
        project = "experience-test-" + uuid4().hex
        tokens = {}
        for role, scopes in {"admin": ["admin"], "admin2": ["admin"], "writer": ["read", "write"], "read": ["read"], "other": ["admin"]}.items():
            tokens[role] = secrets.token_urlsafe(32)
            await queries.create_token(
                token_hash=hash_token(tokens[role]), project_id=project + "-other" if role == "other" else project,
                user_id=role, scopes=scopes, expires_at=None,
            )
        app = create_app(settings, ToolDispatcher(settings))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://memory-test") as client:
            yield Harness(client, pool, project, tokens)
    finally:
        await close_pool()


async def test_authenticated_round_trip_preserves_handoff_and_review_receipts(harness):
    h = harness
    source = await h.source()
    proposed, args = await h.propose(source["handoff_id"])
    memory_id = proposed["memory_id"]
    query = {"query": "인증 모듈"}
    assert (await h.call("memory_search", query, role="read"))["items"] == []
    await h.call("memory_read", {"memory_id": memory_id}, role="read", ok=False)
    queue = await h.call("memory_experience_list", {})
    assert queue["items"][0]["memory_id"] == memory_id
    assert queue["items"][0]["created_by"] == "writer"
    await h.call("memory_experience_list", {}, role="writer", ok=False)
    await h.call("memory_experience_review", {"memory_id": memory_id, "action": "approve", "expected_version": 1}, role="writer", ok=False)
    await h.approve(memory_id)
    for _ in range(2):
        found = await h.call("memory_search", query, role="read")
        assert [row["memory_id"] for row in found["items"]] == [memory_id]
        read = await h.call("memory_read", {"memory_id": memory_id}, role="read")
        assert read["memory"]["source"]["id"] == source["handoff_id"]
        assert read["memory"]["classification"] == "internal"
        assert read["usage"] == "reference_only"
    pending = await h.call("memory_handoff_list", {})
    assert [row["id"] for row in pending] == [source["handoff_id"]]
    claim_args = {"handoff_id": source["handoff_id"], "claim_token": secrets.token_urlsafe(32)}
    claim = await h.call("memory_handoff_claim", claim_args, role="writer")
    assert (await h.call("memory_handoff_get_claimed", claim_args, role="writer"))["envelope_digest"] == claim["envelope_digest"]
    ack_args = {**claim_args, "claim_generation": claim["claim_generation"]}
    await h.call("memory_handoff_ack", ack_args, role="writer")
    await h.call("memory_handoff_ack", ack_args, role="writer")
    await h.call("memory_read", {"memory_id": memory_id}, role="read")
    # An acknowledged handoff is still a retained source for another experience.
    await h.propose(source["handoff_id"], kind="lesson")
    await h.call("memory_experience_review", {"memory_id": memory_id, "action": "archive", "expected_version": 2})
    replay = await h.approve(memory_id)
    assert replay == {"memory_id": memory_id, "applied_status": "active", "applied_version": 2, "already_applied": True}
    assert (await h.call("memory_search", query))["items"] == []
    await h.call("memory_read", {"memory_id": memory_id}, ok=False)
    assert (await h.call("memory_experience_list", {"status": "archived"}))["items"][0]["version"] == 3
    # Idempotent proposal retries must not reactivate retired memory.
    assert (await h.call("memory_experience_propose", args, role="writer"))["already_exists"]


async def test_concurrent_proposals_and_conflicting_idempotency_key(harness):
    h = harness
    source = await h.source()
    first, args = await h.propose(source["handoff_id"])
    args["idempotency_key"] = uuid4().hex
    results = await asyncio.gather(*[h.call("memory_experience_propose", args, role="writer") for _ in range(6)])
    assert len({result["memory_id"] for result in results}) == 1
    assert sum(not result["already_exists"] for result in results) == 1
    conflict = await h.call("memory_experience_propose", {**args, "content": "Different decision"}, role="writer", ok=False)
    assert conflict["error"]["error_code"] == "MEM-EXPERIENCE-0002"
    own = await h.call("memory_experience_propose", args, role="admin")
    assert own["memory_id"] not in {first["memory_id"], results[0]["memory_id"]}


async def test_concurrent_review_has_one_winner_and_actor_bound_replay(harness):
    h = harness
    memory_id = (await h.propose())[0]["memory_id"]

    async def transition(action):
        response = await h.client.post(
            "/tools/memory_experience_review", headers={"Authorization": "Bearer " + h.tokens["admin"]},
            json={"project_id": h.project, "memory_id": memory_id, "action": action, "expected_version": 1},
        )
        return action, response.status_code

    results = await asyncio.gather(transition("approve"), transition("reject"))
    assert sorted(status for _, status in results) == [200, 409]
    winner = next(action for action, status in results if status == 200)
    args = {"memory_id": memory_id, "action": winner, "expected_version": 1}
    assert (await h.call("memory_experience_review", args))["already_applied"]
    other_actor = await h.call("memory_experience_review", args, role="admin2", ok=False)
    assert other_actor["error"]["error_code"] == "MEM-EXPERIENCE-0003"
    async with h.pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM memory_experience_events WHERE memory_id=$1::uuid", memory_id) == 1


async def test_cross_project_source_read_search_and_foreign_key(harness):
    h = harness
    proposal, args = await h.propose()
    memory_id = proposal["memory_id"]
    await h.approve(memory_id)
    for name, arguments in [
        ("memory_search", {"query": "인증"}), ("memory_read", {"memory_id": memory_id}),
        ("memory_experience_list", {}), ("memory_experience_propose", args),
        ("memory_experience_review", {"memory_id": memory_id, "action": "archive", "expected_version": 2}),
    ]:
        denied = await h.call(name, arguments, role="other", ok=False)
        assert denied["error"]["error_code"] == "MEM-AUTH-0003"
    other_project = {"project_id": h.project + "-other"}
    assert (await h.call("memory_search", {**other_project, "query": "인증"}, role="other"))["items"] == []
    await h.call("memory_read", {**other_project, "memory_id": memory_id}, role="other", ok=False)
    missing_source = await h.call("memory_experience_propose", {**args, **other_project}, role="other", ok=False)
    assert missing_source["error"]["error_code"] == "MEM-EXPERIENCE-0001"
    async with h.pool.acquire() as conn:
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            async with conn.transaction():
                await conn.execute("UPDATE memory_experiences SET project_id=$2 WHERE id=$1::uuid", memory_id, h.project + "-other")


async def test_filters_apply_before_top_k_and_korean_substring_recall(harness):
    h = harness
    restricted = (await h.propose((await h.source("restricted"))["handoff_id"], title="인증 모듈", content="인증 모듈"))[0]["memory_id"]
    public = (await h.propose((await h.source("public"))["handoff_id"], title="인증 모듈의 재시도 정책"))[0]["memory_id"]
    await h.approve(restricted)
    await h.approve(public)
    query = {"query": "인증 모듈", "limit": 1, "max_classification": "public"}
    found = await h.call("memory_search", query)
    assert [item["memory_id"] for item in found["items"]] == [public]
    await h.call("memory_read", {"memory_id": restricted}, ok=False)
    await h.call("memory_read", {"memory_id": restricted, "max_classification": "restricted"})
    assert (await h.call("memory_search", {**query, "kind": "procedure"}))["items"] == []
    wrong_lock = "sha256:" + "a" * 64
    assert (await h.call("memory_search", {**query, "source_lock_digest": wrong_lock}))["items"] == []
    await h.call("memory_read", {"memory_id": public, "source_lock_digest": wrong_lock}, ok=False)
    assert (await h.call("memory_search", {"query": "' OR 1=1 --"}))["items"] == []


async def test_expiry_hides_active_memory_blocks_approval_and_allows_receipt_retry(harness):
    h = harness
    expires = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    pending, _ = await h.propose(expires_at=expires)
    active, args = await h.propose(expires_at=expires)
    await h.approve(active["memory_id"])
    async with h.pool.acquire() as conn:
        await conn.execute("UPDATE memory_experiences SET expires_at=now()-interval '1 second' WHERE project_id=$1", h.project)
    await h.call("memory_experience_review", {"memory_id": pending["memory_id"], "action": "approve", "expected_version": 1}, ok=False)
    assert (await h.call("memory_search", {"query": "인증"}))["items"] == []
    await h.call("memory_read", {"memory_id": active["memory_id"]}, ok=False)
    assert (await h.call("memory_experience_list", {}))["items"][0]["expired"]
    assert (await h.call("memory_experience_propose", args, role="writer"))["already_exists"]
    expired_new = {**args, "idempotency_key": uuid4().hex, "expires_at": "2020-01-01T00:00:00Z"}
    await h.call("memory_experience_propose", expired_new, role="writer", ok=False)


async def test_approval_checks_expiry_after_waiting_for_row_lock(harness):
    h = harness
    memory_id = (await h.propose())[0]["memory_id"]
    async with h.pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT id FROM memory_experiences WHERE id=$1::uuid FOR UPDATE", memory_id)
            waiting = asyncio.create_task(h.call("memory_experience_review", {"memory_id": memory_id, "action": "approve", "expected_version": 1}, ok=False))
            async with asyncio.timeout(3):
                while True:
                    await conn.execute("SELECT pg_stat_clear_snapshot()")
                    if await conn.fetchval(
                        "SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE datname=current_database() "
                        "AND wait_event_type='Lock' AND query LIKE '%memory_experiences%')"
                    ):
                        break
                    await asyncio.sleep(0.01)
            await conn.execute("UPDATE memory_experiences SET expires_at=clock_timestamp()-interval '1 second' WHERE id=$1::uuid", memory_id)
        result = await waiting
    assert result["error"]["error_code"] == "MEM-EXPERIENCE-0004"


async def test_review_pagination_and_search_budget(harness):
    h = harness
    source = (await h.source())["handoff_id"]
    for _ in range(5):
        memory_id = (await h.propose(source, content="budget memory " * 50))[0]["memory_id"]
        await h.approve(memory_id)
    first = await h.call("memory_experience_list", {"status": "active", "limit": 2})
    second = await h.call("memory_experience_list", {"status": "active", "limit": 2, "offset": first["next_offset"]})
    assert {item["memory_id"] for item in first["items"]}.isdisjoint(item["memory_id"] for item in second["items"])
    found = await h.call("memory_search", {"query": "budget", "max_chars": 1000})
    assert found["truncated"] and found["result_chars"] <= 1000
    assert found["returned"] >= 1


async def test_handoff_nack_expired_reclaim_and_generation_fencing(harness):
    h = harness
    handoff_id = (await h.source())["handoff_id"]
    first_args = {"handoff_id": handoff_id, "claim_token": secrets.token_urlsafe(32)}
    first = await h.call("memory_handoff_claim", first_args)
    async with h.pool.acquire() as conn:
        await conn.execute("UPDATE handoffs SET claim_lease_expires_at=now()-interval '1 second' WHERE id=$1::uuid", handoff_id)
    second_args = {"handoff_id": handoff_id, "claim_token": secrets.token_urlsafe(32)}
    second = await h.call("memory_handoff_claim", second_args)
    assert second["claim_generation"] > first["claim_generation"]
    await h.call("memory_handoff_ack", {**first_args, "claim_generation": first["claim_generation"]}, ok=False)
    nack = {**second_args, "claim_generation": second["claim_generation"], "reason_code": "retryable"}
    await h.call("memory_handoff_nack", nack)
    await h.call("memory_handoff_nack", nack)
    assert [item["id"] for item in await h.call("memory_handoff_list", {})] == [handoff_id]
