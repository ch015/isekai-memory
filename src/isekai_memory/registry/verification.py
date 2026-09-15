"""Verification of untrusted ISEKAI artifact archives.

This module mirrors the relevant isekai-core archive contract without importing
Core at runtime: gzip tar, regular files only, manifest-bound identity and file
records, and three distinct digests.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import tarfile
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from isekai_memory.server.errors import MemoryToolError

_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_VERSION_RE = re.compile(r"^[0-9]+(?:\.[0-9]+){0,2}(?:[-+][0-9A-Za-z.-]+)?$")
MAX_MANIFEST_BYTES = 4 << 20


@dataclass(frozen=True)
class VerifiedArchive:
    manifest: dict[str, Any]
    manifest_digest: str
    artifact_digest: str
    archive_digest: str


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def digest_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _fail(message: str, **details: Any) -> MemoryToolError:
    return MemoryToolError(
        message,
        data={"error_code": "MEM-REGISTRY-0005", **details},
    )


def _safe_member_name(name: str) -> str:
    if not name or "\\" in name or name.startswith("/") or name.endswith("/"):
        raise _fail("archive member path is unsafe", path=name)
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise _fail("archive member path is unsafe", path=name)
    normalized = path.as_posix()
    if len(normalized) > 1024:
        raise _fail("archive member path exceeds limit", path=name)
    return normalized


def _validate_manifest_shape(manifest: dict[str, Any]) -> None:
    required = {
        "schema_version",
        "kind",
        "id",
        "version",
        "protocol_major",
        "requires",
        "files",
        "content",
        "artifact_digest",
        "provenance",
        "created_at",
    }
    missing = sorted(required - manifest.keys())
    if missing:
        raise _fail("artifact manifest is missing required fields", missing=missing)
    if manifest["schema_version"] != 2:
        raise _fail("unsupported artifact schema_version", value=manifest["schema_version"])
    if manifest["kind"] not in ("foundation", "preset"):
        raise _fail("unsupported artifact kind", value=manifest["kind"])
    if not isinstance(manifest["id"], str) or not _ID_RE.fullmatch(manifest["id"]):
        raise _fail("artifact id is invalid")
    if not isinstance(manifest["version"], str) or not _VERSION_RE.fullmatch(manifest["version"]):
        raise _fail("artifact version is invalid")
    if not isinstance(manifest["protocol_major"], int) or manifest["protocol_major"] < 1:
        raise _fail("artifact protocol_major is invalid")
    if not isinstance(manifest["requires"], dict) or not isinstance(manifest["requires"].get("core_protocol"), str):
        raise _fail("artifact requires.core_protocol is invalid")
    if not isinstance(manifest["provenance"], dict):
        raise _fail("artifact provenance must be an object")
    if not isinstance(manifest["created_at"], str) or not manifest["created_at"].endswith("Z"):
        raise _fail("artifact created_at must be a UTC timestamp")
    if not isinstance(manifest["artifact_digest"], str) or not _DIGEST_RE.fullmatch(manifest["artifact_digest"]):
        raise _fail("artifact_digest is invalid")

    content = manifest["content"]
    expected_schema = f"urn:isekai:schema:{manifest['kind']}-policy"
    if not isinstance(content, dict) or set(content) != {"path", "schema"} or content.get("schema") != expected_schema:
        raise _fail("artifact content descriptor is invalid")

    files = manifest["files"]
    if not isinstance(files, list) or not 1 <= len(files) <= 10_000:
        raise _fail("artifact files must contain between 1 and 10000 records")
    seen: set[str] = set()
    for index, record in enumerate(files):
        if not isinstance(record, dict) or set(record) != {"path", "digest", "size", "mode", "executable"}:
            raise _fail("artifact file record is invalid", index=index)
        path = _safe_member_name(record["path"]) if isinstance(record.get("path"), str) else ""
        if not path or path == "manifest.json" or path in seen:
            raise _fail("artifact file path is duplicate or reserved", index=index, path=path)
        seen.add(path)
        if not isinstance(record["digest"], str) or not _DIGEST_RE.fullmatch(record["digest"]):
            raise _fail("artifact file digest is invalid", index=index)
        if not isinstance(record["size"], int) or not 0 <= record["size"] <= 1 << 30:
            raise _fail("artifact file size is invalid", index=index)
        if record["mode"] not in ("data", "instruction", "executable"):
            raise _fail("artifact file mode is invalid", index=index)
        if not isinstance(record["executable"], bool) or (record["mode"] == "executable") != record["executable"]:
            raise _fail("artifact file executable flag is inconsistent", index=index)
    if content["path"] not in seen:
        raise _fail("artifact content path is not declared in files")


def verify_archive(
    archive_bytes: bytes,
    *,
    max_members: int,
    max_uncompressed_bytes: int,
) -> VerifiedArchive:
    """Verify archive structure, manifest, files, and Core digest semantics."""
    if not archive_bytes:
        raise _fail("artifact archive is empty")
    observed: dict[str, dict[str, Any]] = {}
    manifest_payload: bytes | None = None
    total_size = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as archive:
            for index, member in enumerate(archive, start=1):
                if index > max_members:
                    raise _fail("archive member count exceeds limit")
                name = _safe_member_name(member.name)
                if name in observed:
                    raise _fail("archive contains duplicate member", path=name)
                if not member.isfile():
                    raise _fail("archive member is not a regular file", path=name)
                total_size += member.size
                if total_size > max_uncompressed_bytes:
                    raise _fail("archive uncompressed size exceeds limit")
                if name == "manifest.json" and member.size > MAX_MANIFEST_BYTES:
                    raise _fail("artifact manifest exceeds size limit")
                source = archive.extractfile(member)
                if source is None:
                    raise _fail("archive member cannot be read", path=name)
                digest = hashlib.sha256()
                chunks: list[bytes] | None = [] if name == "manifest.json" else None
                remaining = member.size
                while remaining:
                    chunk = source.read(min(1 << 20, remaining))
                    if not chunk:
                        raise _fail("archive member is truncated", path=name)
                    digest.update(chunk)
                    if chunks is not None:
                        chunks.append(chunk)
                    remaining -= len(chunk)
                if source.read(1):
                    raise _fail("archive member exceeds declared size", path=name)
                observed[name] = {
                    "size": member.size,
                    "digest": "sha256:" + digest.hexdigest(),
                    "executable": bool(member.mode & 0o111),
                }
                if chunks is not None:
                    manifest_payload = b"".join(chunks)
    except MemoryToolError:
        raise
    except (OSError, tarfile.TarError) as error:
        raise _fail("artifact archive cannot be parsed", cause=str(error)) from error

    if manifest_payload is None:
        raise _fail("archive does not contain manifest.json")
    try:
        manifest = json.loads(manifest_payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _fail("artifact manifest cannot be parsed") from error
    if not isinstance(manifest, dict):
        raise _fail("artifact manifest must be an object")
    _validate_manifest_shape(manifest)

    records = {record["path"]: record for record in manifest["files"]}
    expected_names = {"manifest.json", *records}
    if set(observed) != expected_names:
        raise _fail(
            "archive members differ from manifest declarations",
            missing=sorted(expected_names - observed.keys()),
            undeclared=sorted(observed.keys() - expected_names),
        )
    for path, record in records.items():
        actual = observed[path]
        if actual["size"] != record["size"] or actual["digest"] != record["digest"]:
            raise _fail("artifact file size or digest mismatch", path=path)
        if actual["executable"] != record["executable"]:
            raise _fail("artifact file executable mode mismatch", path=path)

    digest_material = dict(manifest)
    digest_material.pop("artifact_digest", None)
    digest_material.pop("signatures", None)
    artifact_digest = digest_bytes(canonical_bytes(digest_material))
    if manifest["artifact_digest"] != artifact_digest:
        raise _fail("manifest artifact_digest mismatch", computed=artifact_digest)

    return VerifiedArchive(
        manifest=manifest,
        manifest_digest=digest_bytes(manifest_payload),
        artifact_digest=artifact_digest,
        archive_digest=digest_bytes(archive_bytes),
    )
