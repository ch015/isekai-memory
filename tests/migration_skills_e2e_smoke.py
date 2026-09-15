"""Populated M4→M5 preservation and transactional Skill rollback refusal."""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from isekai_memory.config import Settings
from isekai_memory.generation.worker import run
from isekai_memory.main import dispatch_tool
from isekai_memory.store.database import close_pool, health_check, init_pool
from tests.migration_e2e_smoke import empty_database, seed
from tests.migration_generation_e2e_smoke import seed_experience, verify


async def skill_snapshot(settings, source, *, create=False):
    pool = await init_pool(settings)
    try:
        if create:
            result = await dispatch_tool("memory_experience_propose", {
                "project_id": "project-1", "source_handoff_id": str(source["id"]), "idempotency_key": "m5-source",
                "kind": "procedure", "title": "Preserve receipts", "content": "Read the original receipt before retrying.",
            })
            await dispatch_tool("memory_experience_review", {"project_id": "project-1", "memory_id": result["memory_id"],
                                "expected_version": 1, "action": "approve"})
            await dispatch_tool("memory_skill_generate", {"project_id": "project-1", "sources": [{"memory_id": result["memory_id"], "version": 2}]}, settings=settings)
            generated = await run(settings, project_id="project-1")
            assert generated["results"][0]["code"] == "skill_proposed"
        assert (await health_check())["schema_revision"] == "013"
        return {name: [dict(row) for row in await pool.fetch(f"SELECT * FROM {name} ORDER BY 1,2")]
                for name in ("memory_skills", "memory_skill_revisions", "memory_skill_sources", "memory_skill_events",
                             "memory_generation_jobs", "memory_generation_attempts", "memory_summary_snapshots")}
    finally:
        await close_pool()


def main():
    dsn = os.environ.get("MEMORY_TEST_DATABASE_URL")
    if not dsn:
        raise SystemExit("MEMORY_TEST_DATABASE_URL must select an empty disposable database")
    settings = Settings(database_url=dsn, generation_enabled=True)
    asyncio.run(empty_database(settings))
    environment = {**os.environ, "ISEKAI_MEMORY_DATABASE_URL": dsn}

    def migrate(action, target, *, success=True):
        result = subprocess.run([sys.executable, "-m", "alembic", action, target], env=environment,
                                cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=30)
        assert (result.returncode == 0) == success, result.stderr
        return result

    migrate("upgrade", "006")
    original = asyncio.run(seed(settings))
    experience = asyncio.run(seed_experience(settings, original))
    before = asyncio.run(verify(settings, original, experience, generate=True))
    migrate("upgrade", "head")
    assert asyncio.run(verify(settings, original, experience)) == before
    migrate("downgrade", "006")
    assert asyncio.run(verify(settings, original, experience)) == before
    migrate("upgrade", "head")
    populated = asyncio.run(skill_snapshot(settings, original, create=True))
    assert "007 downgrade refused" in migrate("downgrade", "006", success=False).stderr
    assert asyncio.run(skill_snapshot(settings, original)) == populated
    print(json.dumps({"populated_m4_preserved": True, "empty_m5_rollback": True, "populated_skill_rollback_refused_atomically": True}))


if __name__ == "__main__":
    main()
