"""Explicit bounded observations; no implicit success, ranking or lifecycle writes."""

from isekai_memory.experience.persistence import lock_project
from isekai_memory.team import assets, grants
from isekai_memory.team.common import conflict, fail, fingerprint, listing, transaction


async def record(arguments, *, actor_id):
    attempted = arguments["outcome"] != "not_attempted"
    if attempted != ("handoff_id" in arguments) or ("grant_id" in arguments) != ("grant_version" in arguments):
        raise fail("Outcome requires evidence; shared feedback requires an exact grant version", "MEM-TEAM-0003", 400)
    project = arguments["project_id"]
    request_digest = fingerprint(arguments)
    async with transaction() as conn:
        owner = project
        if "grant_id" in arguments:
            owner = (await grants.locate(conn, project, arguments["grant_id"]))["project_id"]
        for target in sorted({owner, project}):
            await lock_project(conn, target)
        old = await conn.fetchrow("SELECT id,submission_digest FROM memory_asset_feedback WHERE project_id=$1 AND actor_id=$2 AND idempotency_key=$3",
                                  project, actor_id, arguments["idempotency_key"])
        if old:
            if old["submission_digest"] != request_digest:
                raise conflict()
            return {"feedback_id": str(old["id"]), "already_exists": True}
        if "grant_id" in arguments:
            asset = (await grants.resolve(conn, {**arguments, "max_classification": "restricted"}))["asset"]
            if any(str(asset[key]) != str(arguments[key]) for key in ("asset_kind", "asset_id", "asset_version")):
                raise fail()
        else:
            asset = await assets.resolve(conn, project, arguments["asset_kind"], arguments["asset_id"], arguments["asset_version"], maximum="restricted")
        if await conn.fetchval("""
            SELECT 1 FROM memory_asset_feedback WHERE project_id=$1 AND actor_id=$2 AND asset_kind=$3 AND asset_id=$4::uuid AND asset_version=$5
        """, project, actor_id, asset["asset_kind"], asset["asset_id"], asset["asset_version"]):
            raise conflict()
        evidence = None
        if attempted:
            evidence = await conn.fetchval("""
                SELECT payload_digest FROM handoffs WHERE id=$1::uuid AND project_id=$2 AND result_status=$3
                    AND jsonb_array_length(CASE WHEN jsonb_typeof(result_envelope->'evidence_refs')='array'
                        THEN result_envelope->'evidence_refs' ELSE '[]'::jsonb END)>0
            """, arguments["handoff_id"], project, arguments["outcome"])
            if not evidence:
                raise fail("Reported outcome needs matching same-project handoff evidence", "MEM-TEAM-0003", 400)
        fid = await conn.fetchval("""
            INSERT INTO memory_asset_feedback(project_id,actor_id,asset_kind,asset_id,asset_version,asset_digest,
                owner_project_id,grant_id,usefulness,outcome,handoff_id,evidence_digest,idempotency_key,submission_digest)
            VALUES ($1,$2,$3,$4::uuid,$5,$6,$7,$8::uuid,$9,$10,$11::uuid,$12,$13,$14) RETURNING id
        """, project, actor_id, asset["asset_kind"], asset["asset_id"], asset["asset_version"], asset["asset_digest"], owner,
            arguments.get("grant_id"), arguments["usefulness"], arguments["outcome"], arguments.get("handoff_id"), evidence,
            arguments["idempotency_key"], request_digest)
        return {"feedback_id": str(fid), "already_exists": False, "usage": "reported_observation_only"}


async def list_feedback(arguments):
    return await listing(arguments, table="memory_asset_feedback", view="feedback",
                         columns="id,actor_id,asset_kind,asset_id,asset_version,asset_digest,owner_project_id,grant_id,"
                                 "usefulness,outcome,handoff_id,evidence_digest,created_at",
                         extra="AND ($5::uuid IS NULL OR asset_id=$5)", extra_values=(arguments.get("asset_id"),))
