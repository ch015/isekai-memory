"""Verify 003 → head → 003 preserves an existing claimed handoff.

MEMORY_TEST_DATABASE_URL must select a disposable database with an empty public
schema. The script refuses an existing schema before any migration. Downgrading
removes only the synthetic experiences it creates, then upgrades back to head.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

from isekai_memory.config import Settings
from isekai_memory.handoff.service import claim_handoff_recoverable, push_handoff
from isekai_memory.main import dispatch_tool
from isekai_memory.store.database import close_pool, health_check, init_pool
from tests.helpers import handoff_arguments


async def empty_database(settings):
    pool = await init_pool(settings)
    try:
        async with pool.acquire() as conn:
            tables = await conn.fetchval("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
            if tables:
                raise RuntimeError("Migration smoke requires an EMPTY public schema in a disposable database")
    finally:
        await close_pool()


async def seed(settings):
    pool = await init_pool(settings)
    try:
        source = await push_handoff(handoff_arguments(), settings=settings)
        await claim_handoff_recoverable({
            "project_id": "project-1", "handoff_id": source["handoff_id"], "claim_token": secrets.token_urlsafe(32),
        }, settings=settings)
        async with pool.acquire() as conn:
            return dict(await conn.fetchrow("SELECT * FROM handoffs WHERE id=$1::uuid", source["handoff_id"]))
    finally:
        await close_pool()


async def verify(settings, original, *, experience):
    pool = await init_pool(settings)
    try:
        async with pool.acquire() as conn:
            saved = dict(await conn.fetchrow("SELECT * FROM handoffs WHERE id=$1", original["id"]))
            assert saved == original, "Migration changed an existing handoff payload or claim"
        if experience:
            assert (await health_check())["schema_revision"] == "008"
            proposed = await dispatch_tool("memory_experience_propose", {
                "project_id": "project-1", "source_handoff_id": str(original["id"]),
                "idempotency_key": "migration-proposal", "kind": "lesson",
                "title": "Preserve claim receipts", "content": "Migration must preserve an existing lease.",
            })
            await dispatch_tool("memory_experience_review", {
                "project_id": "project-1", "memory_id": proposed["memory_id"], "action": "approve", "expected_version": 1,
            })
            await dispatch_tool("memory_read", {"project_id": "project-1", "memory_id": proposed["memory_id"]})
    finally:
        await close_pool()


def main():
    dsn = os.environ.get("MEMORY_TEST_DATABASE_URL")
    if not dsn:
        raise SystemExit("MEMORY_TEST_DATABASE_URL must explicitly select an empty disposable database")
    settings = Settings(database_url=dsn)
    asyncio.run(empty_database(settings))
    environment = {**os.environ, "ISEKAI_MEMORY_DATABASE_URL": dsn}
    root = Path(__file__).resolve().parents[1]

    def migrate(action, revision):
        subprocess.run([sys.executable, "-m", "alembic", action, revision], cwd=root, env=environment, check=True, timeout=30)

    migrate("upgrade", "003")
    original = asyncio.run(seed(settings))
    migrate("upgrade", "head")
    asyncio.run(verify(settings, original, experience=True))
    migrate("downgrade", "003")
    asyncio.run(verify(settings, original, experience=False))
    migrate("upgrade", "head")
    print(json.dumps({"populated_upgrade": True, "test_data_downgrade": True, "handoff_payload_and_claim_preserved": True}))


if __name__ == "__main__":
    main()
