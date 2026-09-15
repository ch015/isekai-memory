"""Explicit dispatch to three live reference types. Never returns lifecycle/admin data."""

from fastapi.encoders import jsonable_encoder

from isekai_memory.experience.service import CLASSIFICATIONS
from isekai_memory.retrieval.citations import attach, canonical, digest
from isekai_memory.skills.reads import get as skill_get
from isekai_memory.team import knowledge
from isekai_memory.team.common import fail


async def resolve(conn, project_id, kind, asset_id, version, *, maximum="internal", lock_digest=None):
    if kind == "skill":
        row = await skill_get(conn, {"project_id": project_id, "revision_id": asset_id, "expected_version": version,
                                     "max_classification": maximum, "source_lock_digest": lock_digest})
        content = {key: row[key] for key in ("project_id", "revision_id", "skill_id", "revision", "version", "name", "body",
                    "classification", "source_lock_digest", "source_watermark", "content_digest", "sources")}
        binding = row["content_digest"]
    elif kind == "knowledge":
        if lock_digest is not None:
            raise fail()  # Wiki snapshots have no Core Lock; never pretend to match one.
        content = await knowledge.get(conn, {"project_id": project_id, "document_id": asset_id, "expected_version": version,
                                            "max_classification": maximum})
        binding = digest(canonical({key: content[key] for key in ("document_id", "version", "source_revision", "classification", "content_digest")}))
    elif kind == "experience":
        row = await conn.fetchrow("""
            SELECT m.id,m.project_id,m.version,m.classification,m.kind,m.title,m.content,m.tags,
                   m.source_handoff_id,m.source_lock_digest,m.source_payload_digest
            FROM memory_experiences m JOIN handoffs h ON h.id=m.source_handoff_id AND h.project_id=m.project_id
            WHERE m.project_id=$1 AND m.id=$2::uuid AND m.version=$3 AND m.status='active'
                AND (m.valid_from IS NULL OR m.valid_from<=clock_timestamp())
                AND (m.expires_at IS NULL OR m.expires_at>clock_timestamp()) AND m.classification=ANY($4::text[])
                AND ($5::text IS NULL OR m.source_lock_digest=$5)
                AND m.source_payload_digest=h.payload_digest AND m.source_lock_digest=h.lock_snapshot_digest
                AND m.source->>'envelope_digest'=h.envelope_digest AND m.source->>'classification'=h.classification
        """, project_id, asset_id, version, list(CLASSIFICATIONS[:CLASSIFICATIONS.index(maximum) + 1]), lock_digest)
        if not row:
            raise fail()
        row = dict(row)
        content = {**attach(row), "content": row["content"], "tags": row["tags"]}
        binding = content["citation"]["binding_digest"]
    else:
        raise fail()
    return jsonable_encoder({"asset_kind": kind, "asset_id": str(asset_id), "asset_version": version,
                             "asset_digest": binding, "classification": content["classification"], "data": content})
