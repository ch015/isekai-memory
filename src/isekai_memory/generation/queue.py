"""Persistent receipts, project-first locks, lease fencing and bounded redrive."""

from uuid import uuid4

from isekai_memory.experience import pagination
from isekai_memory.experience.persistence import error, lock_project
from isekai_memory.generation.contracts import (
    MODEL_VERSION,
    PROMPT_VERSION,
    PROVIDER,
    RECIPE,
    SUMMARY_RECIPE,
    source_watermark,
)
from isekai_memory.generation.summaries import materialize, scope
from isekai_memory.retrieval.citations import canonical, digest
from isekai_memory.store.database import get_pool


async def enqueue(arguments: dict, *, actor_id: str, settings) -> dict:
    project_id = arguments["project_id"]
    async with get_pool().acquire() as conn, conn.transaction():
        await conn.execute("SET LOCAL statement_timeout='5s'")
        await lock_project(conn, project_id)
        limit = arguments.get("limit", 20)
        jobs = []
        if arguments["kind"] == "extract":
            # A receipt set, not a timestamp cursor: a late-committing old source cannot be skipped.
            sources = await conn.fetch("""
                SELECT h.id,h.payload_digest,h.envelope_digest,h.classification,h.lock_snapshot_digest,h.phase_id
                FROM handoffs h WHERE h.project_id=$1
                AND NOT EXISTS (SELECT 1 FROM memory_generation_jobs j WHERE j.project_id=h.project_id
                    AND j.kind='extract' AND j.source_key=h.id::text AND j.source_watermark=h.payload_digest AND j.recipe=$2)
                ORDER BY h.created_at,h.id LIMIT $3
            """, project_id, RECIPE, limit + 1)
            for source in sources[:limit]:
                parameters = {
                    "source_handoff_id": str(source["id"]), "source_binding": source_watermark(source),
                    "max_input_chars": settings.generation_max_input_chars,
                    "max_output_chars": settings.generation_max_output_chars,
                    "cost_budget_microusd": 0,
                }
                jobs.append(await _insert(conn, project_id, "extract", str(source["id"]), source["payload_digest"],
                                          RECIPE, parameters, actor_id))
            more = len(sources) > limit
        else:
            view = scope(arguments)
            current = await materialize(conn, project_id, view)
            jobs.append(await _insert(conn, project_id, "summary", digest(canonical(view)), current["source_watermark"],
                                      SUMMARY_RECIPE, view, actor_id))
            more = False
    return {"jobs": jobs, "has_more": more, "coverage": "durable_source_receipts"}


async def _insert(conn, project, kind, key, watermark, recipe, parameters, actor):
    row = await conn.fetchrow("""
        INSERT INTO memory_generation_jobs
            (project_id,kind,source_key,source_watermark,recipe,provider,model_version,prompt_version,parameters,enqueued_by)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10)
        ON CONFLICT (project_id,kind,source_key,source_watermark,recipe) DO NOTHING RETURNING id,status
    """, project, kind, key, watermark, recipe, PROVIDER,
        MODEL_VERSION if kind == "extract" else "skill-scaffold-v1" if kind == "skill" else "approved-references-v1",
        PROMPT_VERSION if kind == "extract" else "no-prompt", parameters, actor)
    existing = row is None
    if existing:
        row = await conn.fetchrow("""
            SELECT id,status FROM memory_generation_jobs
            WHERE project_id=$1 AND kind=$2 AND source_key=$3 AND source_watermark=$4 AND recipe=$5
        """, project, kind, key, watermark, recipe)
    return {"job_id": str(row["id"]), "status": row["status"], "already_exists": existing}


async def list_jobs(arguments: dict) -> dict:
    view = ["generation", arguments["project_id"], arguments.get("status", "dead")]
    at, row_id = pagination.decode(arguments.get("cursor"), view)
    limit = arguments.get("limit", 20)
    async with get_pool().acquire() as conn:
        rows = await conn.fetch("""
            SELECT id,project_id,kind,source_key,source_watermark,recipe,provider,model_version,prompt_version,
                   enqueued_by,status,version,attempts,max_attempts,available_at,lease_until,error_code,outcome,created_at,updated_at
            FROM memory_generation_jobs WHERE project_id=$1 AND status=$2
              AND ($4::timestamptz IS NULL OR (created_at,id)<($4,$5::uuid))
            ORDER BY created_at DESC,id DESC LIMIT $3
        """, view[1], view[2], limit + 1, at, row_id)
    return pagination.page([dict(row) for row in rows], limit, view)


