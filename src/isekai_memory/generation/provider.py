"""Deterministic baseline: quote ResultEnvelope.summary; do not infer advice."""

import re
import unicodedata

from isekai_memory.generation.contracts import RECIPE, Candidate, ExtractionInput, GenerationFailure

_SENSITIVE = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
    r"\b(?:password|passwd|api[_-]?key|secret|token)\s*[:=]\s*\S+|\bBearer\s+\S+",
    re.IGNORECASE,
)


class StructuredExtractor:
    recipe = RECIPE

    async def extract(self, source: ExtractionInput) -> Candidate | None:
        content = unicodedata.normalize("NFC", source.summary).strip()
        title = unicodedata.normalize("NFC", source.objective).strip()[:200] or "Recorded work result"
        if _SENSITIVE.search(content + "\n" + title):
            raise GenerationFailure("sensitive_source")
        if not content:
            return None
        # The fact is an attributed report, not a verified success claim or a procedure.
        return Candidate(kind="fact", title=title, content=content)
