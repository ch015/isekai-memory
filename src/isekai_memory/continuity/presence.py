"""Authenticated presence mutations; no work lease or checkpoint mutations."""

import hmac
from dataclasses import asdict
from datetime import timedelta
from uuid import UUID

from fastapi.encoders import jsonable_encoder

from isekai_memory.continuity.common import (
    CLASSIFICATIONS,
    conflict,
    digest,
    event,
    fail,
    invalid,
    receipt,
    token_digest,
    transaction,
)
from isekai_memory.continuity.overview import read_transaction
from isekai_memory.continuity.presence_state import PresencePolicy, next_times
from isekai_memory.server.auth import authorize_tool

DEFAULT_POLICY = {"enabled": False, **asdict(PresencePolicy()), "retention_hours": 168}
MAX_OPEN_PER_USER = 64
MAX_LIVE_PER_PROJECT = 10000
MAX_REGISTRATIONS_PER_MINUTE = 10
STATE_FIELDS = ("reported_state", "observation_scope", "state_observation_available", "active_work_count", "work_unit_id")


def policy_values(body):
    return PresencePolicy(**{key: body[key] for key in ("heartbeat_seconds", "stale_after_seconds", "idle_after_seconds")})


async def policy(conn, project):
    row = await conn.fetchrow("SELECT version,policy FROM memory_presence_policies WHERE project_id=$1", project)
    return (row["version"], row["policy"]) if row else (0, dict(DEFAULT_POLICY))


def envelope(project, principal, now):
    return {"contract_version": 1, "project_id": project, "actor_id": principal.user_id,
            "observed_at": now, "cache_policy": "no_store"}


def report_fingerprint(arguments):
    return digest({key: token_digest(value) if key == "session_token" else value for key, value in arguments.items()})


def response(row, project, principal, now, version, body, *, replayed=False):
    return jsonable_encoder({**envelope(project, principal, now), "session_id": row["id"],
                             "sequence": row["sequence"], "state_sequence": row["state_sequence"],
                             "state_fingerprint": digest(jsonable_encoder({key: row[key] for key in STATE_FIELDS})),
                             "last_seen_at": row["last_seen_at"], "ended_at": row["ended_at"],
                             "policy_version": version, "policy": body, "replayed": replayed})


async def policy_get(arguments, *, principal):
    authorize_tool(principal, "memory_presence_policy_get", arguments)
    async with read_transaction() as conn:
        version, body = await policy(conn, arguments["project_id"])
        return jsonable_encoder({**envelope(arguments["project_id"], principal, await conn.fetchval("SELECT transaction_timestamp()")),
                                 "configured": version > 0, "policy_version": version, "policy": body})


async def policy_set(arguments, *, principal):
    authorize_tool(principal, "memory_presence_policy_set", arguments)
    project, body = arguments["project_id"], arguments["policy"]
    try:
        policy_values(body)
    except (ValueError, TypeError) as exc:
        raise invalid("Presence thresholds are invalid") from exc
    async with transaction(project) as conn:
        replay = await receipt(conn, arguments, principal, "presence_policy_set")
        if replay:
            return replay
        version, _ = await policy(conn, project)
        if version != arguments["expected_version"]:
            raise conflict()
        await conn.execute("""
            INSERT INTO memory_presence_policies(project_id,version,policy,updated_by) VALUES($1,$2,$3,$4)
            ON CONFLICT(project_id) DO UPDATE SET version=EXCLUDED.version,policy=EXCLUDED.policy,
                updated_by=EXCLUDED.updated_by,updated_at=clock_timestamp()
        """, project, version + 1, body, principal.user_id)
        await event(conn, project, principal.user_id, "presence_policy_set", project,
                    {"version": version + 1, "policy": body, "reason": arguments["reason"]})
        return await receipt(conn, arguments, principal, "presence_policy_set", {"project_id": project, "version": version + 1})


async def _owned(conn, arguments, principal):
    row = await conn.fetchrow("SELECT * FROM memory_presence_sessions WHERE id=$1 AND project_id=$2 AND actor_id=$3",
                              arguments["session_id"], arguments["project_id"], principal.user_id)
    if row is None or not hmac.compare_digest(row["session_token_digest"], token_digest(arguments["session_token"])):
        raise fail("Presence session is unavailable", "MEM-PRESENCE-0001", 404)
    if row["retired_at"] is not None:
        raise fail("Presence session has been retired; use a new observer instance", "MEM-PRESENCE-0002", 410)
    return row


