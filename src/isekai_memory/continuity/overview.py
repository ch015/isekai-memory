"""Read-only M9 collaboration metadata. No receipts, leases, or source bodies."""

import asyncio
from contextlib import asynccontextmanager

import asyncpg
from fastapi.encoders import jsonable_encoder

from isekai_memory.continuity.common import CLASSIFICATIONS, fail, is_admin
from isekai_memory.experience import pagination
from isekai_memory.store.database import get_pool

CONTRACT_VERSION = 1
COUNT_LIMIT = 10000
VIEWS = ("work", "inbox", "sent", "checkpoints")
CAPABILITIES = {"overview": True, "lists": True, "presence": True, "idle": True, "token_usage": True}
# Every query uses the same parameter contract: project, actor, project_scope,
# classification list, observed_at, include_inactive, include_acknowledged.
BUNDLE_FILTER = """
    b.project_id=$1 AND b.classification=ANY($4::text[])
    AND ($6::boolean OR (b.revoked_at IS NULL AND b.expires_at>$5::timestamptz))
"""
BUNDLE_STATE = """CASE WHEN b.revoked_at IS NOT NULL THEN 'revoked'
    WHEN b.expires_at<=$5::timestamptz THEN 'expired' ELSE 'retained' END"""
QUERIES = {
    "sent": f"""
        SELECT b.id,b.project_id,b.created_at,b.from_user,b.created_by,b.classification,
            b.version,b.policy_version,b.source_checkpoint_id,b.source_handoff_id,b.source_digest,
            b.expires_at,b.revoked_at,{BUNDLE_STATE} AS effective_state
        FROM memory_continuity_bundles b
        WHERE {BUNDLE_FILTER} AND ($3::boolean OR b.from_user=$2)
            AND ($7::boolean OR NOT $7::boolean)
    """,
    "inbox": f"""
        SELECT d.id,d.project_id,d.created_at,d.bundle_id,d.recipient_user_id,d.routing_version,
            d.acknowledged_at,d.revoked_at,b.from_user,b.classification,b.source_digest,b.expires_at,
            b.version AS current_routing_version,
            CASE WHEN d.revoked_at IS NOT NULL OR b.revoked_at IS NOT NULL THEN 'revoked'
                WHEN b.expires_at<=$5::timestamptz THEN 'expired'
                WHEN d.acknowledged_at IS NOT NULL THEN 'acknowledged' ELSE 'pending' END AS effective_state
        FROM memory_continuity_deliveries d
        JOIN memory_continuity_bundles b ON (b.id,b.project_id)=(d.bundle_id,d.project_id)
        WHERE {BUNDLE_FILTER} AND ($3::boolean OR (d.recipient_user_id=$2 AND d.revoked_at IS NULL))
            AND ($6::boolean OR d.revoked_at IS NULL) AND ($7::boolean OR d.acknowledged_at IS NULL)
    """,
    "work": f"""
        SELECT u.id,u.project_id,u.updated_at AS created_at,u.updated_at,u.bundle_id,u.unit_key,
            u.summary,u.assignee_user_ids,u.state,u.claimed_by,u.claim_generation,u.lease_expires_at,
            b.from_user,b.classification,b.expires_at,b.version AS routing_version,
            CASE WHEN b.revoked_at IS NOT NULL THEN 'revoked'
                WHEN b.expires_at<=$5::timestamptz THEN 'expired'
                WHEN u.state='claimed' AND u.lease_expires_at<=$5::timestamptz THEN 'lease_expired'
                ELSE u.state END AS effective_state,
            CASE WHEN b.revoked_at IS NOT NULL OR b.expires_at<=$5::timestamptz THEN 'unavailable'
                WHEN u.state!='claimed' THEN 'none'
                WHEN u.lease_expires_at<=$5::timestamptz THEN 'expired' ELSE 'valid' END AS ownership,
            'unobserved'::text AS execution_state
        FROM memory_continuity_units u
        JOIN memory_continuity_bundles b ON (b.id,b.project_id)=(u.bundle_id,u.project_id)
        WHERE {BUNDLE_FILTER} AND ($3::boolean OR b.from_user=$2 OR EXISTS(
            SELECT 1 FROM memory_continuity_deliveries d
            WHERE (d.bundle_id,d.project_id)=(b.id,b.project_id)
                AND d.recipient_user_id=$2 AND d.revoked_at IS NULL))
            AND ($7::boolean OR NOT $7::boolean)
    """,
    "checkpoints": """
        SELECT c.id,c.project_id,c.created_at,c.work_id,c.from_user,c.version,c.classification,
            c.lock_snapshot_digest,c.continuation_digest,c.snapshot_digest,c.payload_digest,
            c.policy_version,c.expires_at,c.forgotten_at,
            CASE WHEN c.forgotten_at IS NOT NULL THEN 'forgotten'
                WHEN c.expires_at<=$5::timestamptz THEN 'expired' ELSE 'retained' END AS effective_state
        FROM memory_checkpoints c
        WHERE c.project_id=$1 AND ($3::boolean OR c.from_user=$2) AND c.classification=ANY($4::text[])
            AND ($6::boolean OR (c.forgotten_at IS NULL AND c.expires_at>$5::timestamptz))
            AND ($7::boolean OR NOT $7::boolean)
    """,
}


