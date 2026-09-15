"""Pinned local recipe and bounded provider contract. No network provider is enabled."""

from dataclasses import dataclass
from typing import Protocol

from isekai_memory.retrieval.citations import canonical, digest

PROVIDER = "local_structured"
MODEL_VERSION = "extractive-v1"
PROMPT_VERSION = "result-summary-v1"
RECIPE = f"{PROVIDER}/{MODEL_VERSION}/{PROMPT_VERSION}"
SUMMARY_RECIPE = "local_structured/approved-references-v1/no-prompt"


class GenerationFailure(Exception):
    def __init__(self, code: str, *, retryable: bool = False):
        super().__init__(code)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class ExtractionInput:
    summary: str
    objective: str
    result_status: str


@dataclass(frozen=True)
class Candidate:
    kind: str
    title: str
    content: str


class ExtractionProvider(Protocol):
    recipe: str

    async def extract(self, source: ExtractionInput) -> Candidate | None: ...


def source_watermark(row) -> str:
    # Handoff delivery status/claim fields deliberately do not participate.
    return digest(canonical({key: str(row[key]) for key in (
        "id", "payload_digest", "envelope_digest", "classification", "lock_snapshot_digest", "phase_id",
    )}))
