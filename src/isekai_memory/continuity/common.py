"""Bounded transactions, project-wide serialization and actor-bound receipts."""

import asyncio
import hashlib
import json
from contextlib import asynccontextmanager

import asyncpg
from fastapi.encoders import jsonable_encoder

from isekai_memory.server.errors import MemoryToolError
from isekai_memory.store.database import get_pool

CLASSIFICATIONS = ["public", "internal", "confidential", "restricted"]


def fail(message="Continuity record is unavailable in this scope", code="MEM-CONTINUITY-0001", status=404):
    return MemoryToolError(message, data={"error_code": code}, http_status=status)


def conflict(message="Continuity version, identity or receipt conflicts"):
    return fail(message, "MEM-CONTINUITY-0002", 409)


def invalid(message):
    return fail(message, "MEM-CONTINUITY-0003", 400)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return "sha256:" + hashlib.sha256(canonical(value)).hexdigest()


def token_digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def is_admin(principal):
    return principal.local or "admin" in principal.scopes


def require_admin(principal):
    if not is_admin(principal):
        raise fail("Project admin authority is required", "MEM-CONTINUITY-0004", 403)


def ceiling(row, arguments):
    if CLASSIFICATIONS.index(row["classification"]) > CLASSIFICATIONS.index(arguments.get("max_classification", "internal")):
        raise fail()


@asynccontextmanager
async def transaction(project):
    try:
        async with asyncio.timeout(8), get_pool().acquire() as conn, conn.transaction():
            await conn.execute("SET LOCAL statement_timeout='6s'")
            # Same ordering for every continuity read/mutation, before any legacy row lock.
            await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended($1,0))", "isekai-continuity:" + project)
            yield conn
    except (TimeoutError, asyncpg.QueryCanceledError) as exc:
        raise fail("Continuity operation exceeded its time budget", "MEM-CONTINUITY-0005", 503) from exc


async def receipt(conn, arguments, principal, operation, result=None):
    material = {key: value for key, value in arguments.items() if key != "idempotency_key"}
    if "claim_token" in material:
        material["claim_token"] = token_digest(material["claim_token"])
    fingerprint = digest(material)
    keys = (arguments["project_id"], principal.user_id, operation, arguments["idempotency_key"])
    if result is None:
        row = await conn.fetchrow("SELECT request_digest,result FROM memory_continuity_receipts "
                                  "WHERE project_id=$1 AND actor_id=$2 AND operation=$3 AND idempotency_key=$4", *keys)
        if not row:
            return None
        if row["request_digest"] != fingerprint:
            raise conflict()
        return {**row["result"], "replayed": True}
    result = jsonable_encoder({**result, "replayed": False})
    await conn.execute("INSERT INTO memory_continuity_receipts(project_id,actor_id,operation,idempotency_key,request_digest,result) "
                       "VALUES($1,$2,$3,$4,$5,$6)", *keys, fingerprint, result)
    return result


async def event(conn, project, actor, action, target, details):
    await conn.execute("INSERT INTO memory_continuity_events(project_id,actor_id,action,target_id,details) VALUES($1,$2,$3,$4,$5)",
                       project, actor, action, str(target), jsonable_encoder(details))
    from isekai_memory.continuity.events import project_event
    await project_event(conn, project, actor, action, target, details)


async def policy(conn, project, *, enabled=True):
    row = await conn.fetchrow("SELECT * FROM memory_continuity_policies WHERE project_id=$1", project)
    if row is None or (enabled and not row["policy"]["enabled"]):
        raise fail("Project continuity policy is absent or disabled", "MEM-CONTINUITY-0006", 409)
    return row


async def eligible(conn, project, users, *, sender=None):
    if sender is not None and sender in users:
        raise invalid("A handover user cannot be their own successor")
    rows = await conn.fetch("SELECT DISTINCT user_id FROM access_tokens WHERE project_id=$1 AND user_id=ANY($2::text[]) "
                            "AND revoked_at IS NULL AND (expires_at IS NULL OR expires_at>clock_timestamp()) "
                            "AND ('admin'=ANY(scopes) OR ('read'=ANY(scopes) AND 'write'=ANY(scopes)))", project, list(users))
    if {row["user_id"] for row in rows} != set(users):
        raise fail("All recipients must have live project read/write or admin authority", "MEM-CONTINUITY-0007", 409)
