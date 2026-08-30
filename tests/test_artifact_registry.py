from __future__ import annotations

import base64

import pytest

from isekai_memory.config import Settings
from isekai_memory.registry.catalog import publish_artifact
from isekai_memory.registry.verification import digest_bytes, verify_archive
from isekai_memory.server.errors import MemoryToolError
from tests.helpers import build_artifact_archive


def test_core_compatible_archive_verifies() -> None:
    archive, manifest = build_artifact_archive()
    verified = verify_archive(archive, max_members=100, max_uncompressed_bytes=1 << 20)
    assert verified.artifact_digest == manifest["artifact_digest"]
    assert verified.archive_digest == digest_bytes(archive)
    assert verified.manifest["id"] == "demo"


def test_archive_file_tampering_is_rejected() -> None:
    archive, _ = build_artifact_archive(archive_payload=b"tampered")
    with pytest.raises(MemoryToolError, match="size or digest mismatch"):
        verify_archive(archive, max_members=100, max_uncompressed_bytes=1 << 20)


@pytest.mark.asyncio
async def test_publish_enforces_strict_base64(monkeypatch: pytest.MonkeyPatch) -> None:
    async def unexpected(**kwargs):  # pragma: no cover
        raise AssertionError(kwargs)

    monkeypatch.setattr("isekai_memory.registry.catalog.queries.insert_artifact", unexpected)
    with pytest.raises(MemoryToolError, match="valid base64"):
        await publish_artifact(
            {
                "artifact_id": "demo", "kind": "foundation", "version": "1.0.0",
                "archive_base64": "%%%", "manifest_digest": "sha256:" + "0" * 64,
                "artifact_digest": "sha256:" + "0" * 64, "archive_digest": "sha256:" + "0" * 64,
            },
            settings=Settings(),
        )


@pytest.mark.asyncio
async def test_publish_sends_three_verified_digests(monkeypatch: pytest.MonkeyPatch) -> None:
    archive, manifest = build_artifact_archive()
    verified = verify_archive(archive, max_members=100, max_uncompressed_bytes=1 << 20)
    captured = {}

    async def insert_artifact(**kwargs):
        captured.update(kwargs)
        return {"id": "artifact-row", "published_at": __import__("datetime").datetime.now(__import__("datetime").UTC)}

    monkeypatch.setattr("isekai_memory.registry.catalog.queries.insert_artifact", insert_artifact)
    result = await publish_artifact(
        {
            "artifact_id": "demo", "kind": "foundation", "version": "1.0.0",
            "archive_base64": base64.b64encode(archive).decode(),
            "manifest_digest": verified.manifest_digest,
            "artifact_digest": manifest["artifact_digest"],
            "archive_digest": verified.archive_digest,
        },
        settings=Settings(),
        published_by="user-1",
    )
    assert result["already_exists"] is False
    assert captured["artifact_digest"] == manifest["artifact_digest"]
    assert captured["archive_digest"] == digest_bytes(archive)
    assert captured["published_by"] == "user-1"
