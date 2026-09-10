"""Immutable proposals and latest-revision compare-and-swap, including durable replay."""

import unicodedata
from uuid import UUID

from jsonschema import Draft202012Validator

from isekai_memory.experience.persistence import lock_project
from isekai_memory.experience.service import CLASSIFICATIONS
from isekai_memory.retrieval.citations import canonical, digest
from isekai_memory.skills import sources
from isekai_memory.skills.sources import fail
from isekai_memory.skills.tools import BODY
from isekai_memory.store.database import get_pool


def normalize(value):
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value).strip()
    if isinstance(value, list):
        return [normalize(item) for item in value]
    if isinstance(value, dict):
        return {key: normalize(item) for key, item in value.items()}
    return value


def prepare(arguments):
    body = normalize(arguments["body"])
    references = sources.refs(arguments["sources"])
    for step in body.get("steps", []):
        step["sources"] = sorted({str(UUID(item)) for item in step["sources"]})
    if not Draft202012Validator(BODY).is_valid(body) or len(canonical(body)) > 24000:
        raise fail("Skill body violates normalized schema or 24000-character budget", "MEM-SKILL-0002", 400)
    ids = {item["memory_id"] for item in references}
    if any(set(step["sources"]) - ids for step in body["steps"]):
        raise fail("Every step must bind declared sources", "MEM-SKILL-0002", 400)
    names = [item["name"] for item in body.get("resources", [])]
    if len(set(names)) != len(names):
        raise fail("Duplicate resource name", "MEM-SKILL-0002", 400)
    material = {key: arguments[key] for key in ("name", "skill_id", "expected_revision") if key in arguments}
    if "skill_id" in material:
        material["skill_id"] = str(UUID(material["skill_id"]))
    material.update(body=body, sources=references)
    return material, digest(canonical(material))


async def submit(arguments, *, actor_id, origin="manual", connection=None):
    material, submission_digest = prepare(arguments)
    if connection is not None:
        return await _submit(connection, arguments, material, submission_digest, actor_id, origin)
    async with get_pool().acquire() as conn, conn.transaction():
        await conn.execute("SET LOCAL statement_timeout='5s'")
        await lock_project(conn, arguments["project_id"])
        return await _submit(conn, arguments, material, submission_digest, actor_id, origin)


async def _submit(conn, arguments, material, submission_digest, actor, origin):
    project_id = arguments["project_id"]
    old = await conn.fetchrow("""
        SELECT id,skill_id,revision,submission_digest FROM memory_skill_revisions
        WHERE project_id=$1 AND created_by=$2 AND idempotency_key=$3
    """, project_id, actor, arguments["idempotency_key"])
    if old:
        if old["submission_digest"] != submission_digest:
            raise fail("Submission key identifies different Skill content", "MEM-SKILL-0003")
        return {"revision_id": str(old["id"]), "skill_id": str(old["skill_id"]), "revision": old["revision"], "already_exists": True}
    current = await sources.capture(conn, project_id, material["sources"])
    if "skill_id" in material:
        skill = await conn.fetchrow("SELECT * FROM memory_skills WHERE id=$1::uuid AND project_id=$2 FOR UPDATE",
                                   material["skill_id"], project_id)
        if not skill or skill["latest_revision"] != material["expected_revision"]:
            raise fail("Skill latest revision conflicts", "MEM-SKILL-0004")
        previous = await conn.fetchrow("SELECT origin,body FROM memory_skill_revisions WHERE skill_id=$1 AND revision=$2",
                                       skill["id"], skill["latest_revision"])
        if origin == "manual" and previous["origin"] == "generated" and all(
            material["body"][key] == previous["body"].get(key) for key in ("triggers", "steps", "validation")
        ):
            raise fail("Author the scaffold's applicability, procedure or validation before review", "MEM-SKILL-0005")
    else:
        skill = await conn.fetchrow("SELECT * FROM memory_skills WHERE project_id=$1 AND name=$2", project_id, material["name"])
        if skill:
            raise fail("Skill name exists; explicitly revise its latest revision", "MEM-SKILL-0004")
        skill = await conn.fetchrow("""
            INSERT INTO memory_skills(project_id,name,classification) VALUES ($1,$2,$3) RETURNING *
        """, project_id, material["name"], current["classification"])
    classification = max((skill["classification"], current["classification"]), key=CLASSIFICATIONS.index)
    content_digest = digest(canonical({"body": material["body"], "sources": current["bindings"], "classification": classification}))
    revision = skill["latest_revision"] + 1
    rid = await conn.fetchval("""
        INSERT INTO memory_skill_revisions(skill_id,project_id,revision,base_active_revision,origin,body,classification,
            source_lock_digest,source_watermark,content_digest,created_by,idempotency_key,submission_digest)
        VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7,$8,$9,$10,$11,$12,$13) RETURNING id
    """, skill["id"], project_id, revision, skill["active_revision"], origin, material["body"], classification,
        current["source_lock_digest"], current["source_watermark"], content_digest, actor,
        arguments["idempotency_key"], submission_digest)
    for binding in current["bindings"]:
        await conn.execute("""
            INSERT INTO memory_skill_sources(revision_id,project_id,memory_id,memory_version,binding)
            VALUES ($1,$2,$3::uuid,$4,$5::jsonb)
        """, rid, project_id, binding["memory_id"], binding["version"], binding)
    await conn.execute("UPDATE memory_skills SET latest_revision=$2,classification=$3 WHERE id=$1", skill["id"], revision, classification)
    return {"revision_id": str(rid), "skill_id": str(skill["id"]), "revision": revision, "already_exists": False}
