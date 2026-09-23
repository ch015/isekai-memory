"""Internal provider boundary. Providers nominate IDs; PostgreSQL owns visibility."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

import asyncpg


@dataclass(frozen=True)
class RetrievalRequest:
    project_id: str
    query: str
    terms: tuple[str, ...]
    classifications: tuple[str, ...]
    kind: str | None
    source_lock_digest: str | None
    limit: int
    compatibility_digest: str | None = None


@dataclass(frozen=True)
class Candidate:
    memory_id: UUID
    score: float


class RetrievalProvider(Protocol):
    name: str
    capabilities: frozenset[str]

    async def candidates(self, conn: asyncpg.Connection, request: RetrievalRequest) -> list[Candidate]: ...
