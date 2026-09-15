"""Offline Git-friendly native archive import: bounded exact profile, quarantine only."""

import base64
import binascii
import gzip
import io
import json
import tarfile
from datetime import datetime
from uuid import UUID

from fastapi.encoders import jsonable_encoder
from jsonschema import Draft202012Validator, FormatChecker

from isekai_memory.experience.tools import _CLASSIFICATION, _ID, _KIND, _UUID, _VERSION
from isekai_memory.registry.verification import digest_bytes
from isekai_memory.retrieval.citations import canonical, digest
from isekai_memory.skills.export import MAX_EXPORT_BYTES, build
from isekai_memory.skills.submissions import prepare
from isekai_memory.team.common import ceiling, conflict, fail, fingerprint, listing, transaction
from isekai_memory.team.tools import DIGEST


def object_schema(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


BINDING = object_schema({
    "project_id": _ID, "memory_id": _UUID, "version": _VERSION, "classification": _CLASSIFICATION,
    "kind": _KIND, "source_handoff_id": _UUID, "source_lock_digest": DIGEST, "source_payload_digest": DIGEST,
    "citation": object_schema({"schema_version": {"const": 1}, "content_digest": DIGEST, "excerpt_digest": DIGEST, "binding_digest": DIGEST}),
})
SOURCE_DATA = object_schema({
    "project_id": _ID, "skill_id": _UUID, "revision_id": _UUID, "revision": _VERSION, "version": _VERSION,
    "classification": _CLASSIFICATION, "source_lock_digest": DIGEST, "source_watermark": DIGEST, "content_digest": DIGEST,
    "sources": {"type": "array", "minItems": 1, "maxItems": 8, "items": BINDING}, "usage": {"const": "evidence_only"},
})


def strict_json(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    return json.loads(data, object_pairs_hook=unique, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Non-finite JSON")))


def validate(arguments):
    """Accept only the exact deterministic M5 profile; never extract files or resolve remote bindings."""
    try:
        if len(arguments["archive_base64"]) > 349528:
            raise ValueError("Archive too large")
        payload = base64.b64decode(arguments["archive_base64"], validate=True)
        if (len(payload) > MAX_EXPORT_BYTES or base64.b64encode(payload).decode() != arguments["archive_base64"]
                or digest_bytes(payload) != arguments["archive_digest"]):
            raise ValueError("Archive too large")
        with gzip.GzipFile(fileobj=io.BytesIO(payload), mode="rb") as compressed:
            # Bound decompression before tar parsing, including headers, padding and extension records.
            unpacked = compressed.read(MAX_EXPORT_BYTES + 65537)
        if len(unpacked) > MAX_EXPORT_BYTES + 65536:
            raise ValueError("Expanded archive too large")
        files = {}
        with tarfile.open(fileobj=io.BytesIO(unpacked), mode="r:") as archive:
            for member in archive:
                if (len(files) >= 8 or not member.isfile() or member.name in files or member.pax_headers
                        or member.mode != 0o644 or not 0 <= member.size <= MAX_EXPORT_BYTES):
                    raise ValueError("Unsafe archive member")
                # All names must match a server-rebuilt archive below. No member ever reaches the filesystem.
                files[member.name] = archive.extractfile(member).read(MAX_EXPORT_BYTES + 1)
        if sum(map(len, files.values())) > MAX_EXPORT_BYTES:
            raise ValueError("Files too large")
        manifest = strict_json(files["manifest.json"])
        source = strict_json(files["source-bindings.json"])
        body = strict_json(files["draft.json"])
        if not Draft202012Validator(SOURCE_DATA, format_checker=FormatChecker()).is_valid(source):
            raise ValueError("Invalid source contract")
        normalized, _ = prepare({"body": body, "sources": source["sources"]})
        if normalized["body"] != body or [v["memory_id"] for v in source["sources"]] != [v["memory_id"] for v in normalized["sources"]]:
            raise ValueError("Non-canonical body or sources")
        for key in ("skill_id", "revision_id"):
            if source[key] != str(UUID(source[key])):
                raise ValueError("Non-canonical identity")
        if "procedure" not in {v["kind"] for v in source["sources"]}:
            raise ValueError("Missing procedure claim")
        for ref in source["sources"]:
            ceiling(ref["classification"], source["classification"])
            if ref["project_id"] != source["project_id"] or ref["source_lock_digest"] != source["source_lock_digest"]:
                raise ValueError("Inconsistent source claims")
        if source["source_watermark"] != digest(canonical(source["sources"])) or source["content_digest"] != digest(canonical({
            "body": body, "sources": source["sources"], "classification": source["classification"],
        })):
            raise ValueError("Invalid content binding")
        at = manifest["created_at"]
        if datetime.fromisoformat(at.replace("Z", "+00:00")).tzinfo is None:
            raise ValueError("Missing approval time offset")
        rebuilt = build({**source, "body": body, "approved_at": at})
        # Compare canonical tar, not gzip encoder bytes: different zlib builds/compression levels can
        # encode the same native artifact. The actual transport digest was checked independently above.
        rebuilt_tar = gzip.decompress(base64.b64decode(rebuilt["archive_base64"]))
        if unpacked != rebuilt_tar or any(rebuilt[key] != arguments[key] for key in ("manifest_digest", "artifact_digest")):
            raise ValueError("Archive does not match deterministic native Skill profile")
        ceiling(source["classification"], arguments["classification"])
        return {"body": body, "source_claims": source, "manifest": rebuilt["manifest"],
                "origin_key": digest(canonical([manifest["provenance"]["source_repository"], manifest["id"], manifest["version"]]))}
    except (ValueError, TypeError, KeyError, AttributeError, IndexError, RecursionError, OverflowError,
            OSError, EOFError, tarfile.TarError, binascii.Error) as exc:
        raise fail("Invalid, inconsistent or over-budget native Skill archive", "MEM-TEAM-0004", 400) from exc


async def ingest(arguments, *, actor_id):
    artifact = validate(arguments)
    request_digest = fingerprint({k: v for k, v in arguments.items() if k != "archive_base64"})
    async with transaction(arguments["project_id"]) as conn:
        old = await conn.fetchrow("SELECT * FROM memory_skill_imports WHERE project_id=$1 AND created_by=$2 AND idempotency_key=$3",
                                  arguments["project_id"], actor_id, arguments["idempotency_key"])
        if old:
            if old["submission_digest"] != request_digest:
                raise conflict()
            return {"import_id": str(old["id"]), "version": 1, "already_exists": True}
        # Even identical content under a new receipt must not silently bypass a prior erasure or reserve a new identity.
        if await conn.fetchval("SELECT 1 FROM memory_skill_imports WHERE project_id=$1 AND origin_key=$2",
                               arguments["project_id"], artifact["origin_key"]):
            raise conflict()
        iid = await conn.fetchval("""
            INSERT INTO memory_skill_imports(project_id,origin_key,archive_digest,manifest_digest,artifact_digest,
                classification,payload,created_by,idempotency_key,submission_digest)
            VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8,$9,$10) RETURNING id
        """, arguments["project_id"], artifact["origin_key"], arguments["archive_digest"], arguments["manifest_digest"],
            arguments["artifact_digest"], arguments["classification"], artifact, actor_id, arguments["idempotency_key"], request_digest)
        return {"import_id": str(iid), "version": 1, "already_exists": False, "status": "quarantined", "usage": "review_only", "trusted": False}


async def inspect(arguments):
    async with transaction(arguments["project_id"]) as conn:
        row = await conn.fetchrow("SELECT * FROM memory_skill_imports WHERE id=$1::uuid AND project_id=$2",
                                  arguments["import_id"], arguments["project_id"])
        if not row:
            raise fail()
        ceiling(row["classification"], arguments.get("max_classification", "internal"))
        result = {key: value for key, value in dict(row).items() if key not in {"id", "idempotency_key", "submission_digest"}}
        return jsonable_encoder({"import_id": row["id"], **result, "usage": "review_only", "trusted": False, "cache_policy": "no_store"})


async def forget(arguments, *, actor_id):
    async with transaction(arguments["project_id"]) as conn:
        row = await conn.fetchrow("SELECT * FROM memory_skill_imports WHERE id=$1::uuid AND project_id=$2",
                                  arguments["import_id"], arguments["project_id"])
        if not row:
            raise fail()
        if arguments["expected_version"] == 1 and row["version"] == 2 and row["forgotten_by"] == actor_id:
            return {"import_id": str(row["id"]), "version": 2, "already_applied": True}
        if row["version"] != 1 or arguments["expected_version"] != 1:
            raise conflict()
        await conn.execute("UPDATE memory_skill_imports SET payload='{}'::jsonb,status='forgotten',version=2,forgotten_by=$2 WHERE id=$1",
                           row["id"], actor_id)
        return {"import_id": str(row["id"]), "version": 2, "already_applied": False}


async def list_imports(arguments):
    return await listing(arguments, table="memory_skill_imports", view="imports",
                         columns="id,origin_key,archive_digest,manifest_digest,artifact_digest,classification,status,version,created_by,created_at",
                         extra="AND status=$5", extra_values=(arguments.get("status", "quarantined"),))
