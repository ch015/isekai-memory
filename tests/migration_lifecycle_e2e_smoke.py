"""Populated 004→005 backfill/replay, safe rollback and M2 rollback refusal.

Requires a separate EMPTY disposable database. No configured application database
is selected implicitly. Source rows and all original M1 columns are compared.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from isekai_memory.config import Settings
from isekai_memory.main import dispatch_tool
from isekai_memory.server.errors import MemoryToolError
from isekai_memory.store.database import close_pool, health_check, init_pool
from tests.migration_e2e_smoke import empty_database, seed


async def seed_m1(settings, original):
    pool = await init_pool(settings)
    proposals = []
    try:
        async with pool.acquire() as conn, conn.transaction():
            source = {
                key: original[key]
                for key in (
                    "id",
                    "unit_id",
                    "phase_attempt_id",
                    "phase_id",
                    "result_status",
                    "classification",
                    "envelope_digest",
                    "payload_digest",
                    "lock_snapshot_digest",
                )
            }
            source["id"] = str(source["id"])
            for status in ("active", "rejected"):
                args = {
                    "project_id": original["project_id"],
                    "source_handoff_id": str(original["id"]),
                    "idempotency_key": "m1-" + status,
                    "kind": "lesson",
                    "title": "M1 " + status,
                    "content": "Retain " + status + " evidence.",
                }
                material = {key: args[key] for key in ("source_handoff_id", "kind", "title", "content")}
                material.update(tags=[], expires_at=None)
                digest = (
                    "sha256:"
                    + hashlib.sha256(
                        json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
                    ).hexdigest()
                )
                memory_id = await conn.fetchval(
                    """
                    INSERT INTO memory_experiences
                        (project_id,source_handoff_id,source,source_lock_digest,classification,kind,title,content,tags,
                         search_text,status,version,created_by,idempotency_key,submission_digest)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,'{}',$9,$10,2,'local-stdio',$11,$12) RETURNING id
                    """,
                    original["project_id"],
                    original["id"],
                    source,
                    original["lock_snapshot_digest"],
                    original["classification"],
                    args["kind"],
                    args["title"],
                    args["content"],
                    (args["title"] + " " + args["content"]).casefold(),
                    status,
                    args["idempotency_key"],
                    digest,
                )
                await conn.execute(
                    "INSERT INTO memory_experience_events (memory_id,version,actor_id,action,previous_status,applied_status) "
                    "VALUES ($1,2,'local-stdio',$2,'pending',$3)",
                    memory_id,
                    "approve" if status == "active" else "reject",
                    status,
                )
                proposals.append((str(memory_id), args))
            # Exercise both sides of the migration's 500-row batch boundary.
            await conn.execute(
                """
                INSERT INTO memory_experiences
                    (project_id,source_handoff_id,source,source_lock_digest,classification,kind,title,content,tags,
                     search_text,created_by,idempotency_key,submission_digest)
                SELECT project_id,source_handoff_id,source,source_lock_digest,classification,kind,title,content,tags,
                    search_text,created_by,'m1-batch-' || n,submission_digest
                FROM memory_experiences CROSS JOIN generate_series(1,500) n WHERE id=$1::uuid
                """,
                proposals[0][0],
            )
            rows = [dict(row) for row in await conn.fetch("SELECT * FROM memory_experiences ORDER BY id")]
            events = [
                dict(row)
                for row in await conn.fetch("SELECT * FROM memory_experience_events ORDER BY memory_id,version")
            ]
            return proposals, rows, events
    finally:
        await close_pool()


async def verify_m1(settings, source, originals, *, upgraded):
    proposals, rows, events = originals
    pool = await init_pool(settings)
    try:
        async with pool.acquire() as conn:
            assert dict(await conn.fetchrow("SELECT * FROM handoffs WHERE id=$1", source["id"])) == source
            saved = [dict(row) for row in await conn.fetch("SELECT * FROM memory_experiences ORDER BY id")]
            assert [{key: row[key] for key in rows[0]} for row in saved] == rows
            receipts = [
                dict(row)
                for row in await conn.fetch("SELECT * FROM memory_experience_events ORDER BY memory_id,version")
            ]
            assert [{key: row[key] for key in events[0]} for row in receipts] == events
            if upgraded:
                assert len(saved) == 502 and all(
                    row["content_fingerprint"] and row["source_payload_digest"] == source["payload_digest"]
                    for row in saved
                )
        if upgraded:
            assert (await health_check())["schema_revision"] == "008"
            for memory_id, args in proposals:
                assert (await dispatch_tool("memory_experience_propose", args)) == {
                    "memory_id": memory_id,
                    "already_exists": True,
                }
                receipt = await dispatch_tool(
                    "memory_experience_review",
                    {
                        "project_id": source["project_id"],
                        "memory_id": memory_id,
                        "action": "approve" if args["idempotency_key"] == "m1-active" else "reject",
                        "expected_version": 1,
                    },
                )
                assert receipt["already_applied"] and receipt["applied_version"] == 2
            try:
                await dispatch_tool(
                    "memory_experience_propose", {**proposals[1][1], "idempotency_key": "new-rejected-copy"}
                )
            except MemoryToolError as exc:
                assert exc.data["error_code"] == "MEM-EXPERIENCE-0007"
            else:
                raise AssertionError("M1 rejected claim was not suppressed")
    finally:
        await close_pool()


async def m2_snapshot(settings, originals, *, create):
    pool = await init_pool(settings)
    try:
        if create:
            parent, args = originals[0][0]
            child = await dispatch_tool(
                "memory_experience_revise",
                {
                    "project_id": args["project_id"],
                    "memory_id": parent,
                    "expected_version": 2,
                    "idempotency_key": "m2-revision",
                    "kind": "lesson",
                    "title": "Correction",
                    "content": "Corrected evidence.",
                },
            )
            await dispatch_tool(
                "memory_experience_review",
                {
                    "project_id": args["project_id"],
                    "memory_id": child["memory_id"],
                    "action": "approve",
                    "expected_version": 1,
                },
            )
            await dispatch_tool(
                "memory_experience_review",
                {"project_id": args["project_id"], "memory_id": parent, "action": "forget", "expected_version": 3},
            )
        assert (await health_check())["schema_revision"] == "008"
        async with pool.acquire() as conn:
            return {
                table: [dict(row) for row in await conn.fetch("SELECT * FROM " + table + " ORDER BY 1,2")]
                for table in (
                    "handoffs",
                    "memory_experiences",
                    "memory_experience_events",
                    "memory_experience_suppressions",
                )
            }
    finally:
        await close_pool()


def main():
    dsn = os.environ.get("MEMORY_TEST_DATABASE_URL")
    if not dsn:
        raise SystemExit("MEMORY_TEST_DATABASE_URL must explicitly select an empty disposable database")
    settings = Settings(database_url=dsn)
    asyncio.run(empty_database(settings))
    environment = {**os.environ, "ISEKAI_MEMORY_DATABASE_URL": dsn}

    def migrate(action, revision, *, succeeds=True):
        result = subprocess.run(
            [sys.executable, "-m", "alembic", action, revision],
            cwd=Path(__file__).resolve().parents[1],
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if succeeds:
            assert result.returncode == 0, result.stderr
        else:
            assert result.returncode != 0 and "Cannot downgrade M2" in result.stderr, result.stderr

    migrate("upgrade", "004")
    source = asyncio.run(seed(settings))
    originals = asyncio.run(seed_m1(settings, source))
    migrate("upgrade", "head")
    asyncio.run(verify_m1(settings, source, originals, upgraded=True))
    migrate("downgrade", "004")
    asyncio.run(verify_m1(settings, source, originals, upgraded=False))
    migrate("upgrade", "head")
    asyncio.run(verify_m1(settings, source, originals, upgraded=True))
    before = asyncio.run(m2_snapshot(settings, originals, create=True))
    migrate("downgrade", "004", succeeds=False)
    assert asyncio.run(m2_snapshot(settings, originals, create=False)) == before
    print(
        json.dumps(
            {
                "m1_rows_preserved": 502,
                "receipts_preserved": True,
                "suppression_backfilled": True,
                "safe_rollback": True,
                "m2_rollback_refused_without_changes": True,
            }
        )
    )


if __name__ == "__main__":
    main()
