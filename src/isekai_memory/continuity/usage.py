"""Actor-bound usage mutations, bounded immutable receipts and absolute latest values."""
import hmac
from datetime import timedelta

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
from isekai_memory.continuity.presence import envelope
from isekai_memory.continuity.usage_metrics import Metrics, validate_revision
from isekai_memory.continuity.usage_periods import source_time, timestamp, timezone
from isekai_memory.continuity.work import active, locate
from isekai_memory.server.auth import authorize_tool

DEFAULT_POLICY = {"enabled": False, "retention_days": 30, "late_report_hours": 168,
                  "timezone": "UTC", "project_alert_tokens": None, "user_alert_tokens": None}
MAX_LIVE = 10000
MAX_IDENTITIES = 200000
MAX_RECEIPTS = 200000
MAX_REGISTER_MINUTE = 10
MAX_REPORT_MINUTE = 120
MAX_REVISIONS = 512


async def policy(conn, project):
    row = await conn.fetchrow("SELECT version,policy FROM memory_usage_policies WHERE project_id=$1", project)
    return (row["version"], row["policy"]) if row else (0, dict(DEFAULT_POLICY))


async def policy_get(arguments, *, principal):
    authorize_tool(principal, "memory_usage_policy_get", arguments)
    async with read_transaction() as conn:
        version, body = await policy(conn, arguments["project_id"])
        return jsonable_encoder({**envelope(arguments["project_id"], principal, await conn.fetchval("SELECT transaction_timestamp()")),
                                 "configured": version > 0, "policy_version": version, "policy": body})


async def policy_set(arguments, *, principal):
    authorize_tool(principal, "memory_usage_policy_set", arguments)
    project, body = arguments["project_id"], arguments["policy"]
    try:
        timezone(body["timezone"])
    except ValueError as exc:
        raise invalid("Invalid usage policy timezone") from exc
    async with transaction(project) as conn:
        replay = await receipt(conn, arguments, principal, "usage_policy_set")
        if replay:
            return replay
        version, _ = await policy(conn, project)
        if version != arguments["expected_version"]:
            raise conflict()
        await conn.execute("""
            INSERT INTO memory_usage_policies(project_id,version,policy,updated_by) VALUES($1,$2,$3,$4)
            ON CONFLICT(project_id) DO UPDATE SET version=EXCLUDED.version,policy=EXCLUDED.policy,
                updated_by=EXCLUDED.updated_by,updated_at=clock_timestamp()
        """, project, version + 1, body, principal.user_id)
        await event(conn, project, principal.user_id, "usage_policy_set", project,
                    {"version": version + 1, "policy": body, "reason": arguments["reason"]})
        return await receipt(conn, arguments, principal, "usage_policy_set", {"project_id": project, "version": version + 1})


def fingerprint(arguments):
    material = {**arguments, "session_token": token_digest(arguments["session_token"])}
    if material.get("work_binding"):
        material["work_binding"] = {**material["work_binding"], "claim_token": token_digest(material["work_binding"]["claim_token"])}
    return digest(material)


def unavailable():
    return fail("Usage reporter is unavailable in this scope", "MEM-USAGE-0001", 404)


def limited():
    return fail("Usage ledger limit reached; no report was silently dropped", "MEM-USAGE-0004", 429)


def registration(row, principal, version, body, *, replayed=False):
    return jsonable_encoder({**envelope(row["project_id"], principal, row["created_at"]),
                             "session_id": row["id"], "execution_attempt_id": row["execution_attempt_id"],
                             "meter_epoch": row["meter_epoch"], "accepts_until": row["accepts_until"],
                             "policy_version": version, "policy": body, "replayed": replayed})


