"""Immutable actor-owned checkpoints; admins recover provenance, never impersonate."""

from datetime import timedelta

from fastapi.encoders import jsonable_encoder

from isekai_memory.continuity import snapshots
from isekai_memory.continuity.common import (
    CLASSIFICATIONS,
    ceiling,
    conflict,
    digest,
    event,
    fail,
    is_admin,
    policy,
    receipt,
    transaction,
)
from isekai_memory.handoff import continuation


def payload(row):
    return {key: row[key] for key in ("project_id", "work_id", "from_user", "version", "classification",
                                     "lock_snapshot_digest", "continuation", "continuation_digest", "snapshot_digest")}


async def locate(conn, project, checkpoint_id, *, retained=True):
    row = await conn.fetchrow("SELECT * FROM memory_checkpoints WHERE project_id=$1 AND id=$2::uuid", project, checkpoint_id)
    if row is None or (retained and (row["forgotten_at"] is not None or row["expires_at"] <= await conn.fetchval("SELECT clock_timestamp()"))):
        raise fail()
    return row


async def save(arguments, *, principal):
    project = arguments["project_id"]
    package = arguments["continuation"]
    package_digest = continuation.validate(package)
    async with transaction(project) as conn:
        replay = await receipt(conn, arguments, principal, "checkpoint_save")
        if replay:
            return replay
        configured = await policy(conn, project)
        body = configured["policy"]
        snapshot_digest = snapshots.validate(arguments.get("snapshot"), package, body)
        latest = await conn.fetchrow("SELECT version,classification FROM memory_checkpoints WHERE project_id=$1 AND from_user=$2 "
                                     "AND work_id=$3 ORDER BY version DESC LIMIT 1", project, principal.user_id, arguments["work_id"])
        version = latest["version"] if latest else 0
        if version != arguments["expected_version"]:
            raise conflict()
        if latest and CLASSIFICATIONS.index(arguments["classification"]) < CLASSIFICATIONS.index(latest["classification"]):
            raise conflict("Checkpoint classification cannot be lowered")
        material = {"project_id": project, "work_id": arguments["work_id"], "from_user": principal.user_id,
                    "version": version + 1, "classification": arguments["classification"],
                    "lock_snapshot_digest": arguments["lock_snapshot_digest"], "continuation": package,
                    "continuation_digest": package_digest, "snapshot_digest": snapshot_digest}
        expires = await conn.fetchval("SELECT clock_timestamp()") + timedelta(hours=body["retention_hours"])
        row = await conn.fetchrow("""
            INSERT INTO memory_checkpoints(project_id,work_id,from_user,version,classification,lock_snapshot_digest,
                continuation,continuation_digest,snapshot,snapshot_digest,payload_digest,policy_version,expires_at)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13) RETURNING id,created_at,expires_at
        """, project, arguments["work_id"], principal.user_id, version + 1, arguments["classification"],
            arguments["lock_snapshot_digest"], package, package_digest, arguments.get("snapshot"), snapshot_digest,
            digest(material), configured["version"], expires)
        await event(conn, project, principal.user_id, "checkpoint_save", row["id"],
                    {"work_id": arguments["work_id"], "version": version + 1, "payload_digest": digest(material)})
        return await receipt(conn, arguments, principal, "checkpoint_save",
                             {"checkpoint_id": str(row["id"]), "version": version + 1, "payload_digest": digest(material),
                              "created_at": row["created_at"], "expires_at": expires})


async def read(arguments, *, principal):
    async with transaction(arguments["project_id"]) as conn:
        row = await locate(conn, arguments["project_id"], arguments["checkpoint_id"])
        if row["from_user"] != principal.user_id and not is_admin(principal):
            raise fail()
        ceiling(row, arguments)
        return jsonable_encoder({"checkpoint_id": str(row["id"]), "source": payload(row), "snapshot": row["snapshot"],
                                 "payload_digest": row["payload_digest"], "created_at": row["created_at"],
                                 "expires_at": row["expires_at"], "cache_policy": "no_store", "automatic_resume": False})


async def forget(arguments, *, principal):
    async with transaction(arguments["project_id"]) as conn:
        replay = await receipt(conn, arguments, principal, "checkpoint_forget")
        if replay:
            return replay
        row = await locate(conn, arguments["project_id"], arguments["checkpoint_id"], retained=False)
        revoked_users = []
        if row["forgotten_at"] is None:
            revoked_users = await conn.fetch("SELECT d.recipient_user_id FROM memory_continuity_deliveries d "
                "JOIN memory_continuity_bundles b ON b.id=d.bundle_id WHERE b.source_checkpoint_id=$1 AND d.revoked_at IS NULL", row["id"])
            await conn.execute("UPDATE memory_checkpoints SET continuation='{}'::jsonb,snapshot=NULL,forgotten_at=clock_timestamp() WHERE id=$1", row["id"])
            bundle_ids = await conn.fetch("UPDATE memory_continuity_bundles SET revoked_at=clock_timestamp(),version=version+1 "
                                          "WHERE source_checkpoint_id=$1 AND revoked_at IS NULL RETURNING id", row["id"])
            for bundle in bundle_ids:
                await conn.execute("UPDATE memory_continuity_deliveries SET revoked_at=clock_timestamp() WHERE bundle_id=$1 AND revoked_at IS NULL", bundle["id"])
                await conn.execute("UPDATE memory_continuity_units SET state='cancelled',claim_token_digest=NULL,lease_expires_at=NULL,"
                                   "claimed_by=NULL,claim_generation=claim_generation+1,updated_at=clock_timestamp() WHERE bundle_id=$1", bundle["id"])
        await event(conn, arguments["project_id"], principal.user_id, "checkpoint_forget", row["id"], {"reason": arguments["reason"],
                    "revoked_user_ids": [user["recipient_user_id"] for user in revoked_users]})
        return await receipt(conn, arguments, principal, "checkpoint_forget", {"checkpoint_id": str(row["id"]), "forgotten": True})
