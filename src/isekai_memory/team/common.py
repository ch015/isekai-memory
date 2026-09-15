"""Small shared transaction and metadata helpers, without generic asset inheritance."""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import asyncpg
from fastapi.encoders import jsonable_encoder

from isekai_memory.experience import pagination
from isekai_memory.experience.persistence import lock_project
from isekai_memory.experience.service import CLASSIFICATIONS
from isekai_memory.retrieval.citations import canonical, digest
from isekai_memory.server.errors import MemoryToolError
from isekai_memory.store.database import get_pool


def fail(message="Asset is unavailable in this scope", code="MEM-TEAM-0001", status=404):
    return MemoryToolError(message, data={"error_code": code}, http_status=status)


def conflict():
    return fail("Version, identity or receipt conflicts", "MEM-TEAM-0002", 409)


def fingerprint(arguments):
    return digest(canonical({k: v for k, v in arguments.items() if k not in {"project_id", "idempotency_key"}}))


def ceiling(classification, maximum):
    if CLASSIFICATIONS.index(classification) > CLASSIFICATIONS.index(maximum):
        raise fail()


async def deadline(conn, value, *, days):
    at = datetime.fromisoformat(value.upper().replace("Z", "+00:00")).astimezone(UTC)
    now = await conn.fetchval("SELECT clock_timestamp()")
    if not now < at <= now + timedelta(days=days):
        raise fail("Validity must be in the future and within the allowed window", "MEM-TEAM-0003", 400)
    return at


@asynccontextmanager
async def transaction(project_id=None):
    try:
        async with asyncio.timeout(5), get_pool().acquire() as conn, conn.transaction():
            await conn.execute("SET LOCAL statement_timeout='4s'")
            if project_id is not None:
                await lock_project(conn, project_id)
            yield conn
    except (TimeoutError, asyncpg.QueryCanceledError) as exc:
        raise fail("Team asset operation exceeded its time budget", "MEM-TEAM-0006", 503) from exc


async def listing(arguments, *, table, columns, view, extra="", extra_values=()):
    # SQL identifiers/expressions are constants supplied by internal callers only.
    scope = [view, arguments["project_id"], *map(str, extra_values)]
    at, row_id = pagination.decode(arguments.get("cursor"), scope)
    limit = arguments.get("limit", 10)
    async with transaction() as conn:
        rows = await conn.fetch(
            f"SELECT {columns} FROM {table} WHERE project_id=$1 "
            f"AND ($2::timestamptz IS NULL OR (created_at,id)<($2,$3::uuid)) {extra} "
            "ORDER BY created_at DESC,id DESC LIMIT $4",
            arguments["project_id"], at, row_id, limit + 1, *extra_values,
        )
        return jsonable_encoder(pagination.page([dict(row) for row in rows], limit, scope))
