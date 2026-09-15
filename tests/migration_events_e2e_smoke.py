"""Populated 012 preservation, empty 013 rollback, stable cursor key and history-aware refusal."""
import asyncio
import json
import os
import subprocess
import sys
from uuid import uuid4

from isekai_memory.config import Settings
from isekai_memory.main import ToolDispatcher
from isekai_memory.server.auth import Principal
from isekai_memory.store.database import close_pool, health_check, init_pool
from tests.migration_continuity_e2e_smoke import populate
from tests.migration_e2e_smoke import empty_database
from tests.migration_presence_e2e_smoke import observe, snapshot
from tests.migration_usage_e2e_smoke import current_usage, usage_data


async def create_event(settings):
    await init_pool(settings)
    try:
        dispatcher = ToolDispatcher(settings)
        principal = Principal("owner", "project-1", frozenset({"admin"}))
        policy = await dispatcher("memory_continuity_policy_get", {"project_id": "project-1"}, principal)
        await dispatcher("memory_continuity_policy_set", {"project_id": "project-1", "policy": policy["policy"],
                         "expected_version": policy["version"], "idempotency_key": uuid4().hex, "reason": "migration feed fixture"}, principal)
    finally:
        await close_pool()


async def current(settings):
    pool = await init_pool(settings)
    try:
        assert (await health_check())["schema_revision"] == "013"
        return {table: await pool.fetchval(f"SELECT jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text) FROM {table} t")
                for table in ("memory_event_cursor_key", "memory_event_heads", "memory_collaboration_events")}
    finally:
        await close_pool()


def main():
    settings = Settings(database_url=os.environ["MEMORY_TEST_DATABASE_URL"])
    asyncio.run(empty_database(settings))
    def migrate(action, target, success=True):
        result = subprocess.run([sys.executable, "-m", "alembic", action, target],
            env={**os.environ, "ISEKAI_MEMORY_DATABASE_URL": settings.database_url}, capture_output=True, text=True, timeout=30)
        assert (result.returncode == 0) == success, result.stderr
        return result
    migrate("upgrade", "012")
    asyncio.run(populate(settings))
    asyncio.run(observe(settings))
    asyncio.run(usage_data(settings))
    old = asyncio.run(snapshot(settings, presence=True))
    usage = asyncio.run(current_usage(settings))
    migrate("upgrade", "013")
    assert asyncio.run(snapshot(settings, presence=True)) == old and asyncio.run(current_usage(settings)) == usage
    migrate("downgrade", "012")
    assert asyncio.run(snapshot(settings, presence=True)) == old and asyncio.run(current_usage(settings)) == usage
    migrate("upgrade", "013")
    asyncio.run(create_event(settings))
    data = asyncio.run(current(settings))
    migrate("upgrade", "head")
    assert asyncio.run(current(settings)) == data
    assert "013 downgrade refused" in migrate("downgrade", "012", success=False).stderr
    assert asyncio.run(current(settings)) == data
    assert asyncio.run(current_usage(settings)) == usage
    print(json.dumps({"schema_013_populated_012_preserved": True, "empty_events_rollback": True,
                      "cursor_key_stable": True, "event_history_downgrade_refused": True}))


if __name__ == "__main__":
    main()