async def redrive(arguments: dict, *, actor_id: str) -> dict:
    async with get_pool().acquire() as conn, conn.transaction():
        await lock_project(conn, arguments["project_id"])
        row = await conn.fetchrow("SELECT * FROM memory_generation_jobs WHERE project_id=$1 AND id=$2::uuid FOR UPDATE",
                                  arguments["project_id"], arguments["job_id"])
        expected = arguments["expected_version"]
        if row and row["redrive_version"] == expected + 1 and row["redrive_actor"] == actor_id:
            return {"job_id": str(row["id"]), "applied_version": expected + 1, "already_applied": True}
        if not row or row["status"] != "dead" or row["version"] != expected or row["max_attempts"] >= 30:
            raise error("Job is unavailable, changed, or has exhausted its lifetime retry budget", "MEM-GENERATION-0002")
        await conn.execute("""
            UPDATE memory_generation_jobs SET status='queued',version=version+1,max_attempts=least(30,max_attempts+3),
                available_at=clock_timestamp(),error_code=NULL,updated_at=clock_timestamp(),
                redrive_version=version+1,redrive_actor=$2 WHERE id=$1
        """, row["id"], actor_id)
    return {"job_id": str(row["id"]), "applied_version": expected + 1, "already_applied": False}


async def claim(project_id: str, *, lease_seconds: int) -> dict | None:
    async with get_pool().acquire() as conn, conn.transaction():
        await lock_project(conn, project_id)
        # Drain a bounded batch of exhausted leases before selecting runnable work.
        exhausted = await conn.fetch("""
            SELECT id,attempts FROM memory_generation_jobs WHERE project_id=$1 AND status='running'
            AND lease_until <= clock_timestamp() AND attempts >= max_attempts ORDER BY created_at,id LIMIT 100 FOR UPDATE
        """, project_id)
        for row in exhausted:
            await finish_attempt(conn, row, "lease_expired")
            await conn.execute("""
                UPDATE memory_generation_jobs SET status='dead',version=version+1,lease_token=NULL,lease_until=NULL,
                    error_code='lease_expired',updated_at=clock_timestamp() WHERE id=$1
            """, row["id"])
        row = await conn.fetchrow("""
            SELECT * FROM memory_generation_jobs WHERE project_id=$1 AND attempts < max_attempts AND
              ((status='queued' AND available_at <= clock_timestamp()) OR (status='running' AND lease_until <= clock_timestamp()))
            ORDER BY created_at,id LIMIT 1 FOR UPDATE
        """, project_id)
        if row is None:
            return None
        if row["status"] == "running":
            await finish_attempt(conn, row, "lease_expired")
        row = await conn.fetchrow("""
            UPDATE memory_generation_jobs SET status='running',version=version+1,attempts=attempts+1,lease_token=$2,
                lease_until=clock_timestamp()+make_interval(secs=>$3),updated_at=clock_timestamp()
            WHERE id=$1 RETURNING *
        """, row["id"], uuid4(), lease_seconds)
        await conn.execute("INSERT INTO memory_generation_attempts(job_id,attempt) VALUES ($1,$2)", row["id"], row["attempts"])
        return dict(row)


async def fenced(conn, job) -> bool:
    # Call after the project lock. Database time is checked after any lock wait.
    return bool(await conn.fetchval("""
        SELECT 1 FROM memory_generation_jobs WHERE id=$1 AND project_id=$2 AND status='running'
          AND lease_token=$3 AND attempts=$4 AND lease_until > clock_timestamp() FOR UPDATE
    """, job["id"], job["project_id"], job["lease_token"], job["attempts"]))


async def finish_attempt(conn, job, code, input_chars=0, output_chars=0):
    await conn.execute("""
        UPDATE memory_generation_attempts SET finished_at=clock_timestamp(),outcome_code=$3,input_chars=$4,output_chars=$5
        WHERE job_id=$1 AND attempt=$2 AND finished_at IS NULL
    """, job["id"], job["attempts"], code, input_chars, output_chars)


async def fail(job: dict, code: str, *, retryable: bool, input_chars: int = 0, output_chars: int = 0) -> bool:
    async with get_pool().acquire() as conn, conn.transaction():
        await lock_project(conn, job["project_id"])
        if not await fenced(conn, job):
            return False
        retry = retryable and job["attempts"] < job["max_attempts"]
        await finish_attempt(conn, job, code, input_chars, output_chars)
        await conn.execute("""
            UPDATE memory_generation_jobs SET status=$2,version=version+1,error_code=$3,lease_token=NULL,lease_until=NULL,
                available_at=clock_timestamp()+make_interval(secs=>$4),updated_at=clock_timestamp() WHERE id=$1
        """, job["id"], "queued" if retry else "dead", code, min(300, 2 ** job["attempts"]))
        return True
