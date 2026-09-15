"""Populated 008↔009 preservation and refusal to erase any M8 delivery history."""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from isekai_memory.config import Settings
from isekai_memory.handoff.service import _compute_envelope_digest, push_handoff
from isekai_memory.store.database import close_pool, health_check, init_pool
from tests.helpers import continuation_package, handoff_arguments
from tests.migration_e2e_smoke import empty_database, legacy_handoff, seed


async def snapshot(settings, *, legacy=False):
    pool = await init_pool(settings)
    try:
        handoffs = [dict(row) for row in await pool.fetch("SELECT * FROM handoffs ORDER BY id")]
        receipts = [dict(row) for row in await pool.fetch("SELECT * FROM handoff_claim_receipts ORDER BY id")]
        return {"handoffs": [legacy_handoff(row) for row in handoffs] if legacy else handoffs, "receipts": receipts}
    finally:
        await close_pool()


async def populate(settings):
    await init_pool(settings)
    try:
        assert (await health_check())["schema_revision"] == "013"
        args = handoff_arguments()
        args["phase_attempt_id"] = "continuation-migration"
        for field in ("task_envelope", "result_envelope"):
            args[field]["phase_attempt_id"] = args["phase_attempt_id"]
        args["envelope_digest"] = _compute_envelope_digest(args["task_envelope"], args["result_envelope"])
        args["continuation"] = continuation_package()
        return (await push_handoff(args, settings=settings))["handoff_id"]
    finally:
        await close_pool()


async def transition(settings, hid, status):
    pool = await init_pool(settings)
    try:
        await pool.execute("UPDATE handoffs SET status=$2 WHERE id=$1::uuid", hid, status)
    finally:
        await close_pool()


def main():
    dsn = os.environ.get("MEMORY_TEST_DATABASE_URL")
    if not dsn:
        raise SystemExit("MEMORY_TEST_DATABASE_URL must select an EMPTY disposable database")
    settings = Settings(database_url=dsn)
    asyncio.run(empty_database(settings))

    def migrate(action, target, success=True):
        result = subprocess.run([sys.executable, "-m", "alembic", action, target],
                                env={**os.environ, "ISEKAI_MEMORY_DATABASE_URL": dsn}, cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, timeout=30)
        assert (result.returncode == 0) == success, result.stderr
        return result

    migrate("upgrade", "008")
    asyncio.run(seed(settings))
    before = asyncio.run(snapshot(settings, legacy=True))
    migrate("upgrade", "head")
    assert asyncio.run(snapshot(settings, legacy=True)) == before
    migrate("downgrade", "008")
    assert asyncio.run(snapshot(settings, legacy=True)) == before
    migrate("upgrade", "head")
    hid = asyncio.run(populate(settings))
    for state in ("pending", "claimed", "acknowledged", "expired"):
        asyncio.run(transition(settings, hid, state))
        expected = asyncio.run(snapshot(settings))
        assert "009 downgrade refused" in migrate("downgrade", "008", success=False).stderr
        assert asyncio.run(snapshot(settings)) == expected
    print(json.dumps({"legacy_payload_claim_preserved": True, "empty_m8_rollback": True,
                      "m8_history_rollback_refused_for_all_delivery_states": True}))


if __name__ == "__main__":
    main()
