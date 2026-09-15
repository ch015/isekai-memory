"""Finite offline worker. Provider execution holds no transaction or Handoff lease."""

import asyncio

from isekai_memory.experience import service as experiences
from isekai_memory.experience.persistence import lock_project
from isekai_memory.generation import queue, summaries
from isekai_memory.generation.contracts import (
    RECIPE,
    SUMMARY_RECIPE,
    ExtractionInput,
    GenerationFailure,
    source_watermark,
)
from isekai_memory.generation.provider import StructuredExtractor
from isekai_memory.retrieval.citations import digest
from isekai_memory.server.errors import MemoryToolError
from isekai_memory.server.validation import validate_tool_arguments
from isekai_memory.store.database import get_pool


async def _source(conn, job, input_limit):
    # Never fetch raw output or the entire envelope into the extraction provider.
    return await conn.fetchrow("""
        SELECT id,payload_digest,envelope_digest,classification,lock_snapshot_digest,phase_id,result_status,
               left(result_envelope->>'summary',$3+1) AS summary,
               left(task_envelope->>'objective',201) AS objective
        FROM handoffs WHERE project_id=$1 AND id=$2::uuid FOR KEY SHARE
    """, job["project_id"], job["source_key"], input_limit)


def _check_source(source, job):
    if source is None or source["payload_digest"] != job["source_watermark"] or (
        source_watermark(source) != job["parameters"]["source_binding"]
    ):
        raise GenerationFailure("source_changed")


async def _complete(job, *, candidate=None, input_chars=0, output_chars=0, summary=None):
    async with get_pool().acquire() as conn, conn.transaction():
        await conn.execute("SET LOCAL statement_timeout='5s'")
        await lock_project(conn, job["project_id"])
        if not await queue.fenced(conn, job):
            return {"job_id": str(job["id"]), "status": "lease_lost"}
        outcome = {"code": "empty", "input_chars": input_chars, "output_chars": output_chars, "cost_microusd": 0}
        if job["kind"] == "skill":
            from isekai_memory.skills.generation import complete

            outcome.update(await complete(conn, job, candidate))
        elif job["kind"] == "summary":
            current = await summaries.materialize(conn, job["project_id"], job["parameters"])
            if current["source_watermark"] != job["source_watermark"] or summary != current["dependencies"]:
                raise GenerationFailure("source_changed")
            await conn.execute("""
                INSERT INTO memory_summary_snapshots(job_id,project_id,source_watermark,scope,source_count,dependencies)
                VALUES ($1,$2,$3,$4::jsonb,$5,$6::jsonb)
            """, job["id"], job["project_id"], job["source_watermark"], job["parameters"],
                current["source_count"], current["dependencies"])
            outcome.update(code="snapshot", source_count=current["source_count"], captured_count=len(summary))
        else:
            source = await _source(conn, job, job["parameters"]["max_input_chars"])
            _check_source(source, job)
            # Conservative source-level gate also protects paraphrases and manual corrections.
            protected = await conn.fetchval("""
                SELECT EXISTS(SELECT 1 FROM memory_experience_suppressions
                    WHERE project_id=$1 AND source_payload_digest=$2 AND released_at IS NULL)
                OR EXISTS(SELECT 1 FROM memory_experiences
                    WHERE project_id=$1 AND source_payload_digest=$2 AND is_correction)
            """, job["project_id"], source["payload_digest"])
            if protected:
                outcome["code"] = "protected_source"
            elif candidate is not None:
                args = {
                    "project_id": job["project_id"], "source_handoff_id": job["source_key"],
                    "idempotency_key": "generation:" + str(job["id"]),
                    "kind": candidate.kind, "title": candidate.title, "content": candidate.content,
                }
                validate_tool_arguments("memory_experience_propose", args)
                # Same-source normalized duplicates never create another review item, even under a new recipe.
                normalized = " ".join(experiences._search_text(candidate.content).split())
                fingerprint = digest(candidate.kind + "\n" + normalized)
                duplicate = await conn.fetchval("""
                    SELECT id FROM memory_experiences WHERE project_id=$1 AND source_payload_digest=$2
                        AND content_fingerprint=$3 LIMIT 1
                """, job["project_id"], source["payload_digest"], fingerprint)
                if duplicate:
                    outcome.update(code="duplicate", memory_id=str(duplicate))
                else:
                    receipt = await experiences.propose(args, actor_id="generation:" + str(job["id"]), connection=conn)
                    outcome.update(code="proposed", memory_id=receipt["memory_id"])
        # Recheck lease after all potentially waiting operations; roll back proposals on expiry.
        if not await queue.fenced(conn, job):
            raise GenerationFailure("lease_lost")
        await queue.finish_attempt(conn, job, outcome["code"], input_chars, output_chars)
        completed = await conn.fetchval("""
            UPDATE memory_generation_jobs SET status='succeeded',version=version+1,lease_token=NULL,lease_until=NULL,
                error_code=NULL,outcome=$2::jsonb,updated_at=clock_timestamp()
            WHERE id=$1 AND lease_until > clock_timestamp() RETURNING id
        """, job["id"], outcome)
        if completed is None:
            raise GenerationFailure("lease_lost")
        return {"job_id": str(job["id"]), "status": "succeeded", **outcome}


