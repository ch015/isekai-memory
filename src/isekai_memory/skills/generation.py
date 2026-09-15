"""Offline source-linked scaffolding on M4's durable execution path."""

from isekai_memory.experience.persistence import lock_project
from isekai_memory.generation import queue
from isekai_memory.generation.contracts import GenerationFailure
from isekai_memory.retrieval.citations import canonical, digest
from isekai_memory.server.errors import MemoryToolError
from isekai_memory.skills import sources, submissions
from isekai_memory.store.database import get_pool

RECIPE = "local_structured/skill-scaffold-v1/no-prompt"


async def enqueue(arguments, *, actor_id, settings):
    async with get_pool().acquire() as conn, conn.transaction():
        await conn.execute("SET LOCAL statement_timeout='5s'")
        await lock_project(conn, arguments["project_id"])
        refs = sources.refs(arguments["sources"])
        captured = await sources.capture(conn, arguments["project_id"], refs)
        job = await queue._insert(conn, arguments["project_id"], "skill", digest(canonical(refs)), captured["source_watermark"],
                                  RECIPE, {"sources": refs, "max_input_chars": settings.generation_max_input_chars,
                                           "max_output_chars": settings.generation_max_output_chars, "cost_budget_microusd": 0}, actor_id)
        return {"job": job}


def scaffold(job):
    if job["recipe"] != RECIPE:
        raise GenerationFailure("unsupported_recipe")
    refs = job["parameters"]["sources"]
    return {
        "project_id": job["project_id"], "name": "draft-" + str(job["id"]).replace("-", ""),
        "idempotency_key": "generation:" + str(job["id"]), "sources": refs,
        "body": {
            "title": "Procedure Skill scaffold",
            "description": "Human authoring required: derive a scoped procedure from the approved evidence.",
            "triggers": ["Replace this scaffold with concrete applicability conditions before review."],
            "steps": [{"instruction": "Inspect the bound source as evidence and author a concrete, authorized step.",
                       "sources": [ref["memory_id"]]} for ref in refs],
            "validation": ["Replace this scaffold with observable success and failure criteria."],
        },
    }


async def complete(conn, job, candidate):
    try:
        current = await sources.capture(conn, job["project_id"], job["parameters"]["sources"])
    except MemoryToolError as exc:
        raise GenerationFailure("source_changed") from exc
    if current["source_watermark"] != job["source_watermark"]:
        raise GenerationFailure("source_changed")
    receipt = await submissions.submit(candidate, actor_id="generation:" + str(job["id"]), origin="generated", connection=conn)
    return {"code": "skill_proposed", **receipt}
