"""Scoped presence metadata and complete-set user aggregation, never table writes."""

from collections import defaultdict
from datetime import timedelta

from fastapi.encoders import jsonable_encoder

from isekai_memory.continuity.common import CLASSIFICATIONS, fail, is_admin
from isekai_memory.continuity.overview import read_transaction
from isekai_memory.continuity.presence import envelope, policy, policy_values
from isekai_memory.continuity.presence_state import aggregate_states, session_state
from isekai_memory.experience import pagination
from isekai_memory.server.auth import authorize_tool

AGGREGATE_LIMIT = 10000
VISIBLE = """
    SELECT s.id,s.project_id,s.actor_id,s.host_kind,s.session_kind,s.classification,s.sequence,s.state_sequence,
        s.reported_policy_version,s.reported_state,s.observation_scope,s.state_observation_available,s.active_work_count,
        s.created_at,s.last_seen_at,s.state_since_at,s.idle_since_at,s.ended_at,
        CASE WHEN EXISTS(SELECT 1 FROM memory_presence_sessions p WHERE p.id=s.parent_session_id
            AND p.classification=ANY($4::text[]) AND p.retired_at IS NULL) THEN s.parent_session_id END AS parent_session_id,
        CASE WHEN EXISTS(
            SELECT 1 FROM memory_continuity_units u JOIN memory_continuity_bundles b ON b.id=u.bundle_id
            WHERE u.id=s.work_unit_id AND b.classification=ANY($4::text[]) AND b.revoked_at IS NULL AND b.expires_at>$8
                AND ($3::boolean OR (s.actor_id=ANY(u.assignee_user_ids) AND EXISTS(
                    SELECT 1 FROM memory_continuity_deliveries d WHERE d.bundle_id=b.id
                        AND d.recipient_user_id=s.actor_id AND d.revoked_at IS NULL))))
            THEN s.work_unit_id END AS work_unit_id,
        CASE WHEN EXISTS(SELECT 1 FROM memory_checkpoints c WHERE c.id=s.checkpoint_id
            AND c.classification=ANY($4::text[]) AND c.forgotten_at IS NULL AND c.expires_at>$8)
            THEN s.checkpoint_id END AS checkpoint_id
    FROM memory_presence_sessions s
    WHERE s.project_id=$1 AND ($3::boolean OR s.actor_id=$2) AND s.classification=ANY($4::text[])
        AND ($5::text IS NULL OR s.host_kind=$5) AND COALESCE(s.ended_at,s.last_seen_at)>$6
        AND ($7::boolean OR s.ended_at IS NULL) AND s.retired_at IS NULL
"""


def scope_for(arguments, principal, view):
    kind = arguments.get("scope", "mine")
    if kind == "project" and not is_admin(principal):
        raise fail("Project presence requires admin authority", "MEM-PRESENCE-0005", 403)
    return {"kind": kind, "max_classification": arguments.get("max_classification", "internal"),
            "host_kind": arguments.get("host_kind"), "include_ended": arguments.get("include_ended", view == "users")}


def binding(arguments, principal, scope, view):
    return ["presence-v1", arguments["project_id"], principal.user_id, ",".join(sorted(principal.scopes)),
            str(principal.local), view, scope["kind"], scope["max_classification"],
            str(scope["host_kind"]), str(scope["include_ended"])]


def parameters(arguments, principal, scope, now, body):
    allowed = CLASSIFICATIONS[:CLASSIFICATIONS.index(scope["max_classification"]) + 1]
    return (arguments["project_id"], principal.user_id, scope["kind"] == "project", allowed,
            scope["host_kind"], now-timedelta(hours=body["retention_hours"]), scope["include_ended"], now)


def metadata(row, now, version, body):
    return {**dict(row), **session_state(row, now, policy_values(body)),
            "policy_version": version, "policy_mismatch": row["reported_policy_version"] != version}


async def listing(arguments, *, principal):
    authorize_tool(principal, "memory_presence_list", arguments)
    scope = scope_for(arguments, principal, "sessions")
    key = binding(arguments, principal, scope, "sessions")
    at, row_id = pagination.decode(arguments.get("cursor"), key)
    limit = arguments.get("limit", 20)
    async with read_transaction() as conn:
        now = await conn.fetchval("SELECT transaction_timestamp()")
        version, body = await policy(conn, arguments["project_id"])
        rows = await conn.fetch(
            f"SELECT * FROM ({VISIBLE}) visible WHERE ($9::timestamptz IS NULL OR (created_at,id)<($9,$10::uuid)) "
            "ORDER BY created_at DESC,id DESC LIMIT $11",
            *parameters(arguments, principal, scope, now, body), at, row_id, limit + 1,
        )
        page = pagination.page([metadata(row, now, version, body) for row in rows], limit, key)
        return jsonable_encoder({**envelope(arguments["project_id"], principal, now), "scope": scope,
                                 "policy_version": version, "policy": body, "coverage": "page", **page})


async def users(arguments, *, principal):
    authorize_tool(principal, "memory_presence_users", arguments)
    scope = scope_for(arguments, principal, "users")
    key = binding(arguments, principal, scope, "users")
    at, row_id = pagination.decode(arguments.get("cursor"), key)
    limit = arguments.get("limit", 20)
    async with read_transaction() as conn:
        now = await conn.fetchval("SELECT transaction_timestamp()")
        version, body = await policy(conn, arguments["project_id"])
        params = parameters(arguments, principal, scope, now, body)
        people = await conn.fetch(f"""
            SELECT * FROM (SELECT actor_id AS user_id,md5(actor_id)::uuid AS id,min(created_at) AS created_at
                FROM ({VISIBLE}) visible GROUP BY actor_id) people
            WHERE ($9::timestamptz IS NULL OR (created_at,id)<($9,$10::uuid))
            ORDER BY created_at DESC,id DESC LIMIT $11
        """, *params, at, row_id, limit + 1)
        page = pagination.page([dict(row) for row in people], limit, key)
        user_ids = [row["user_id"] for row in page["items"]]
        if not user_ids and scope["kind"] == "mine" and arguments.get("cursor") is None:
            user_ids = [principal.user_id]
        rows = await conn.fetch(f"""
            WITH ranked AS (
                SELECT *,row_number() OVER(PARTITION BY actor_id ORDER BY (ended_at IS NULL) DESC,last_seen_at DESC,id DESC) AS rank
                FROM ({VISIBLE}) visible WHERE actor_id=ANY($9::text[]))
            SELECT * FROM ranked WHERE ended_at IS NULL OR rank=1 ORDER BY actor_id,rank LIMIT $10
        """, *params, user_ids, AGGREGATE_LIMIT + 1)
        grouped = defaultdict(list)
        complete = len(rows) <= AGGREGATE_LIMIT
        for row in rows[:AGGREGATE_LIMIT]:
            grouped[row["actor_id"]].append(session_state(row, now, policy_values(body)))
        page["items"] = [{"user_id": actor, **aggregate_states(grouped[actor], complete=complete)} for actor in user_ids]
        return jsonable_encoder({
            **envelope(arguments["project_id"], principal, now), "scope": scope, "policy_version": version, "policy": body,
            "coverage": "page", "aggregation_scope": "authorized_open_sessions_or_latest_ended",
            **page,
        })
