"""Populated 005↔006 preserves M2 data; populated M4 rollback is refused atomically."""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from isekai_memory.config import Settings
from isekai_memory.generation import queue, worker
from isekai_memory.main import dispatch_tool
from isekai_memory.store.database import close_pool, health_check, init_pool
from tests.migration_e2e_smoke import empty_database, seed


async def seed_experience(settings, original):
    pool = await init_pool(settings)
    try:
        receipt = await dispatch_tool("memory_experience_propose", {
            "project_id": "project-1", "source_handoff_id": str(original["id"]), "idempotency_key": "pre-m4",
            "kind": "lesson", "title": "Existing experience", "content": "Preserve this receipt across M4 migrations.",
        })
        await dispatch_tool("memory_experience_review", {
            "project_id": "project-1", "memory_id": receipt["memory_id"], "action": "approve", "expected_version": 1,
        })
        return dict(await pool.fetchrow("SELECT * FROM memory_experiences WHERE id=$1::uuid", receipt["memory_id"]))
    finally:
        await close_pool()


async def verify(settings, source, experience, *, generate=False):
    pool = await init_pool(settings)
    try:
        assert dict(await pool.fetchrow("SELECT * FROM handoffs WHERE id=$1", source["id"])) == source
        assert dict(await pool.fetchrow("SELECT * FROM memory_experiences WHERE id=$1", experience["id"])) == experience
        if generate:
            await queue.enqueue({"project_id": "project-1", "kind": "extract"}, actor_id="migration-test", settings=settings)
            await worker.run(settings, project_id="project-1")
            await queue.enqueue({"project_id": "project-1", "kind": "summary"}, actor_id="migration-test", settings=settings)
            await worker.run(settings, project_id="project-1")
        return {
            name: [dict(row) for row in await pool.fetch(f"SELECT * FROM {name} ORDER BY 1")]
            for name in ("memory_generation_jobs", "memory_generation_attempts", "memory_summary_snapshots")
        } if await pool.fetchval("SELECT to_regclass('memory_generation_jobs') IS NOT NULL") else {}
    finally:
        await close_pool()


def main():
    dsn = os.environ.get("MEMORY_TEST_DATABASE_URL")
    if not dsn:
        raise SystemExit("MEMORY_TEST_DATABASE_URL must explicitly select an empty disposable database")
    settings = Settings(database_url=dsn, generation_enabled=True)
    asyncio.run(empty_database(settings))
    environment = {**os.environ, "ISEKAI_MEMORY_DATABASE_URL": dsn}
    root = Path(__file__).resolve().parents[1]

    def migrate(action, revision, *, success=True):
        result = subprocess.run([sys.executable, "-m", "alembic", action, revision], cwd=root, env=environment,
                                capture_output=True, text=True, timeout=30)
        assert (result.returncode == 0) == success, result.stderr
        return result

    migrate("upgrade", "005")
    original = asyncio.run(seed(settings))
    experience = asyncio.run(seed_experience(settings, original))
    migrate("upgrade", "head")
    asyncio.run(verify(settings, original, experience))
    migrate("downgrade", "005")
    asyncio.run(verify(settings, original, experience))
    migrate("upgrade", "head")
    before = asyncio.run(verify(settings, original, experience, generate=True))
    assert "006 downgrade refused" in migrate("downgrade", "005", success=False).stderr
    assert asyncio.run(verify(settings, original, experience)) == before

    async def ready():
        await init_pool(settings)
        try:
            assert (await health_check())["schema_revision"] == "008"
        finally:
            await close_pool()

    asyncio.run(ready())
    print(json.dumps({"populated_005_upgrade": True, "empty_m4_rollback": True, "generation_receipts_preserved_on_refusal": True}))


if __name__ == "__main__":
    main()