@asynccontextmanager
async def read_transaction():
    """A repeatable read snapshot without the continuity mutation advisory lock."""
    try:
        async with asyncio.timeout(8), get_pool().acquire() as conn, conn.transaction(isolation="repeatable_read", readonly=True):
            await conn.execute("SET LOCAL statement_timeout='1500ms'")
            yield conn
    except (TimeoutError, asyncpg.QueryCanceledError) as exc:
        raise fail("Collaboration query exceeded its time budget", "MEM-COLLABORATION-0002", 503) from exc


def request_scope(arguments, principal):
    kind = arguments.get("scope", "mine")
    if kind == "project" and not is_admin(principal):
        raise fail("Project overview requires admin authority", "MEM-COLLABORATION-0001", 403)
    return {
        "kind": kind,
        "max_classification": arguments.get("max_classification", "internal"),
        "include_inactive": arguments.get("include_inactive", False),
        "include_acknowledged": arguments.get("include_acknowledged", False),
    }


def query_parameters(arguments, principal, scope, now):
    allowed = CLASSIFICATIONS[:CLASSIFICATIONS.index(scope["max_classification"]) + 1]
    return (arguments["project_id"], principal.user_id, scope["kind"] == "project",
            allowed, now, scope["include_inactive"], scope["include_acknowledged"])


def cursor_scope(arguments, principal, scope, view):
    return ["collaboration-v1", arguments["project_id"], principal.user_id,
            ",".join(sorted(principal.scopes)), str(principal.local), view,
            scope["kind"], scope["max_classification"], str(scope["include_inactive"]),
            str(scope["include_acknowledged"])]


def envelope(arguments, principal, scope, now):
    return {"contract_version": CONTRACT_VERSION, "project_id": arguments["project_id"],
            "actor_id": principal.user_id, "scope": scope, "observed_at": now,
            "cache_policy": "no_store", "consistency": "snapshot_per_response_live_pagination"}


async def count_view(conn, view, params):
    row = await conn.fetchrow(
        f"SELECT count(*) AS n FROM (SELECT id FROM ({QUERIES[view]}) visible LIMIT $8) bounded",
        *params, COUNT_LIMIT + 1,
    )
    count = row["n"]
    complete = count <= COUNT_LIMIT
    return {"value": count if complete else None, "lower_bound": min(count, COUNT_LIMIT),
            "coverage": "complete" if complete else "partial"}


async def overview(arguments, *, principal):
    from isekai_memory.continuity.tools import CONTINUITY_SCOPES
    from isekai_memory.server.auth import _TOOL_SCOPES, authorize_tool

    authorize_tool(principal, "memory_collaboration_overview", arguments)
    scope = request_scope(arguments, principal)
    async with read_transaction() as conn:
        now = await conn.fetchval("SELECT transaction_timestamp()")
        params = query_parameters(arguments, principal, scope, now)
        counts = {view: await count_view(conn, view, params) for view in VIEWS}
        policy = await conn.fetchrow(
            "SELECT version,policy->>'enabled' AS enabled FROM memory_continuity_policies WHERE project_id=$1",
            arguments["project_id"],
        )
        exposed = {**CONTINUITY_SCOPES, **{name: _TOOL_SCOPES[name] for name in (
            "memory_search", "memory_read", "memory_experience_list", "memory_experience_review")}}
        actions = sorted(name for name, required in exposed.items()
                         if is_admin(principal) or required in principal.scopes)
        return jsonable_encoder({
            **envelope(arguments, principal, scope, now),
            "coverage": "complete" if all(count["coverage"] == "complete" for count in counts.values()) else "partial",
            "capabilities": dict(CAPABILITIES),
            "identity": {"user_id": principal.user_id, "project_admin": is_admin(principal),
                         "local": principal.local},
            "allowed_tools": actions,
            "counts": counts,
            "continuity_policy": {"configured": policy is not None,
                                  "version": policy["version"] if policy else 0,
                                  "enabled": policy["enabled"] == "true" if policy else False},
            # Capability describes an API, not opt-in or successful collection. Read it separately.
            "telemetry": {key: {"status": "separate_query",
                                "reason": "use_presence_tools" if key != "token_usage" else "use_usage_tools",
                                "value": None} for key in ("presence", "idle", "token_usage")},
        })


async def listing(arguments, *, principal):
    from isekai_memory.server.auth import authorize_tool

    authorize_tool(principal, "memory_collaboration_list", arguments)
    scope = request_scope(arguments, principal)
    view = arguments["view"]
    binding = cursor_scope(arguments, principal, scope, view)
    at, row_id = pagination.decode(arguments.get("cursor"), binding)
    limit = arguments.get("limit", 20)
    async with read_transaction() as conn:
        now = await conn.fetchval("SELECT transaction_timestamp()")
        params = query_parameters(arguments, principal, scope, now)
        rows = await conn.fetch(
            f"""SELECT * FROM ({QUERIES[view]}) visible
                WHERE ($8::timestamptz IS NULL OR (created_at,id)<($8,$9::uuid))
                ORDER BY created_at DESC,id DESC LIMIT $10""",
            *params, at, row_id, limit + 1,
        )
        page = pagination.page([dict(row) for row in rows], limit, binding)
        return jsonable_encoder({**envelope(arguments, principal, scope, now),
                                 "view": view, "coverage": "page", **page})
