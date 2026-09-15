"""Lexical providers and authoritative post-candidate hydration in one snapshot."""

from __future__ import annotations

import math

import asyncpg

from isekai_memory.retrieval.contracts import Candidate, RetrievalProvider, RetrievalRequest
from isekai_memory.store.database import get_pool

# Every candidate query applies visibility BEFORE ranking and LIMIT. Hydration
# repeats it defensively; a future provider must not rely on post-filtering alone.
_VISIBLE = """
    project_id=$1 AND status='active'
    AND (valid_from IS NULL OR valid_from <= now()) AND (expires_at IS NULL OR expires_at > now())
    AND classification=ANY($2::text[]) AND ($3::text IS NULL OR kind=$3)
    AND ($4::text IS NULL OR source_lock_digest=$4)
"""
_MATCH = """
    search_document @@ plainto_tsquery('simple', $5) OR NOT EXISTS (
        SELECT 1 FROM unnest($6::text[]) AS term WHERE strpos(search_text, term)=0
    )
"""


def _scope(request: RetrievalRequest) -> tuple:
    return request.project_id, list(request.classifications), request.kind, request.source_lock_digest


class PostgresLexical:
    name = "postgres_lexical"
    capabilities = frozenset({"lexical", "substring", "prefiltered", "transactional"})
    _rank = "ts_rank_cd(search_document, plainto_tsquery('simple', $5))"

    async def candidates(self, conn: asyncpg.Connection, request: RetrievalRequest) -> list[Candidate]:
        rows = await conn.fetch(
            f"SELECT id, {self._rank} + CASE WHEN strpos(search_text,$5)>0 THEN 0.05 ELSE 0 END AS score "
            f"FROM memory_experiences WHERE {_VISIBLE} AND ({_MATCH}) "
            "ORDER BY score DESC,updated_at DESC,id DESC LIMIT $7",
            *_scope(request),
            request.query,
            list(request.terms),
            request.limit,
        )
        return [Candidate(row["id"], float(row["score"])) for row in rows]


class PostgresWeightedLexical(PostgresLexical):
    """Evaluation candidate, not vector/hybrid retrieval. No extra extension needed."""

    name = "postgres_weighted_lexical"
    _rank = """ts_rank_cd(
        setweight(to_tsvector('simple',title),'A') ||
        setweight(to_tsvector('simple',array_to_string(tags,' ')),'B') ||
        setweight(to_tsvector('simple',content),'D'), plainto_tsquery('simple',$5))"""


_PROVIDERS: dict[str, RetrievalProvider] = {
    provider.name: provider for provider in (PostgresLexical(), PostgresWeightedLexical())
}


async def fetch_rows(request: RetrievalRequest, strategy: str) -> list[dict]:
    provider = _PROVIDERS[strategy]  # Settings validates the allowlist; not caller-controlled.
    async with get_pool().acquire() as conn, conn.transaction(isolation="repeatable_read", readonly=True):
        await conn.execute("SET LOCAL statement_timeout = '2000ms'")
        candidates = await provider.candidates(conn, request)
        # Bound and deduplicate nominations. Providers cannot supply text or citations.
        scores = {}
        for candidate in candidates[: request.limit]:
            if math.isfinite(candidate.score):
                scores.setdefault(candidate.memory_id, candidate.score)
        rows = await conn.fetch(
            "SELECT id,project_id,title,content,tags,kind,classification,source_handoff_id,source_lock_digest,"
            "source_payload_digest,version,revision_root_id,revision_number,is_correction "
            f"FROM memory_experiences WHERE {_VISIBLE} AND id=ANY($5::uuid[])",
            *_scope(request),
            list(scores),
        )
        by_id = {row["id"]: dict(row) for row in rows}
        return [{**by_id[memory_id], "score": score} for memory_id, score in scores.items() if memory_id in by_id]
