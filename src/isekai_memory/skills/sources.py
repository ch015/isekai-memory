"""Canonical multi-source binding and live validity checks before review/export."""

from uuid import UUID

from isekai_memory.experience.service import CLASSIFICATIONS
from isekai_memory.retrieval.citations import attach, canonical, digest
from isekai_memory.server.errors import MemoryToolError


def fail(message="Skill or its exact approved sources are unavailable", code="MEM-SKILL-0001", status=409):
    return MemoryToolError(message, data={"error_code": code}, http_status=status)


def refs(values):
    result = sorted([{"memory_id": str(UUID(item["memory_id"])), "version": item["version"]} for item in values],
                    key=lambda item: item["memory_id"])
    if not 1 <= len(result) <= 8 or len({v["memory_id"] for v in result}) != len(result):
        raise fail("Skill sources must contain 1–8 distinct experiences", "MEM-SKILL-0002", 400)
    return result


async def capture(conn, project_id, references):
    references = refs(references)
    rows = await conn.fetch("""
        SELECT m.id,m.project_id,m.version,m.classification,m.kind,m.title,m.content,m.tags,
               m.source_handoff_id,m.source_lock_digest,m.source_payload_digest,
               h.phase_id
        FROM memory_experiences m JOIN handoffs h ON h.id=m.source_handoff_id AND h.project_id=m.project_id
        WHERE m.project_id=$1 AND m.id=ANY($2::uuid[]) AND m.status='active'
          AND (m.valid_from IS NULL OR m.valid_from <= clock_timestamp())
          AND (m.expires_at IS NULL OR m.expires_at > clock_timestamp())
          AND m.source_payload_digest=h.payload_digest AND m.source_lock_digest=h.lock_snapshot_digest
          AND m.source->>'envelope_digest'=h.envelope_digest AND m.source->>'classification'=h.classification
          AND h.result_status='succeeded'
          AND jsonb_array_length(CASE WHEN jsonb_typeof(h.result_envelope->'evidence_refs')='array'
              THEN h.result_envelope->'evidence_refs' ELSE '[]'::jsonb END) > 0
        ORDER BY m.id
    """, project_id, [UUID(item["memory_id"]) for item in references])
    if len(rows) != len(references) or any(str(row["id"]) != ref["memory_id"] or row["version"] != ref["version"]
                                         for row, ref in zip(rows, references, strict=True)):
        raise fail()
    if "procedure" not in {row["kind"] for row in rows} or len({row["source_lock_digest"] for row in rows}) != 1:
        raise fail("Skill needs an approved procedure and sources from exactly one Lock", "MEM-SKILL-0002")
    bindings, evidence = [], []
    for row in rows:
        item = attach({key: value for key, value in dict(row).items() if key != "phase_id"})
        bindings.append({key: item[key] for key in (
            "project_id", "memory_id", "version", "classification", "kind", "source_handoff_id",
            "source_lock_digest", "source_payload_digest", "citation",
        )})
        evidence.append(item)
    return {
        "bindings": bindings, "source_watermark": digest(canonical(bindings)),
        "classification": max((row["classification"] for row in rows), key=CLASSIFICATIONS.index),
        "source_lock_digest": rows[0]["source_lock_digest"], "evidence": evidence,
    }


async def saved(conn, row):
    values = await conn.fetch("SELECT binding FROM memory_skill_sources WHERE revision_id=$1 ORDER BY memory_id", row["id"])
    return [value["binding"] for value in values]


async def freshness(conn, row, bindings):
    try:
        current = await capture(conn, row["project_id"], bindings)
    except MemoryToolError:
        return False, []
    return current["source_watermark"] == row["source_watermark"], current["evidence"]