async def register(arguments, *, principal):
    authorize_tool(principal, "memory_usage_register", arguments)
    project, identity = arguments["project_id"], fingerprint(arguments)
    async with transaction(project) as conn:
        now = await conn.fetchval("SELECT clock_timestamp()")
        version, body = await policy(conn, project)
        existing = await conn.fetchrow("SELECT * FROM memory_usage_sessions WHERE project_id=$1 AND actor_id=$2 AND execution_attempt_id=$3",
                                       project, principal.user_id, arguments["execution_attempt_id"])
        if existing:
            if existing["register_digest"] != identity:
                raise conflict("This attempt already has a different observer or epoch")
            if existing["retired_at"] is not None:
                raise fail("Usage attempt is retired and cannot be resurrected", "MEM-USAGE-0002", 410)
            return registration(existing, principal, version, body, replayed=True)
        if not body["enabled"]:
            raise fail("Usage collection is disabled", "MEM-USAGE-0003", 409)
        limits = await conn.fetchrow("""
            SELECT count(*) AS identities,count(*) FILTER(WHERE retired_at IS NULL) AS live,
                count(*) FILTER(WHERE actor_id=$2 AND created_at>$3::timestamptz-interval '1 minute') AS recent
            FROM memory_usage_sessions WHERE project_id=$1
        """, project, principal.user_id, now)
        if limits["identities"] >= MAX_IDENTITIES or limits["live"] >= MAX_LIVE or limits["recent"] >= MAX_REGISTER_MINUTE:
            raise limited()
        classification = arguments["classification"]
        parent_id = arguments["parent_session_id"]
        if parent_id:
            parent = await conn.fetchrow("SELECT classification FROM memory_usage_sessions WHERE id=$1 AND project_id=$2 "
                                         "AND actor_id=$3 AND retired_at IS NULL", parent_id, project, principal.user_id)
            if parent is None:
                raise unavailable()
            classification = max((classification, parent["classification"]), key=CLASSIFICATIONS.index)
        binding = arguments["work_binding"]
        if binding:
            # Bind while this exact private lease is active. Late reports retain this historic actor,
            # even after reassignment; they never reacquire or extend that lease.
            work_args = {"project_id": project, "unit_id": binding["work_unit_id"]}
            unit, bundle = await locate(conn, work_args, principal)
            active(unit, binding, principal.user_id, now)
            classification = max((classification, bundle["classification"]), key=CLASSIFICATIONS.index)
        row = await conn.fetchrow("""
            INSERT INTO memory_usage_sessions(project_id,actor_id,execution_attempt_id,meter_epoch,session_token_digest,
                register_digest,host_kind,host_version,adapter_version,provider,model_id,classification,parent_session_id,
                work_unit_id,claim_generation,created_at,accepts_until)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17) RETURNING *
        """, project, principal.user_id, arguments["execution_attempt_id"], arguments["meter_epoch"],
            token_digest(arguments["session_token"]), identity, arguments["host_kind"], arguments["host_version"],
            arguments["adapter_version"], arguments["provider"], arguments["model_id"], classification, parent_id,
            binding["work_unit_id"] if binding else None, binding["claim_generation"] if binding else None, now,
            now + timedelta(hours=body["late_report_hours"]))
        return registration(row, principal, version, body)


async def owned(conn, arguments, principal):
    row = await conn.fetchrow("SELECT * FROM memory_usage_sessions WHERE id=$1 AND project_id=$2 AND actor_id=$3",
                              arguments["session_id"], arguments["project_id"], principal.user_id)
    if row is None or not hmac.compare_digest(row["session_token_digest"], token_digest(arguments["session_token"])):
        raise unavailable()
    if row["retired_at"] is not None:
        raise fail("Usage reporter was retired", "MEM-USAGE-0002", 410)
    return row


def report_receipt(row, principal, *, replayed=False):
    return jsonable_encoder({**envelope(row["project_id"], principal, row["received_at"]),
                             "session_id": row["session_id"], "sequence": row["sequence"],
                             "bucket_at": row["bucket_at"], "completion_state": row["completion_state"],
                             "replayed": replayed})


