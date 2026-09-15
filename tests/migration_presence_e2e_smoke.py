"""Populated M8 preservation and presence anti-replay downgrade protection."""

import asyncio
import json
import os
import subprocess
import sys
from uuid import uuid4

from isekai_memory.config import Settings
from isekai_memory.continuity.presence import DEFAULT_POLICY
from isekai_memory.main import ToolDispatcher
from isekai_memory.server.auth import Principal
from isekai_memory.store.database import close_pool, init_pool
from tests.migration_continuity_e2e_smoke import populate
from tests.migration_e2e_smoke import empty_database


async def snapshot(settings, *, presence=False):
    pool = await init_pool(settings)
    try:
        tables = ["memory_continuity_policies", "memory_checkpoints", "memory_continuity_bundles",
                  "memory_continuity_deliveries", "memory_continuity_units", "memory_continuity_receipts",
                  "memory_continuity_claims", "memory_continuity_events"]
        if presence:
            tables.extend(["memory_presence_policies", "memory_presence_sessions"])
        return {table: await pool.fetchval(f"SELECT jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text) FROM {table} t") for table in tables}
    finally:
        await close_pool()


async def observe(settings):
    from tests.migration_fixture_compat import pre_event_fixture
    with pre_event_fixture():
        return await _observe(settings)


async def _observe(settings):
    await init_pool(settings)
    try:
        dispatcher = ToolDispatcher(settings)
        principal = Principal("owner", "project-1", frozenset({"admin"}))
        await dispatcher("memory_presence_policy_set", {"project_id": "project-1", "policy": {**DEFAULT_POLICY, "enabled": True},
                         "expected_version": 0, "idempotency_key": "presence", "reason": "migration fixture"}, principal)
        registered = await dispatcher("memory_presence_register",
            {"project_id": "project-1", "client_instance_id": str(uuid4()), "session_token": "a"*32,
             "host_kind": "unknown", "session_kind": "worker", "classification": "internal"}, principal)
        await dispatcher("memory_presence_end", {"project_id": "project-1", "session_id": registered["session_id"],
                         "session_token": "a"*32, "sequence": 1}, principal)
    finally:
        await close_pool()


def main():
    settings = Settings(database_url=os.environ["MEMORY_TEST_DATABASE_URL"])
    asyncio.run(empty_database(settings))

    def migrate(action, revision, success=True):
        result = subprocess.run([sys.executable, "-m", "alembic", action, revision],
            env={**os.environ, "ISEKAI_MEMORY_DATABASE_URL": settings.database_url}, capture_output=True, text=True, timeout=30)
        assert (result.returncode == 0) == success, result.stderr
        return result

    migrate("upgrade", "010")
    asyncio.run(populate(settings))
    original = asyncio.run(snapshot(settings))
    migrate("upgrade", "head")
    assert asyncio.run(snapshot(settings)) == original
    migrate("downgrade", "010")
    assert asyncio.run(snapshot(settings)) == original
    migrate("upgrade", "head")
    asyncio.run(observe(settings))
    before = asyncio.run(snapshot(settings, presence=True))
    assert "011 downgrade refused" in migrate("downgrade", "010", success=False).stderr
    assert asyncio.run(snapshot(settings, presence=True)) == before
    print(json.dumps({"m8_rows_preserved": True, "empty_presence_downgrade": True, "observed_history_downgrade_refused": True}))


if __name__ == "__main__":
    main()
