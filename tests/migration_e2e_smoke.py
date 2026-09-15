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
from isekai_memory.handoff.service import _claim_token_digest, _digest
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
        # Frozen schema-003 fixture: current runtime queries require schema 010.
        args = handoff_arguments()
        material = {**args, "from_user": "local-stdio", "task_summary": None,
                    "passed_checks": [], "artifacts_produced": [], "handoff_note": None}
        async with pool.acquire() as conn:
            return dict(await conn.fetchrow(
                """INSERT INTO handoffs
                   (project_id,unit_id,phase_attempt_id,phase_id,from_user,result_status,classification,
                    task_envelope,result_envelope,context_digest,raw_output,lock_snapshot_digest,envelope_digest,
                    payload_digest,expires_at,status,claimed_by,claimed_at,claim_token_digest,claim_generation,claim_lease_expires_at)
                   VALUES ($1,$2,$3,$4,'local-stdio',$5,$6,$7::jsonb,$8::jsonb,$9,$10,$11,$12,$13,
                           clock_timestamp()+interval '7 days','claimed','local-stdio',clock_timestamp(),$14,1,
                           clock_timestamp()+interval '1 hour') RETURNING *""",
                args["project_id"], args["unit_id"], args["phase_attempt_id"], args["phase_id"],
                args["result_status"], args["classification"], args["task_envelope"], args["result_envelope"],
                args["context_digest"], args["raw_output"], args["lock_snapshot_digest"], args["envelope_digest"],
                _digest(material), _claim_token_digest(secrets.token_urlsafe(32)),
            ))
    finally:
        await close_pool()


async def verify(settings, original, *, experience):
    pool = await init_pool(settings)
    try:
        async with pool.acquire() as conn:
            saved = dict(await conn.fetchrow("SELECT * FROM handoffs WHERE id=$1", original["id"]))
            assert legacy_handoff(saved) == original, "Migration changed an existing handoff payload or claim"
        if experience:
            assert (await health_check())["schema_revision"] == "013"
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


def legacy_handoff(row):
    """Assert additive defaults, then compare all historical columns exactly."""
    saved = dict(row)
    for name, expected in {"handoff_version": 1, "recipient_user_id": None,
                           "continuation": None, "continuation_digest": None, "continuity_managed": False}.items():
        if name in saved:
            assert saved.pop(name) == expected
    return saved


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