async def register(arguments, *, principal):
    authorize_tool(principal, "memory_presence_register", arguments)
    project = arguments["project_id"]
    fingerprint = report_fingerprint(arguments)
    async with transaction(project) as conn:
        now = await conn.fetchval("SELECT clock_timestamp()")
        version, body = await policy(conn, project)
        row = await conn.fetchrow("SELECT * FROM memory_presence_sessions WHERE project_id=$1 AND actor_id=$2 AND client_instance_id=$3",
                                  project, principal.user_id, arguments["client_instance_id"])
        if row:
            if row["register_digest"] != fingerprint:
                raise conflict("Observer instance is bound to a different registration")
            if row["retired_at"] is not None:
                raise fail("Observer instance is retired", "MEM-PRESENCE-0002", 410)
            return response(row, project, principal, now, version, body, replayed=True)
        if not body["enabled"]:
            raise fail("Project observation is disabled", "MEM-PRESENCE-0003", 409)
        limits = await conn.fetchrow("""
            SELECT count(*) FILTER(WHERE retired_at IS NULL) AS live,
                count(*) FILTER(WHERE actor_id=$2 AND retired_at IS NULL AND ended_at IS NULL) AS owned,
                count(*) FILTER(WHERE actor_id=$2 AND created_at>$3::timestamptz-interval '1 minute') AS recent
            FROM memory_presence_sessions WHERE project_id=$1
        """, project, principal.user_id, now)
        if (limits["live"] >= MAX_LIVE_PER_PROJECT or limits["owned"] >= MAX_OPEN_PER_USER
                or limits["recent"] >= MAX_REGISTRATIONS_PER_MINUTE):
            raise fail("Observation registration limit reached", "MEM-PRESENCE-0004", 429)
        classification = arguments["classification"]
        parent_id = arguments.get("parent_session_id")
        if parent_id is not None:
            parent = await conn.fetchrow("SELECT classification FROM memory_presence_sessions WHERE id=$1 AND project_id=$2 "
                                         "AND actor_id=$3 AND ended_at IS NULL AND retired_at IS NULL", parent_id, project, principal.user_id)
            if parent is None:
                raise fail("Parent observation is unavailable", "MEM-PRESENCE-0001", 404)
            classification = max((classification, parent["classification"]), key=CLASSIFICATIONS.index)
        row = await conn.fetchrow("""
            INSERT INTO memory_presence_sessions(project_id,actor_id,client_instance_id,session_token_digest,register_digest,
                host_kind,session_kind,parent_session_id,classification,created_at,last_seen_at,state_since_at)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$10,$10) RETURNING *
        """, project, principal.user_id, arguments["client_instance_id"], token_digest(arguments["session_token"]), fingerprint,
            arguments["host_kind"], arguments["session_kind"], parent_id, classification, now)
        await event(conn, project, principal.user_id, "presence_register", row["id"], {"session_kind": row["session_kind"]})
        return response(row, project, principal, now, version, body)


async def _classification(conn, row, arguments, principal, now):
    values = [row["classification"], arguments["classification"]]
    unit_id = arguments["work_unit_id"]
    if unit_id:
        unit = await conn.fetchrow("""
            SELECT b.classification FROM memory_continuity_units u
            JOIN memory_continuity_bundles b ON (b.id,b.project_id)=(u.bundle_id,u.project_id)
            WHERE u.id=$1 AND u.project_id=$2 AND $3=ANY(u.assignee_user_ids)
                AND b.revoked_at IS NULL AND b.expires_at>$4 AND EXISTS(
                    SELECT 1 FROM memory_continuity_deliveries d
                    WHERE d.bundle_id=b.id AND d.project_id=b.project_id AND d.recipient_user_id=$3 AND d.revoked_at IS NULL)
        """, unit_id, arguments["project_id"], principal.user_id, now)
        if unit is None:
            raise fail("Work observation binding is unavailable", "MEM-PRESENCE-0001", 404)
        values.append(unit["classification"])
    checkpoint_id = arguments["checkpoint_id"]
    if checkpoint_id:
        checkpoint = await conn.fetchrow("SELECT classification FROM memory_checkpoints WHERE id=$1 AND project_id=$2 "
                                         "AND from_user=$3 AND forgotten_at IS NULL AND expires_at>$4",
                                         checkpoint_id, arguments["project_id"], principal.user_id, now)
        if checkpoint is None:
            raise fail("Checkpoint observation binding is unavailable", "MEM-PRESENCE-0001", 404)
        values.append(checkpoint["classification"])
    if row["parent_session_id"]:
        parent = await conn.fetchval("SELECT classification FROM memory_presence_sessions WHERE id=$1", row["parent_session_id"])
        values.append(parent)
    return max(values, key=CLASSIFICATIONS.index)


def _validate_report(arguments):
    state, active = arguments["reported_state"], arguments["active_work_count"]
    available = arguments["state_observation_available"] and arguments["observation_scope"] != "partial"
    if ((state != "unknown" and not available) or (state == "running" and active == 0)
            or (state == "idle" and active != 0)):
        raise invalid("Observed work state and coverage are inconsistent")