async def report(arguments, *, principal):
    authorize_tool(principal, "memory_usage_report", arguments)
    try:
        current = Metrics.from_dict(arguments["metrics"])
        if arguments["coverage"] == "complete" and current.as_dict()["total_tokens"]["value"] is None:
            raise ValueError("Complete scope coverage needs a known total")
    except (TypeError, ValueError) as exc:
        raise invalid("Invalid normalized usage counters") from exc
    project, identity = arguments["project_id"], fingerprint(arguments)
    async with transaction(project) as conn:
        row = await owned(conn, arguments, principal)
        sequence = arguments["sequence"]
        previous = await conn.fetchrow("SELECT * FROM memory_usage_receipts WHERE session_id=$1 AND sequence=$2", row["id"], sequence)
        if previous:
            if previous["request_digest"] != identity:
                raise conflict("Same usage sequence has different content")
            return report_receipt(previous, principal, replayed=True)
        if sequence <= row["sequence"]:
            raise conflict("Unrecognized older usage revision")
        now = await conn.fetchval("SELECT clock_timestamp()")
        _, body = await policy(conn, project)
        if not body["enabled"]:
            raise fail("Usage collection is disabled", "MEM-USAGE-0003", 409)
        if now > min(row["accepts_until"], row["created_at"] + timedelta(hours=body["late_report_hours"])):
            raise fail("Usage late-report window has expired", "MEM-USAGE-0002", 410)
        if row["metrics"] is not None:
            try:
                validate_revision(Metrics.from_dict(row["metrics"]), current)
            except ValueError as exc:
                raise conflict("Usage counters cannot reset or downgrade in this epoch") from exc
        if row["completion_state"] == "final" and arguments["completion_state"] != "final":
            raise conflict("Final usage cannot return to in-progress")
        if row["coverage"] == "complete" and arguments["coverage"] != "complete":
            raise conflict("Complete usage coverage cannot regress")
        limits = await conn.fetchrow("""
            SELECT count(*) AS total,count(*) FILTER(WHERE r.session_id=$2) AS revisions,
                count(*) FILTER(WHERE s.actor_id=$3 AND r.received_at>$4::timestamptz-interval '1 minute') AS recent
            FROM memory_usage_receipts r JOIN memory_usage_sessions s ON s.id=r.session_id WHERE r.project_id=$1
        """, project, row["id"], principal.user_id, now)
        if limits["total"] >= MAX_RECEIPTS or limits["revisions"] >= MAX_REVISIONS or limits["recent"] >= MAX_REPORT_MINUTE:
            raise limited()
        first = row["first_received_at"] or now
        source = timestamp(arguments["source_occurred_at"]) if arguments["source_occurred_at"] else None
        final_at = row["finalized_at"]
        if final_at is not None:
            if source != row["source_occurred_at"]:
                raise conflict("Final usage attribution is pinned")
            bucket, basis = row["bucket_at"], row["bucket_basis"]
        elif arguments["completion_state"] == "final":
            # Unknown run end is received now; do not assign a long run to its first partial day.
            bucket, basis = source_time(arguments["source_occurred_at"], now, body["late_report_hours"], now)
            final_at = now
        else:
            bucket, basis = first, "provisional"
        await conn.execute("""
            UPDATE memory_usage_sessions SET sequence=$2,metrics=$3,coverage=$4,completion_state=$5,
                first_received_at=$6,last_received_at=$7,bucket_at=$8,bucket_basis=$9,source_occurred_at=$10,finalized_at=$11
            WHERE id=$1
        """, row["id"], sequence, current.as_dict(), arguments["coverage"], arguments["completion_state"],
            first, now, bucket, basis, source, final_at)
        received = await conn.fetchrow("""
            INSERT INTO memory_usage_receipts(session_id,project_id,sequence,request_digest,received_at,bucket_at,completion_state)
            VALUES($1,$2,$3,$4,$5,$6,$7) RETURNING *
        """, row["id"], project, sequence, identity, now, bucket, arguments["completion_state"])
        if row["completion_state"] != "final" and arguments["completion_state"] == "final":
            await event(conn, project, principal.user_id, "usage_finalized", row["id"], {"sequence": sequence})
        return report_receipt(received, principal)


async def prune(arguments, *, principal):
    authorize_tool(principal, "memory_usage_prune", arguments)
    project = arguments["project_id"]
    async with transaction(project) as conn:
        replay = await receipt(conn, arguments, principal, "usage_prune")
        if replay:
            return replay
        now = await conn.fetchval("SELECT clock_timestamp()")
        _, body = await policy(conn, project)
        rows = await conn.fetch("""
            WITH candidates AS (
                SELECT id FROM memory_usage_sessions WHERE project_id=$1 AND retired_at IS NULL
                    AND COALESCE(bucket_at,created_at)<$2 ORDER BY created_at,id LIMIT $3)
            UPDATE memory_usage_sessions s SET retired_at=$4,host_kind='unknown',host_version='unknown',
                adapter_version='unknown',provider='unknown',model_id='unknown',metrics=NULL
            FROM candidates c WHERE s.id=c.id RETURNING s.id
        """, project, now-timedelta(days=body["retention_days"]), arguments.get("limit", 100), now)
        await event(conn, project, principal.user_id, "usage_prune", project, {"retired": len(rows), "reason": arguments["reason"]})
        return await receipt(conn, arguments, principal, "usage_prune", {"project_id": project, "retired": len(rows)})
