"""Populated 007↔008 preservation and refusal to discard any M6 history."""

import asyncio
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from isekai_memory.config import Settings
from isekai_memory.main import dispatch_tool
from isekai_memory.retrieval.citations import canonical, digest
from isekai_memory.store.database import close_pool, health_check, init_pool
from tests.migration_e2e_smoke import empty_database, seed

BASE_TABLES = ("handoffs", "handoff_claim_receipts", "memory_experiences", "memory_experience_events", "memory_skills",
               "memory_skill_revisions", "memory_skill_sources", "memory_skill_events")
TEAM_TABLES = ("memory_asset_grants", "memory_knowledge_documents", "memory_knowledge_events", "memory_skill_imports", "memory_asset_feedback")


async def seed_skill(settings, source):
    await init_pool(settings)
    try:
        mid = (await dispatch_tool("memory_experience_propose", {"project_id": "project-1", "source_handoff_id": str(source["id"]),
                     "idempotency_key": "procedure", "kind": "procedure", "title": "Receipt", "content": "Verify the receipt."}))["memory_id"]
        await dispatch_tool("memory_experience_review", {"project_id": "project-1", "memory_id": mid, "expected_version": 1, "action": "approve"})
        skill = await dispatch_tool("memory_skill_propose", {"project_id": "project-1", "name": "migration-skill", "idempotency_key": "skill",
                                    "sources": [{"memory_id": mid, "version": 2}], "body": {
            "title": "Receipt verification", "description": "Check receipts", "triggers": ["Retry needed"],
            "steps": [{"instruction": "Read receipt", "sources": [mid]}], "validation": ["Receipt matches"],
        }})
        await dispatch_tool("memory_skill_review", {"project_id": "project-1", "revision_id": skill["revision_id"], "expected_version": 1, "action": "approve"})
        return skill
    finally:
        await close_pool()


async def snapshot(settings, *, team=False):
    pool = await init_pool(settings)
    try:
        return {name: [dict(row) for row in await pool.fetch(f"SELECT * FROM {name} ORDER BY 1,2")]
                for name in (*BASE_TABLES, *(TEAM_TABLES if team else ()))}
    finally:
        await close_pool()


async def populate(settings, skill, source):
    await init_pool(settings)
    try:
        assert (await health_check())["schema_revision"] == "008"

        async def call(name, arguments):
            return await dispatch_tool(name, {"project_id": "project-1", **arguments})

        until = (datetime.now(UTC) + timedelta(days=1)).isoformat()
        text = {"title": "Wiki reference", "content": "Receipt checklist"}
        doc = await call("memory_knowledge_sync", {"provider": "pushed_wiki_v1", "source_key": "wiki", "source_revision": "one",
                         "expected_version": 0, "classification": "internal", "valid_until": until, **text, "content_digest": digest(canonical(text))})
        asset = {"asset_kind": "knowledge", "asset_id": doc["document_id"], "asset_version": 1}
        granted = await call("memory_grant_create", {**asset, "consumer_project_id": "consumer", "max_classification": "internal",
                             "expires_at": until, "idempotency_key": "grant"})
        await call("memory_feedback_record", {**asset, "usefulness": "helpful", "outcome": "not_attempted", "idempotency_key": "feedback"})
        exported = await call("memory_skill_export", {"revision_id": skill["revision_id"], "expected_version": 2, "source_lock_digest": source["lock_snapshot_digest"]})
        imported = await call("memory_skill_import", {**{k: exported[k] for k in ("archive_base64", "archive_digest", "manifest_digest", "artifact_digest")},
                              "classification": "internal", "idempotency_key": "import"})
        await call("memory_skill_import_forget", {"import_id": imported["import_id"], "expected_version": 1})
        await call("memory_grant_revoke", {"grant_id": granted["grant_id"], "expected_version": 1})
        await call("memory_knowledge_delete", {"document_id": doc["document_id"], "expected_version": 1})
    finally:
        await close_pool()


def main():
    dsn = os.environ.get("MEMORY_TEST_DATABASE_URL")
    if not dsn:
        raise SystemExit("MEMORY_TEST_DATABASE_URL must select an empty disposable database")
    settings = Settings(database_url=dsn)
    asyncio.run(empty_database(settings))

    def migrate(action, target, *, success=True):
        result = subprocess.run([sys.executable, "-m", "alembic", action, target],
                                env={**os.environ, "ISEKAI_MEMORY_DATABASE_URL": dsn}, cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, timeout=30)
        assert (result.returncode == 0) == success, result.stderr
        return result

    migrate("upgrade", "007")
    original = asyncio.run(seed(settings))
    skill = asyncio.run(seed_skill(settings, original))
    before = asyncio.run(snapshot(settings))
    migrate("upgrade", "head")
    assert asyncio.run(snapshot(settings)) == before
    migrate("downgrade", "007")
    assert asyncio.run(snapshot(settings)) == before
    migrate("upgrade", "head")
    asyncio.run(populate(settings, skill, original))
    populated = asyncio.run(snapshot(settings, team=True))
    assert "008 downgrade refused" in migrate("downgrade", "007", success=False).stderr
    assert asyncio.run(snapshot(settings, team=True)) == populated
    print(json.dumps({"populated_m5_preserved": True, "empty_m6_rollback": True, "retired_m6_history_rollback_refused_atomically": True}))


if __name__ == "__main__":
    main()