async def heartbeat(arguments, *, principal):
    authorize_tool(principal, "memory_presence_heartbeat", arguments)
    _validate_report(arguments)
    project = arguments["project_id"]
    fingerprint = report_fingerprint(arguments)
    async with transaction(project) as conn:
        row = await _owned(conn, arguments, principal)
        now = await conn.fetchval("SELECT clock_timestamp()")
        version, body = await policy(conn, project)
        if row["ended_at"] is not None:
            raise conflict("Ended observations cannot be refreshed")
        if arguments["sequence"] == row["sequence"] and fingerprint == row["report_digest"]:
            return response(row, project, principal, now, version, body, replayed=True)
        if arguments["sequence"] <= row["sequence"]:
            raise conflict("Presence sequence is stale or conflicts")
        if not body["enabled"]:
            raise fail("Project observation is disabled", "MEM-PRESENCE-0003", 409)
        if arguments["observation_scope"] not in {row["session_kind"], "partial"}:
            raise invalid("Report scope must match the registered observer kind")
        reported_fields = {key: arguments[key] for key in STATE_FIELDS}
        if reported_fields["work_unit_id"] is not None:
            reported_fields["work_unit_id"] = UUID(reported_fields["work_unit_id"])
        changed = any(reported_fields[key] != row[key] for key in STATE_FIELDS)
        if arguments["state_sequence"] != row["state_sequence"] + int(changed):
            raise conflict("State sequence must advance only for an observed state change")
        classification = await _classification(conn, row, arguments, principal, now)
        previous_classification = row["classification"]
        times = next_times(row, arguments["reported_state"], now, policy_values(body), state_changed=changed)
        resumed = now < row["last_seen_at"] or (now-row["last_seen_at"]).total_seconds() >= body["stale_after_seconds"]
        row = await conn.fetchrow("""
            UPDATE memory_presence_sessions SET sequence=$2,state_sequence=$3,report_digest=$4,reported_policy_version=$5,
                reported_state=$6,observation_scope=$7,state_observation_available=$8,active_work_count=$9,
                work_unit_id=$10,checkpoint_id=$11,classification=$12,last_seen_at=$13,state_since_at=$14,idle_since_at=$15
            WHERE id=$1 RETURNING *
        """, row["id"], arguments["sequence"], arguments["state_sequence"], fingerprint, arguments["policy_version"],
            arguments["reported_state"], arguments["observation_scope"], arguments["state_observation_available"],
            arguments["active_work_count"], arguments["work_unit_id"], arguments["checkpoint_id"], classification,
            now, times["state_since_at"], times["idle_since_at"])
        if changed or resumed or classification != previous_classification:
            await event(conn, project, principal.user_id, "presence_state", row["id"],
                        {"sequence": row["sequence"], "resumed": resumed, "previous_classification": previous_classification})
        return response(row, project, principal, now, version, body)


async def end(arguments, *, principal):
    authorize_tool(principal, "memory_presence_end", arguments)
    project = arguments["project_id"]
    fingerprint = report_fingerprint(arguments)
    async with transaction(project) as conn:
        row = await _owned(conn, arguments, principal)
        now = await conn.fetchval("SELECT clock_timestamp()")
        version, body = await policy(conn, project)
        if row["ended_at"] is not None:
            if arguments["sequence"] == row["sequence"] and fingerprint == row["report_digest"]:
                return response(row, project, principal, now, version, body, replayed=True)
            raise conflict("Observation already ended")
        if arguments["sequence"] <= row["sequence"]:
            raise conflict("Presence sequence is stale")
        row = await conn.fetchrow("UPDATE memory_presence_sessions SET sequence=$2,report_digest=$3,ended_at=$4 WHERE id=$1 RETURNING *",
                                  row["id"], arguments["sequence"], fingerprint, now)
        await event(conn, project, principal.user_id, "presence_end", row["id"], {"sequence": row["sequence"]})
        return response(row, project, principal, now, version, body)


async def prune(arguments, *, principal):
    authorize_tool(principal, "memory_presence_prune", arguments)
    project = arguments["project_id"]
    async with transaction(project) as conn:
        replay = await receipt(conn, arguments, principal, "presence_prune")
        if replay:
            return replay
        now = await conn.fetchval("SELECT clock_timestamp()")
        _, body = await policy(conn, project)
        cutoff = now - timedelta(hours=body["retention_hours"])
        rows = await conn.fetch("""
            WITH candidates AS (
                SELECT id FROM memory_presence_sessions WHERE project_id=$1 AND retired_at IS NULL
                    AND COALESCE(ended_at,last_seen_at)<$2 ORDER BY last_seen_at,id LIMIT $3)
            UPDATE memory_presence_sessions s SET retired_at=$4,ended_at=COALESCE(s.ended_at,$4),
                host_kind='unknown',reported_state='unknown',observation_scope='partial',
                state_observation_available=false,active_work_count=0,work_unit_id=NULL,checkpoint_id=NULL,idle_since_at=NULL
            FROM candidates c WHERE s.id=c.id RETURNING s.id
        """, project, cutoff, arguments.get("limit", 100), now)
        await event(conn, project, principal.user_id, "presence_prune", project, {"retired": len(rows), "reason": arguments["reason"]})
        return await receipt(conn, arguments, principal, "presence_prune", {"project_id": project, "retired": len(rows)})
