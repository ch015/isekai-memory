"""Atomic fan-out and admin reassignment, independent from recipient intake."""

from datetime import timedelta

from fastapi.encoders import jsonable_encoder

from isekai_memory.continuity import checkpoints, policies
from isekai_memory.continuity.common import (
    ceiling,
    conflict,
    eligible,
    event,
    fail,
    invalid,
    is_admin,
    policy,
    receipt,
    require_admin,
    transaction,
)

LEGACY_FIELDS = ("project_id", "unit_id", "phase_attempt_id", "phase_id", "from_user", "result_status",
                 "classification", "task_summary", "passed_checks", "artifacts_produced", "handoff_note",
                 "task_envelope", "result_envelope", "context_digest", "raw_output", "lock_snapshot_digest", "envelope_digest")


def handoff_payload(row):
    result = {key: row[key] for key in LEGACY_FIELDS}
    if row["handoff_version"] == 2:
        result.update({key: row[key] for key in ("handoff_version", "recipient_user_id", "continuation", "continuation_digest")})
    return result


def validate_units(units, recipients):
    keys = set()
    for unit in units:
        if unit["key"] in keys or not set(unit["assignee_user_ids"]) <= set(recipients):
            raise invalid("Work keys must be unique and assignees must be active recipients")
        keys.add(unit["key"])


async def bundle(conn, project, bundle_id, *, retained=True):
    row = await conn.fetchrow("SELECT * FROM memory_continuity_bundles WHERE project_id=$1 AND id=$2::uuid", project, bundle_id)
    if row is None or (retained and (row["revoked_at"] is not None or row["expires_at"] <= await conn.fetchval("SELECT clock_timestamp()"))):
        raise fail()
    return row


async def own_delivery(conn, project, delivery_id, actor):
    row = await conn.fetchrow("SELECT * FROM memory_continuity_deliveries WHERE project_id=$1 AND id=$2::uuid "
                              "AND recipient_user_id=$3 AND revoked_at IS NULL", project, delivery_id, actor)
    if not row:
        raise fail()
    parent = await bundle(conn, project, row["bundle_id"])
    return row, parent


async def _insert_delivery(conn, project, bundle_id, recipient, version):
    await conn.execute("INSERT INTO memory_continuity_deliveries(project_id,bundle_id,recipient_user_id,routing_version) VALUES($1,$2,$3,$4)",
                       project, bundle_id, recipient, version)


async def _insert_unit(conn, project, bundle_id, unit):
    await conn.execute("INSERT INTO memory_continuity_units(project_id,bundle_id,unit_key,summary,assignee_user_ids) VALUES($1,$2,$3,$4,$5)",
                       project, bundle_id, unit["key"], unit["summary"], sorted(unit["assignee_user_ids"]))


