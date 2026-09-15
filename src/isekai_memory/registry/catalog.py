"""Artifact Registry business logic — publish, resolve, fetch."""

from __future__ import annotations

import base64
import binascii
from typing import Any

from isekai_memory.config import Settings
from isekai_memory.registry.policy import resolve_policies
from isekai_memory.registry.verification import digest_bytes, verify_archive
from isekai_memory.server.errors import MemoryToolError
from isekai_memory.store import queries


async def publish_artifact(
    arguments: dict[str, Any],
    *,
    settings: Settings | None = None,
    published_by: str = "local-stdio",
) -> dict[str, Any]:
    """Verify and register an immutable Core-compatible artifact archive."""
    settings = settings or Settings()
    try:
        archive_bytes = base64.b64decode(arguments["archive_base64"], validate=True)
    except (binascii.Error, ValueError) as error:
        raise MemoryToolError(
            "archive_base64 is not valid base64",
            data={"error_code": "MEM-REGISTRY-0005"},
        ) from error
    if len(archive_bytes) > settings.max_archive_bytes:
        raise MemoryToolError(
            "artifact archive exceeds compressed size limit",
            data={"error_code": "MEM-REGISTRY-0005", "max_bytes": settings.max_archive_bytes},
        )

    verified = verify_archive(
        archive_bytes,
        max_members=settings.max_archive_members,
        max_uncompressed_bytes=settings.max_archive_uncompressed_bytes,
    )
    identity = (verified.manifest["id"], verified.manifest["kind"], verified.manifest["version"])
    requested = (arguments["artifact_id"], arguments["kind"], arguments["version"])
    if identity != requested:
        raise MemoryToolError(
            "archive manifest identity differs from publish request",
            data={"error_code": "MEM-REGISTRY-0005", "manifest": identity, "requested": requested},
        )
    declared = {
        "manifest_digest": arguments["manifest_digest"],
        "artifact_digest": arguments["artifact_digest"],
        "archive_digest": arguments["archive_digest"],
    }
    computed = {
        "manifest_digest": verified.manifest_digest,
        "artifact_digest": verified.artifact_digest,
        "archive_digest": verified.archive_digest,
    }
    if declared != computed:
        raise MemoryToolError(
            "artifact digest verification failed",
            data={"error_code": "MEM-REGISTRY-0002", "declared": declared, "computed": computed},
        )

    row = await queries.insert_artifact(
        artifact_id=arguments["artifact_id"],
        kind=arguments["kind"],
        version=arguments["version"],
        manifest_digest=verified.manifest_digest,
        artifact_digest=verified.artifact_digest,
        archive_digest=verified.archive_digest,
        archive_blob=archive_bytes,
        archive_url=None,
        published_by=published_by,
        metadata=arguments.get("metadata"),
    )
    if row is None:
        existing = await queries.fetch_artifact(
            artifact_id=arguments["artifact_id"],
            kind=arguments["kind"],
            version=arguments["version"],
        )
        if existing is None:
            raise MemoryToolError("artifact conflict row disappeared", data={"error_code": "MEM-REGISTRY-0003"})
        existing_digests = {key: existing[key] for key in computed}
        if existing_digests != computed:
            raise MemoryToolError(
                "artifact identity already exists with different content",
                data={"error_code": "MEM-REGISTRY-0003", "existing": existing_digests, "submitted": computed},
            )
        return {"id": str(existing["id"]), "published_at": existing["published_at"].isoformat(), "already_exists": True}

    return {"id": str(row["id"]), "published_at": row["published_at"].isoformat(), "already_exists": False}


async def resolve_artifacts(arguments: dict[str, Any]) -> list[dict[str, Any]]:
    """Resolve required artifacts for a project based on organization policies."""
    organization_id = arguments["organization_id"]
    project_id = arguments["project_id"]
    policies = await queries.get_policies_for_org(organization_id=organization_id)
    if not policies:
        return []
    needed = {(policy["artifact_id"], policy["kind"]) for policy in policies}
    available_versions = {
        key: await queries.list_artifact_versions(artifact_id=key[0], kind=key[1]) for key in needed
    }
    return resolve_policies(policies, project_id, available_versions)


async def fetch_artifact(arguments: dict[str, Any]) -> dict[str, Any]:
    """Fetch an archive after checking logical and byte-level integrity."""
    row = await queries.fetch_artifact(
        artifact_id=arguments["artifact_id"],
        kind=arguments["kind"],
        version=arguments["version"],
    )
    if row is None:
        raise MemoryToolError(
            f"Artifact not found: {arguments['kind']}:{arguments['artifact_id']}@{arguments['version']}",
            data={"error_code": "MEM-REGISTRY-0001"},
        )
    if row["artifact_digest"] != arguments["expected_artifact_digest"]:
        raise MemoryToolError(
            "stored artifact_digest does not match expected",
            data={
                "error_code": "MEM-REGISTRY-0002",
                "stored": row["artifact_digest"],
                "expected": arguments["expected_artifact_digest"],
            },
        )
    archive_blob = row.get("archive_blob")
    if archive_blob is None:
        raise MemoryToolError(
            "artifact archive is not available",
            data={"error_code": "MEM-REGISTRY-0004"},
        )
    archive_bytes = bytes(archive_blob)
    computed_archive_digest = digest_bytes(archive_bytes)
    if computed_archive_digest != row["archive_digest"]:
        raise MemoryToolError(
            "stored archive failed integrity verification",
            data={"error_code": "MEM-REGISTRY-0002", "computed": computed_archive_digest},
        )
    return {
        "archive_base64": base64.b64encode(archive_bytes).decode("ascii"),
        "manifest_digest": row["manifest_digest"],
        "artifact_digest": row["artifact_digest"],
        "archive_digest": row["archive_digest"],
    }
