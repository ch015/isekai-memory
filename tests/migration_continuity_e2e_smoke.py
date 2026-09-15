"""Populated 009 -> 010 -> 009 preservation and immutable-history downgrade refusal."""

import asyncio
import json
import os
import subprocess
import sys

from isekai_memory.config import Settings
from isekai_memory.main import ToolDispatcher
from isekai_memory.server.auth import Principal, hash_token
from isekai_memory.store import queries
from isekai_memory.store.database import close_pool, init_pool
from tests.migration_e2e_smoke import empty_database, seed
from tests.test_continuity import captured, policy_body


async def snapshot(settings, *, legacy=False):
    pool = await init_pool(settings)
    try:
        rows = [dict(row) for row in await pool.fetch("SELECT * FROM handoffs ORDER BY id")]
        if legacy:
            for row in rows:
                assert row.pop("continuity_managed", False) is False
        return rows
    finally:
        await close_pool()


async def populate(settings):
    from tests.migration_fixture_compat import pre_event_fixture
    with pre_event_fixture():
        return await _populate(settings)


async def _populate(settings):
    pool = await init_pool(settings)
    try:
        await queries.create_token(token_hash=hash_token("synthetic-continuity-recipient"), project_id="project-1", user_id="receiver", scopes=["read", "write"], expires_at=None)
        dispatcher = ToolDispatcher(settings)
        admin = Principal("owner", "project-1", frozenset({"admin"}))
        body = policy_body(default_recipient_user_ids=["receiver"])
        await dispatcher("memory_continuity_policy_set", {"project_id": "project-1", "policy": body,
            "expected_version": 0, "reason": "migration", "idempotency_key": "policy"}, admin)
        package, data = captured()
        checkpoint = await dispatcher("memory_checkpoint_save", {"project_id": "project-1", "work_id": "work",
            "expected_version": 0, "continuation": package, "snapshot": data, "classification": "internal",
            "lock_snapshot_digest": "sha256:" + "a" * 64, "idempotency_key": "save"}, admin)
        await dispatcher("memory_continuity_publish", {"project_id": "project-1", "source_kind": "checkpoint",
            "source_id": checkpoint["checkpoint_id"], "expected_policy_version": 1, "reason": "recovery", "idempotency_key": "publish"}, admin)
        return await pool.fetchval("SELECT count(*) FROM memory_continuity_events")
    finally:
        await close_pool()


def main():
    settings = Settings(database_url=os.environ["MEMORY_TEST_DATABASE_URL"])
    asyncio.run(empty_database(settings))

    def migrate(action, revision, *, success=True):
        result = subprocess.run([sys.executable, "-m", "alembic", action, revision],
            env={**os.environ, "ISEKAI_MEMORY_DATABASE_URL": settings.database_url}, capture_output=True, text=True, timeout=30)
        assert (result.returncode == 0) == success, result.stderr
        return result

    migrate("upgrade", "009")
    asyncio.run(seed(settings))
    original = asyncio.run(snapshot(settings, legacy=True))
    migrate("upgrade", "head")
    assert asyncio.run(snapshot(settings, legacy=True)) == original
    migrate("downgrade", "009")
    assert asyncio.run(snapshot(settings, legacy=True)) == original
    migrate("upgrade", "head")
    assert asyncio.run(populate(settings)) == 3
    before = asyncio.run(snapshot(settings))
    assert "010 downgrade refused" in migrate("downgrade", "009", success=False).stderr
    assert asyncio.run(snapshot(settings)) == before
    print(json.dumps({"legacy_claim_and_payload_preserved": True, "empty_continuity_downgrade": True, "continuity_history_downgrade_refused": True}))


if __name__ == "__main__":
    main()