async def publish(arguments, *, principal):
    project = arguments["project_id"]
    async with transaction(project) as conn:
        replay = await receipt(conn, arguments, principal, "publish")
        if replay:
            return replay
        configured = await policy(conn, project)
        if configured["version"] != arguments["expected_policy_version"]:
            raise conflict()
        kind = arguments["source_kind"]
        if kind == "checkpoint":
            source = await checkpoints.locate(conn, project, arguments["source_id"])
            if source["from_user"] != principal.user_id and not is_admin(principal):
                raise fail()
        else:
            # Moving an existing fixed-recipient contract is explicitly administrative.
            require_admin(principal)
            source = await conn.fetchrow("SELECT * FROM handoffs WHERE project_id=$1 AND id=$2::uuid FOR UPDATE", project, arguments["source_id"])
            now = await conn.fetchval("SELECT clock_timestamp()")
            if source is None or source["expires_at"] is None or source["expires_at"] <= now:
                raise fail()
            if source["continuity_managed"] or not (source["status"] == "pending" or (
                source["status"] == "claimed" and source["claim_lease_expires_at"] is not None and source["claim_lease_expires_at"] <= now
            )):
                raise conflict("Only pending or expired recoverable legacy leases can be promoted")
        if await conn.fetchval("SELECT EXISTS(SELECT 1 FROM memory_continuity_bundles WHERE project_id=$1 "
                               "AND (source_checkpoint_id=$2::uuid OR source_handoff_id=$2::uuid))", project, arguments["source_id"]):
            raise conflict("This source already has a continuity bundle; use explicit reassignment")
        defaults, _ = policies.resolve(configured["policy"], source["from_user"])
        recipients = arguments.get("recipient_user_ids", defaults)
        if not is_admin(principal) and not set(recipients) <= set(defaults):
            raise fail("Publisher recipients must be allowed by the admin's sender policy", "MEM-CONTINUITY-0004", 403)
        await eligible(conn, project, recipients, sender=source["from_user"])
        units = arguments.get("work_units", [{"key": "continue", "summary": "Continue the pinned source after local preflight", "assignee_user_ids": recipients}])
        validate_units(units, recipients)
        now = await conn.fetchval("SELECT clock_timestamp()")
        expires = min(source["expires_at"], now + timedelta(hours=configured["policy"]["retention_hours"]))
        bundle_id = await conn.fetchval("""
            INSERT INTO memory_continuity_bundles(project_id,source_checkpoint_id,source_handoff_id,from_user,
                classification,source_digest,policy_version,expires_at,created_by)
            VALUES($1,$2::uuid,$3::uuid,$4,$5,$6,$7,$8,$9) RETURNING id
        """, project, arguments["source_id"] if kind == "checkpoint" else None,
            arguments["source_id"] if kind == "handoff" else None, source["from_user"], source["classification"],
            source["payload_digest"], configured["version"], expires, principal.user_id)
        if kind == "handoff":
            # Delivery metadata only; never rewrite original payload, recipient or digest.
            await conn.execute("UPDATE handoffs SET continuity_managed=true,claim_generation=claim_generation+1,"
                               "claim_token_digest=NULL,claim_lease_expires_at=NULL,claimed_by=NULL,claimed_at=NULL,status='pending',"
                               "claim_disposition=NULL,claim_reason_code=NULL WHERE id=$1", source["id"])
        for user in sorted(recipients):
            await _insert_delivery(conn, project, bundle_id, user, 1)
        for unit in units:
            await _insert_unit(conn, project, bundle_id, unit)
        await event(conn, project, principal.user_id, "publish", bundle_id,
                    {"source_kind": kind, "source_id": arguments["source_id"], "source_digest": source["payload_digest"],
                     "recipient_user_ids": sorted(recipients), "work_units": units, "policy_version": configured["version"],
                     "version": 1, "reason": arguments["reason"]})
        return await receipt(conn, arguments, principal, "publish", {"bundle_id": str(bundle_id), "version": 1,
                             "continuity_version": 1, "recipient_user_ids": sorted(recipients), "expires_at": expires})


async def read(arguments, *, principal):
    project = arguments["project_id"]
    async with transaction(project) as conn:
        delivery, parent = await own_delivery(conn, project, arguments["delivery_id"], principal.user_id)
        ceiling(parent, arguments)
        if parent["source_checkpoint_id"]:
            source = await checkpoints.locate(conn, project, parent["source_checkpoint_id"])
            payload, snapshot, kind = checkpoints.payload(source), source["snapshot"], "checkpoint"
        else:
            source = await conn.fetchrow("SELECT * FROM handoffs WHERE project_id=$1 AND id=$2", project, parent["source_handoff_id"])
            if not source or source["expires_at"] <= await conn.fetchval("SELECT clock_timestamp()"):
                raise fail()
            payload, snapshot, kind = handoff_payload(source), None, "handoff"
        return jsonable_encoder({"continuity_version": 1, "bundle_id": parent["id"], "routing_version": parent["version"],
                                 "delivery_id": delivery["id"], "recipient_user_id": principal.user_id,
                                 "source_kind": kind, "source_id": source["id"], "source": payload, "snapshot": snapshot,
                                 "source_digest": parent["source_digest"], "source_created_at": source["created_at"],
                                 "expires_at": parent["expires_at"], "cache_policy": "no_store",
                                 "preflight": {"status": "verification_required", "automatic_resume": False}})


async def ack(arguments, *, principal):
    project = arguments["project_id"]
    async with transaction(project) as conn:
        replay = await receipt(conn, arguments, principal, "ack")
        if replay:
            return replay
        row, parent = await own_delivery(conn, project, arguments["delivery_id"], principal.user_id)
        if row["acknowledged_at"] is None:
            await conn.execute("UPDATE memory_continuity_deliveries SET acknowledged_at=clock_timestamp() WHERE id=$1", row["id"])
            await event(conn, project, principal.user_id, "ack", parent["id"], {"delivery_id": str(row["id"])})
        return await receipt(conn, arguments, principal, "ack", {"delivery_id": str(row["id"]), "acknowledged": True,
                                                               "work_completed": False})


