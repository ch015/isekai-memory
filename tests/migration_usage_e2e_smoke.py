"""Populated M8/presence preservation and usage anti-replay downgrade refusal."""
import asyncio
import json
import os
import subprocess
import sys
from uuid import uuid4

from isekai_memory.config import Settings
from isekai_memory.continuity.usage import DEFAULT_POLICY
from isekai_memory.main import ToolDispatcher
from isekai_memory.server.auth import Principal
from isekai_memory.store.database import close_pool, init_pool
from tests.migration_continuity_e2e_smoke import populate
from tests.migration_e2e_smoke import empty_database
from tests.migration_presence_e2e_smoke import observe, snapshot


async def usage_data(settings):
    from tests.migration_fixture_compat import pre_event_fixture
    with pre_event_fixture():
        return await _usage_data(settings)


async def _usage_data(settings):
    await init_pool(settings)
    try:
        dispatcher = ToolDispatcher(settings)
        principal = Principal("owner", "project-1", frozenset({"admin"}))
        await dispatcher("memory_usage_policy_set", {"project_id": "project-1", "policy": {**DEFAULT_POLICY, "enabled": True},
                         "expected_version": 0, "idempotency_key": "usage-policy", "reason": "migration fixture"}, principal)
        await dispatcher("memory_usage_register", {"project_id": "project-1", "execution_attempt_id": str(uuid4()),
            "meter_epoch": str(uuid4()), "session_token": "a"*32, "host_kind": "unknown", "host_version": "unknown",
            "adapter_version": "synthetic", "provider": "unknown", "model_id": "unknown", "classification": "internal",
            "observation_scope": "exclusive_run", "parent_session_id": None, "work_binding": None}, principal)
    finally:
        await close_pool()


async def current_usage(settings):
    pool = await init_pool(settings)
    try:
        return {table: await pool.fetchval(f"SELECT jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text) FROM {table} t")
                for table in ("memory_usage_policies", "memory_usage_sessions", "memory_usage_receipts")}
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

    migrate("upgrade", "011")
    asyncio.run(populate(settings))
    asyncio.run(observe(settings))
    before = asyncio.run(snapshot(settings, presence=True))
    migrate("upgrade", "012")
    assert asyncio.run(snapshot(settings, presence=True)) == before
    migrate("downgrade", "011")
    assert asyncio.run(snapshot(settings, presence=True)) == before
    migrate("upgrade", "012")
    asyncio.run(usage_data(settings))
    old = asyncio.run(snapshot(settings, presence=True))
    usage = asyncio.run(current_usage(settings))
    assert "012 downgrade refused" in migrate("downgrade", "011", success=False).stderr
    assert asyncio.run(current_usage(settings)) == usage
    assert asyncio.run(snapshot(settings, presence=True)) == old
    print(json.dumps({"m8_presence_preserved": True, "empty_usage_downgrade": True,
                      "usage_ownership_history_downgrade_refused": True}))


if __name__ == "__main__":
    main()
