"""Owner-issued, consumer-bound, non-transitive reference grants. No cache reads."""

from isekai_memory.experience.persistence import lock_project
from isekai_memory.team import assets
from isekai_memory.team.common import ceiling, conflict, deadline, fail, fingerprint, listing, transaction


async def create(arguments, *, actor_id):
    project = arguments["project_id"]
    if arguments["consumer_project_id"] == project:
        raise conflict()
    request_digest = fingerprint(arguments)
    async with transaction(project) as conn:
        old = await conn.fetchrow("SELECT * FROM memory_asset_grants WHERE project_id=$1 AND created_by=$2 AND idempotency_key=$3",
                                  project, actor_id, arguments["idempotency_key"])
        if old:
            if old["submission_digest"] != request_digest:
                raise conflict()
            return {"grant_id": str(old["id"]), "version": 1, "already_exists": True}
        expires_at = await deadline(conn, arguments["expires_at"], days=30)
        asset = await assets.resolve(conn, project, arguments["asset_kind"], arguments["asset_id"], arguments["asset_version"],
                                     maximum=arguments["max_classification"], lock_digest=arguments.get("source_lock_digest"))
        gid = await conn.fetchval("""
            INSERT INTO memory_asset_grants(project_id,consumer_project_id,asset_kind,asset_id,asset_version,
                asset_digest,classification,expires_at,created_by,idempotency_key,submission_digest)
            VALUES ($1,$2,$3,$4::uuid,$5,$6,$7,$8,$9,$10,$11) RETURNING id
        """, project, arguments["consumer_project_id"], asset["asset_kind"], asset["asset_id"], asset["asset_version"],
            asset["asset_digest"], asset["classification"], expires_at, actor_id, arguments["idempotency_key"], request_digest)
        return {"grant_id": str(gid), "version": 1, "already_exists": False}


async def revoke(arguments, *, actor_id):
    async with transaction(arguments["project_id"]) as conn:
        row = await conn.fetchrow("SELECT * FROM memory_asset_grants WHERE id=$1::uuid AND project_id=$2",
                                  arguments["grant_id"], arguments["project_id"])
        if not row:
            raise fail()
        if arguments["expected_version"] == 1 and row["version"] == 2 and row["revoked_by"] == actor_id:
            return {"grant_id": str(row["id"]), "version": 2, "already_applied": True}
        if row["version"] != 1 or arguments["expected_version"] != 1:
            raise conflict()
        await conn.execute("UPDATE memory_asset_grants SET version=2,revoked_at=clock_timestamp(),revoked_by=$2 WHERE id=$1",
                           row["id"], actor_id)
        return {"grant_id": str(row["id"]), "version": 2, "already_applied": False}


async def locate(conn, project, grant_id):
    row = await conn.fetchrow("SELECT * FROM memory_asset_grants WHERE id=$1::uuid AND consumer_project_id=$2", grant_id, project)
    if not row:
        raise fail()
    return row


async def resolve(conn, arguments):
    row = await locate(conn, arguments["project_id"], arguments["grant_id"])
    if row["version"] != arguments["grant_version"] or row["revoked_at"] is not None:
        raise fail()
    ceiling(row["classification"], arguments.get("max_classification", "internal"))
    if row["expires_at"] <= await conn.fetchval("SELECT clock_timestamp()"):
        raise fail()
    asset = await assets.resolve(conn, row["project_id"], row["asset_kind"], row["asset_id"], row["asset_version"],
                                 maximum=row["classification"], lock_digest=arguments.get("source_lock_digest"))
    if asset["asset_digest"] != row["asset_digest"]:
        raise fail()
    return {"grant_id": str(row["id"]), "grant_version": row["version"], "owner_project_id": row["project_id"],
            "consumer_project_id": row["consumer_project_id"], "asset": asset, "usage": "reference_only", "cache_policy": "no_store"}


async def read(arguments):
    async with transaction() as conn:
        row = await locate(conn, arguments["project_id"], arguments["grant_id"])
        # READ COMMITTED rechecks after the owner's mutation lock. A completed revoke cannot be served from a prior snapshot.
        await lock_project(conn, row["project_id"])
        return await resolve(conn, arguments)


async def list_grants(arguments):
    return await listing(arguments, table="memory_asset_grants", view="grants",
                         columns="id,consumer_project_id,asset_kind,asset_id,asset_version,asset_digest,classification,expires_at,"
                                 "version,revoked_at,revoked_by,created_by,created_at")