async def reassign(arguments, *, principal):
    project = arguments["project_id"]
    async with transaction(project) as conn:
        replay = await receipt(conn, arguments, principal, "reassign")
        if replay:
            return replay
        configured = await policy(conn, project)
        parent = await bundle(conn, project, arguments["bundle_id"])
        if parent["version"] != arguments["expected_version"]:
            raise conflict()
        recipients, units = arguments["recipient_user_ids"], arguments["work_units"]
        validate_units(units, recipients)
        await eligible(conn, project, recipients, sender=parent["from_user"])
        existing = await conn.fetch("SELECT * FROM memory_continuity_units WHERE bundle_id=$1 ORDER BY unit_key", parent["id"])
        generations = {row["unit_key"]: row["claim_generation"] for row in existing}
        if arguments["expected_generations"] != generations:
            raise conflict("Expected generations must match every existing work unit")
        emergency = arguments.get("emergency_takeover", False)
        if emergency and not (configured["policy"]["allow_emergency_takeover"] and arguments.get("confirm_running_work_may_continue") is True):
            raise conflict("Emergency takeover requires enabled policy and explicit running-process confirmation")
        takeover = set(arguments.get("takeover_unit_keys", []))
        if (emergency and not takeover) or (takeover and not emergency) or not takeover <= set(generations):
            raise invalid("Emergency takeover must name existing affected work units explicitly")
        selected = {unit["key"]: unit for unit in units}
        now = await conn.fetchval("SELECT clock_timestamp()")
        for row in existing:
            updated = selected.get(row["unit_key"])
            changed = updated is None or (row["summary"] != updated["summary"] or set(row["assignee_user_ids"]) != set(updated["assignee_user_ids"]))
            force = row["unit_key"] in takeover and row["state"] == "claimed"
            if not changed and not force:
                continue
            if row["state"] in {"completed", "cancelled"}:
                # Never reopen terminal work. Omission just retains its history.
                if updated is not None:
                    raise conflict("Terminal work cannot be reassigned or reopened")
                continue
            if row["state"] == "claimed" and row["lease_expires_at"] > now and not force:
                raise conflict("Active work must expire or be explicitly emergency-reassigned")
            await conn.execute("UPDATE memory_continuity_units SET state=$2,summary=$3,assignee_user_ids=$4,"
                               "claimed_by=NULL,claim_token_digest=NULL,lease_expires_at=NULL,claim_generation=claim_generation+1,"
                               "updated_at=clock_timestamp() WHERE id=$1", row["id"], "available" if updated else "cancelled",
                               updated["summary"] if updated else row["summary"],
                               sorted(updated["assignee_user_ids"]) if updated else row["assignee_user_ids"])
        existing_keys = {row["unit_key"] for row in existing}
        if len(existing_keys | set(selected)) > 32:
            raise invalid("A bundle may contain at most 32 lifetime work units, including terminal history")
        for unit in units:
            if unit["key"] not in existing_keys:
                await _insert_unit(conn, project, parent["id"], unit)
        old = await conn.fetch("SELECT * FROM memory_continuity_deliveries WHERE bundle_id=$1 AND revoked_at IS NULL", parent["id"])
        old_users = {row["recipient_user_id"] for row in old}
        for row in old:
            if row["recipient_user_id"] not in recipients:
                await conn.execute("UPDATE memory_continuity_deliveries SET revoked_at=clock_timestamp() WHERE id=$1", row["id"])
        for user in sorted(set(recipients) - old_users):
            await _insert_delivery(conn, project, parent["id"], user, parent["version"] + 1)
        await conn.execute("UPDATE memory_continuity_bundles SET version=version+1,policy_version=$2 WHERE id=$1", parent["id"], configured["version"])
        await event(conn, project, principal.user_id, "reassign", parent["id"],
                    {"old_recipient_user_ids": sorted(old_users), "recipient_user_ids": sorted(recipients), "work_units": units,
                     "expected_generations": generations, "version": parent["version"] + 1, "policy_version": configured["version"],
                     "emergency_takeover": emergency, "takeover_unit_keys": sorted(takeover), "reason": arguments["reason"]})
        return await receipt(conn, arguments, principal, "reassign", {"bundle_id": str(parent["id"]), "version": parent["version"] + 1,
                             "running_processes_stopped": False, "recipient_user_ids": sorted(recipients)})
