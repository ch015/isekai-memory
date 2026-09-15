"""Read-only authorized whole-set usage aggregates and separately paged metadata."""
from collections import Counter, defaultdict
from datetime import timedelta

from fastapi.encoders import jsonable_encoder

from isekai_memory.continuity.common import CLASSIFICATIONS, digest, fail, invalid, is_admin
from isekai_memory.continuity.overview import read_transaction
from isekai_memory.continuity.presence import envelope
from isekai_memory.continuity.usage import policy
from isekai_memory.continuity.usage_metrics import (
    FIELDS,
    MAX_AGGREGATE_UNITS,
    Metrics,
    aggregate,
    normalize,
    unavailable,
)
from isekai_memory.continuity.usage_periods import period
from isekai_memory.experience import pagination
from isekai_memory.server.auth import authorize_tool

VISIBLE = """
    SELECT s.id,s.project_id,s.actor_id,s.execution_attempt_id,s.meter_epoch,s.classification,
        s.host_kind,s.host_version,s.adapter_version,s.provider,s.model_id,s.created_at,
        s.sequence,s.metrics,s.coverage,s.completion_state,s.first_received_at,s.last_received_at,
        COALESCE(s.bucket_at,s.created_at) AS bucket_at,COALESCE(s.bucket_basis,'provisional') AS bucket_basis,
        s.finalized_at,
        CASE WHEN EXISTS(SELECT 1 FROM memory_usage_sessions p WHERE p.id=s.parent_session_id
            AND p.retired_at IS NULL AND p.classification=ANY($4::text[])) THEN s.parent_session_id END AS parent_session_id,
        CASE WHEN EXISTS(SELECT 1 FROM memory_continuity_units u
            JOIN memory_continuity_bundles b ON b.id=u.bundle_id WHERE u.id=s.work_unit_id
            AND b.revoked_at IS NULL AND b.expires_at>$11 AND b.classification=ANY($4::text[]))
            THEN s.work_unit_id END AS work_unit_id
    FROM memory_usage_sessions s WHERE s.project_id=$1 AND ($3::boolean OR s.actor_id=$2)
        AND s.classification=ANY($4::text[]) AND s.retired_at IS NULL
        AND COALESCE(s.bucket_at,s.created_at)>=$5 AND COALESCE(s.bucket_at,s.created_at)<$6
        AND COALESCE(s.bucket_at,s.created_at)>=$7
        AND ($8::text IS NULL OR s.actor_id=$8) AND ($9::text IS NULL OR s.host_kind=$9)
        AND ($10::text IS NULL OR s.model_id=$10)
"""


def scope_for(arguments, principal):
    scope = {"kind": arguments.get("scope", "mine"), "max_classification": arguments.get("max_classification", "internal"),
             "user_id": arguments.get("user_id"), "host_kind": arguments.get("host_kind"),
             "model_id": arguments.get("model_id"), "work_unit_id": arguments.get("work_unit_id")}
    if scope["kind"] == "project" and not is_admin(principal):
        raise fail("Project usage requires admin authority", "MEM-USAGE-0005", 403)
    if scope["kind"] == "mine" and scope["user_id"] not in (None, principal.user_id):
        raise fail("This usage user filter is outside your scope", "MEM-USAGE-0005", 403)
    return scope


def prepare(arguments, principal, scope, now, body):
    try:
        window = period(arguments, now, body["timezone"])
    except (KeyError, ValueError, TypeError, OverflowError) as exc:
        raise invalid("Invalid bounded usage period or timezone") from exc
    allowed = CLASSIFICATIONS[:CLASSIFICATIONS.index(scope["max_classification"])+1]
    parameters = (arguments["project_id"], principal.user_id, scope["kind"] == "project", allowed,
                  window["start_at"], window["end_at"], now-timedelta(days=body["retention_days"]),
                  scope["user_id"], scope["host_kind"], scope["model_id"], now, scope["work_unit_id"])
    # today/week end advances on polls; bind cursors to local start, not moving now.
    key = ["usage-v1", arguments["project_id"], principal.user_id, ",".join(sorted(principal.scopes)), str(principal.local),
           digest(scope), window["kind"], window["timezone"], window["start_at"].isoformat(),
           window["end_at"].isoformat() if window["kind"] == "custom" else "live", digest(body)]
    return window, parameters, key


FILTERED = f"SELECT * FROM ({VISIBLE}) authorized WHERE ($12::uuid IS NULL OR work_unit_id=$12)"


def metrics(row):
    return Metrics.from_dict(row["metrics"]) if row["metrics"] is not None else normalize(dict.fromkeys(FIELDS, unavailable("awaiting_result")))