async def process(job, settings, *, provider=None):
    input_chars = output_chars = 0
    try:
        async with asyncio.timeout(settings.generation_timeout_seconds):
            if job["kind"] == "skill":
                from isekai_memory.retrieval.citations import canonical
                from isekai_memory.skills.generation import scaffold

                candidate = scaffold(job)
                input_chars = len(canonical(job["parameters"]))
                output_chars = len(canonical(candidate["body"]))
                if input_chars > min(settings.generation_max_input_chars, job["parameters"]["max_input_chars"]):
                    raise GenerationFailure("input_budget")
                if output_chars > min(settings.generation_max_output_chars, job["parameters"]["max_output_chars"]):
                    raise GenerationFailure("output_budget")
                return await _complete(job, candidate=candidate, input_chars=input_chars, output_chars=output_chars)
            if job["kind"] == "summary":
                if job["recipe"] != SUMMARY_RECIPE:
                    raise GenerationFailure("unsupported_recipe")
                async with get_pool().acquire() as conn, conn.transaction(isolation="repeatable_read", readonly=True):
                    await conn.execute("SET LOCAL statement_timeout='2s'")
                    current = await summaries.materialize(conn, job["project_id"], job["parameters"])
                if current["source_watermark"] != job["source_watermark"]:
                    raise GenerationFailure("source_changed")
                return await _complete(job, summary=current["dependencies"])
            provider = provider or StructuredExtractor()
            if job["recipe"] != RECIPE or provider.recipe != RECIPE or job["parameters"]["cost_budget_microusd"] != 0:
                raise GenerationFailure("unsupported_recipe")
            input_limit = min(settings.generation_max_input_chars, job["parameters"]["max_input_chars"])
            output_limit = min(settings.generation_max_output_chars, job["parameters"]["max_output_chars"])
            async with get_pool().acquire() as conn:
                source = await _source(conn, job, input_limit)
            _check_source(source, job)
            source_input = ExtractionInput(summary=source["summary"] or "", objective=source["objective"] or "",
                                           result_status=source["result_status"])
            input_chars = len(source_input.summary) + len(source_input.objective)
            if input_chars > input_limit:
                raise GenerationFailure("input_budget")
            candidate = await provider.extract(source_input)
            output_chars = len(candidate.title) + len(candidate.content) if candidate else 0
            if output_chars > output_limit:
                raise GenerationFailure("output_budget")
            return await _complete(job, candidate=candidate, input_chars=input_chars, output_chars=output_chars)
    except GenerationFailure as exc:
        code, retryable = exc.code, exc.retryable
    except TimeoutError:
        code, retryable = "timeout", True
    except MemoryToolError:
        code, retryable = "invalid_candidate", False
    except Exception:
        # No provider output/credentials or exception strings in durable logs.
        code, retryable = "processing_failed", True
    applied = await queue.fail(job, code, retryable=retryable, input_chars=input_chars, output_chars=output_chars)
    return {"job_id": str(job["id"]), "status": "failed" if applied else "lease_lost", "error_code": code}


async def run(settings, *, project_id: str, max_jobs: int = 20) -> dict:
    if not settings.generation_enabled:
        raise MemoryToolError("Generation worker is disabled; explicitly enable generation.enabled",
                              data={"error_code": "MEM-GENERATION-0001"})
    if not project_id.strip() or len(project_id) > 128 or not 1 <= max_jobs <= 100:
        raise ValueError("Worker requires a project and 1–100 jobs per invocation")
    results = []
    for _ in range(max_jobs):
        job = await queue.claim(project_id, lease_seconds=settings.generation_lease_seconds)
        if job is None:
            break
        results.append(await process(job, settings))
    return {"project_id": project_id, "processed": len(results), "results": results, "cost_microusd": 0}
