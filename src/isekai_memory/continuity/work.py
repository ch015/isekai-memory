"""One execution-ownership claim per explicit work unit, never a remote process lock."""

from datetime import UTC, datetime, timedelta

from fastapi.encoders import jsonable_encoder

from isekai_memory.continuity.common import conflict, event, fail, policy, receipt, token_digest, transaction
from isekai_memory.continuity.delivery import bundle


async def locate(conn, arguments, principal):
    row = await conn.fetchrow("SELECT * FROM memory_continuity_units WHERE project_id=$1 AND id=$2::uuid",
                              arguments["project_id"], arguments["unit_id"])
    if row is None or principal.user_id not in row["assignee_user_ids"]:
        raise fail()
    parent = await bundle(conn, arguments["project_id"], row["bundle_id"])
    if not await conn.fetchval("SELECT EXISTS(SELECT 1 FROM memory_continuity_deliveries WHERE bundle_id=$1 AND recipient_user_id=$2 AND revoked_at IS NULL)",
                               row["bundle_id"], principal.user_id):
        raise fail()
    return row, parent


def result(row, parent):
    return jsonable_encoder({"unit_id": row["id"], "bundle_id": row["bundle_id"], "unit_key": row["unit_key"],
                             "claimed_by": row["claimed_by"], "claim_generation": row["claim_generation"],
                             "lease_expires_at": row["lease_expires_at"], "expires_at": parent["expires_at"],
                             "routing_version": parent["version"], "automatic_resume": False})


def active(row, arguments, actor, now):
    if (row["state"] != "claimed" or row["claimed_by"] != actor
            or row["claim_token_digest"] != token_digest(arguments["claim_token"])
            or row["claim_generation"] != arguments["claim_generation"]
            or row["lease_expires_at"] is None or row["lease_expires_at"] <= now):
        raise conflict("No active work lease matches this actor, token and generation")


async def claim(arguments, *, principal):
    project = arguments["project_id"]
    async with transaction(project) as conn:
        configured = await policy(conn, project)
        row, parent = await locate(conn, arguments, principal)
        now = await conn.fetchval("SELECT clock_timestamp()")
        token = token_digest(arguments["claim_token"])
        expected = arguments.get("expected_generation")
        routing = arguments.get("expected_routing_version")
        if routing is not None and parent["version"] != routing:
            raise conflict("Work routing changed since selection")
        if row["state"] == "claimed" and row["lease_expires_at"] > now:
            if row["claimed_by"] == principal.user_id and row["claim_token_digest"] == token:
                if expected is not None and expected != row["claim_generation"] - 1:
                    raise conflict("Claim receipt belongs to another selected generation")
                return {**result(row, parent), "replayed": True}
            raise conflict("Work unit already has an active owner")
        if expected is not None and row["claim_generation"] != expected:
            raise conflict("Work ownership generation changed since selection")
        if row["state"] not in {"available", "claimed"}:
            raise conflict("Terminal work cannot be claimed")
        if await conn.fetchval("SELECT EXISTS(SELECT 1 FROM memory_continuity_claims WHERE unit_id=$1 AND actor_id=$2 AND claim_token_digest=$3)",
                               row["id"], principal.user_id, token):
            raise conflict("A previously used claim token cannot start a new generation")
        until = min(parent["expires_at"], now + timedelta(seconds=configured["policy"]["lease_seconds"]))
        updated = await conn.fetchrow("UPDATE memory_continuity_units SET state='claimed',claimed_by=$2,claim_token_digest=$3,"
                                      "claim_generation=claim_generation+1,lease_expires_at=$4,updated_at=clock_timestamp() WHERE id=$1 RETURNING *",
                                      row["id"], principal.user_id, token, until)
        await conn.execute("INSERT INTO memory_continuity_claims(unit_id,project_id,actor_id,claim_token_digest,claim_generation) VALUES($1,$2,$3,$4,$5)",
                           row["id"], project, principal.user_id, token, updated["claim_generation"])
        await event(conn, project, principal.user_id, "claim", parent["id"],
                    {"unit_id": str(row["id"]), "claim_generation": updated["claim_generation"]})
        return {**result(updated, parent), "replayed": False}


async def renew(arguments, *, principal):
    async with transaction(arguments["project_id"]) as conn:
        configured = await policy(conn, arguments["project_id"], enabled=False)
        row, parent = await locate(conn, arguments, principal)
        now = await conn.fetchval("SELECT clock_timestamp()")
        active(row, arguments, principal.user_id, now)
        deadline = datetime.fromisoformat(arguments["lease_expires_at"].upper().replace("Z", "+00:00")).astimezone(UTC)
        if deadline > row["lease_expires_at"] and deadline > now + timedelta(seconds=configured["policy"]["lease_seconds"]):
            raise conflict("Requested work lease exceeds the current project maximum")
        effective = max(row["lease_expires_at"], min(deadline, parent["expires_at"]))
        updated = await conn.fetchrow("UPDATE memory_continuity_units SET lease_expires_at=$2 WHERE id=$1 RETURNING *", row["id"], effective)
        return {**result(updated, parent), "extended": effective > row["lease_expires_at"]}


async def release(arguments, *, principal):
    project = arguments["project_id"]
    async with transaction(project) as conn:
        replay = await receipt(conn, arguments, principal, "work_release")
        if replay:
            return replay
        row, parent = await locate(conn, arguments, principal)
        active(row, arguments, principal.user_id, await conn.fetchval("SELECT clock_timestamp()"))
        state = "completed" if arguments["action"] == "complete" else "available"
        await conn.execute("UPDATE memory_continuity_units SET state=$2,claim_token_digest=NULL,lease_expires_at=NULL,"
                           "claimed_by=NULL,updated_at=clock_timestamp() WHERE id=$1", row["id"], state)
        await event(conn, project, principal.user_id, "work_" + arguments["action"], parent["id"],
                    {"unit_id": str(row["id"]), "claim_generation": row["claim_generation"], "reason": arguments["reason"]})
        return await receipt(conn, arguments, principal, "work_release",
                             {"unit_id": str(row["id"]), "state": state, "claim_generation": row["claim_generation"], "execution_verified": False})