def metadata(row):
    return {**dict(row), "metrics": metrics(row).as_dict(), "observation_scope": "exclusive_run", "semantics_version": 1}


def summary_values(rows):
    values = aggregate([metrics(row) for row in rows])
    return {**values, "coverage_scope": "authorized_retained_observed_runs_only",
            "in_progress_runs": sum(row["completion_state"] == "in_progress" for row in rows),
            "partial_runs": sum(row["coverage"] == "partial" for row in rows),
            "bucket_basis_counts": dict(Counter(row["bucket_basis"] for row in rows)),
            "last_received_at": max((row["last_received_at"] for row in rows if row["last_received_at"]), default=None),
            "revision": digest([(str(row["id"]), row["sequence"]) for row in rows]),
            "outside_core_usage": "unobserved", "billing_verified": False}


async def listing(arguments, *, principal):
    authorize_tool(principal, "memory_usage_list", arguments)
    scope = scope_for(arguments, principal)
    async with read_transaction() as conn:
        now = await conn.fetchval("SELECT transaction_timestamp()")
        version, body = await policy(conn, arguments["project_id"])
        window, params, key = prepare(arguments, principal, scope, now, body)
        at, row_id = pagination.decode(arguments.get("cursor"), key)
        limit = arguments.get("limit", 20)
        rows = await conn.fetch(f"SELECT * FROM ({FILTERED}) filtered "
                                "WHERE ($13::timestamptz IS NULL OR (created_at,id)<($13,$14::uuid)) "
                                "ORDER BY created_at DESC,id DESC LIMIT $15", *params, at, row_id, limit+1)
        page = pagination.page([metadata(row) for row in rows], limit, key)
        return jsonable_encoder({**envelope(arguments["project_id"], principal, now), "scope": scope, "period": window,
                                 "policy_version": version, "policy": body, "coverage": "page", **page})


def alerts(rows, arguments, scope, window, version, body):
    # Stable level identities are read-only. A consumer may suppress repeats by id;
    # summary polling itself never inserts notification or acknowledgement rows.
    if window["kind"] != "today":
        return []
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["actor_id"]].append(row)
    candidates = [(actor, group, body["user_alert_tokens"]) for actor, group in grouped.items()]
    unfiltered = all(scope[key] is None for key in ("user_id", "host_kind", "model_id", "work_unit_id"))
    if scope["kind"] == "project" and unfiltered:
        candidates.append((None, rows, body["project_alert_tokens"]))
    if not unfiltered:
        return []
    result = []
    for actor, group, threshold in candidates:
        total = aggregate([metrics(row) for row in group])["reported"]["total_tokens"]["value"]
        if threshold is not None and total is not None and total >= threshold:
            identity = [arguments["project_id"], actor, version, threshold, window["start_at"].isoformat(),
                        window["timezone"], scope["max_classification"]]
            result.append({"id": digest(identity), "kind": "soft_threshold", "user_id": actor,
                           "reported_total_tokens": total, "threshold_tokens": threshold,
                           "action": "inform_only", "incomplete_observation_warning": True})
    return result


async def summary(arguments, *, principal):
    authorize_tool(principal, "memory_usage_summary", arguments)
    scope = scope_for(arguments, principal)
    async with read_transaction() as conn:
        now = await conn.fetchval("SELECT transaction_timestamp()")
        version, body = await policy(conn, arguments["project_id"])
        window, params, _ = prepare(arguments, principal, scope, now, body)
        rows = await conn.fetch(f"{FILTERED} ORDER BY id LIMIT $13", *params, MAX_AGGREGATE_UNITS+1)
        if len(rows) > MAX_AGGREGATE_UNITS:
            raise fail("Narrow usage period or filters; complete aggregation exceeds the bounded limit", "MEM-USAGE-0004", 429)
        group_by = arguments.get("group_by", "none")
        field = {"user": "actor_id", "host": "host_kind", "model": "model_id", "work": "work_unit_id"}.get(group_by)
        grouped = defaultdict(list)
        if field:
            for row in rows:
                grouped[str(row[field]) if row[field] is not None else "unlinked"].append(row)
        if len(grouped) > 1000:
            raise fail("Too many usage groups; narrow period or filters", "MEM-USAGE-0004", 429)
        return jsonable_encoder({**envelope(arguments["project_id"], principal, now), "scope": scope, "period": window,
                                 "policy_version": version, "policy": body, "aggregation_scope": "whole_authorized_retained_set",
                                 "summary": summary_values(rows), "group_by": group_by,
                                 "groups": [{"key": key, **summary_values(group)} for key, group in sorted(grouped.items())],
                                 "alerts": alerts(rows, arguments, scope, window, version, body)})
