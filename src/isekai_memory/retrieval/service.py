"""Validated queries, total time bounds and serialized result budgets."""

from __future__ import annotations

import asyncio
import re
import unicodedata

import asyncpg

from isekai_memory.retrieval.citations import attach, canonical
from isekai_memory.retrieval.contracts import RetrievalRequest
from isekai_memory.retrieval.postgres import fetch_rows
from isekai_memory.server.errors import MemoryToolError

CLASSIFICATIONS = ("public", "internal", "confidential", "restricted")


async def search(arguments: dict, *, strategy: str = "postgres_lexical") -> dict:
    query = unicodedata.normalize("NFKC", arguments["query"]).casefold().strip()
    terms = tuple(dict.fromkeys(re.findall(r"\w+", query)))
    if len(query) > 512 or not terms or len(terms) > 16:
        raise MemoryToolError(
            "Search requires 1–16 distinct word terms and at most 512 normalized characters",
            code=-32602,
            data={"error_code": "MEM-EXPERIENCE-0005"},
        )
    limit = arguments.get("limit", 10)
    budget = arguments.get("max_chars", 8000)
    request = RetrievalRequest(
        project_id=arguments["project_id"],
        query=query,
        terms=terms,
        classifications=CLASSIFICATIONS[: CLASSIFICATIONS.index(arguments.get("max_classification", "internal")) + 1],
        kind=arguments.get("kind"),
        source_lock_digest=arguments.get("source_lock_digest"),
        limit=limit + 1,
        compatibility_digest=arguments.get("compatibility_digest"),
    )
    try:
        # Includes pool wait, provider work and hydration, not only SQL execution.
        async with asyncio.timeout(2.5):
            rows = await fetch_rows(request, strategy)
    except (TimeoutError, asyncpg.QueryCanceledError) as exc:
        raise MemoryToolError(
            "Experience search exceeded its time budget; narrow the query",
            data={"error_code": "MEM-EXPERIENCE-0006"},
            http_status=503,
        ) from exc
    except (OSError, asyncpg.PostgresConnectionError) as exc:
        raise MemoryToolError(
            "Experience retrieval is unavailable", data={"error_code": "MEM-EXPERIENCE-0011"}, http_status=503
        ) from exc
    items = []
    used = 2
    clipped = False
    for row in rows[:limit]:
        item = attach(row)
        size = len(canonical(item)) + int(bool(items))
        if used + size > budget:
            # Keep provenance intact; shorten only the excerpt and rebind its hash.
            low, high, fitted = 1, len(item["excerpt"]), None
            while low <= high:
                middle = (low + high) // 2
                candidate = attach(row, excerpt_chars=middle)
                candidate_size = len(canonical(candidate)) + int(bool(items))
                if used + candidate_size <= budget:
                    fitted = candidate, candidate_size
                    low = middle + 1
                else:
                    high = middle - 1
            if fitted is None:
                break
            item, size = fitted
            clipped = True
        items.append(item)
        used += size
    return {
        "items": items,
        "returned": len(items),
        "truncated": clipped or len(items) < len(rows),
        "result_chars": used,
        "max_chars": budget,
        "strategy": strategy,
        "usage": "reference_only",
        "citation_schema_version": 2 if request.compatibility_digest else 1,
    }
