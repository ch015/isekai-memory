import hashlib
import json

import pytest

from isekai_memory.projects import service
from isekai_memory.server.auth import Principal, authorize_tool
from isekai_memory.server.errors import MemoryToolError


def metadata(project_id="project-a"):
    setup = {"schema_version": 1, "config": {"project_id": project_id, "credential_refs": []}, "artifacts": []}
    setup["digest"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(setup, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()
    )
    return {
        "project_id": project_id,
        "organization_id": "org",
        "name": "Project",
        "git_url": "https://example.com/repo.git",
        "git_ref": "main",
        "setup": setup,
        "expected_revision": 0,
    }


@pytest.mark.asyncio
async def test_directory_binding_requires_assignment_and_intersects_scope(monkeypatch):
    actor = Principal("alice", "directory", frozenset({"read", "write", "admin", "projects"}))

    async def member(project, user):
        return {"project_id": project}, "read"

    monkeypatch.setattr(service, "access", member)
    bound = await service.bind(actor, "memory_handoff_list", {"project_id": "project-a"})
    assert bound.project_id == "project-a"
    assert bound.scopes == frozenset({"read", "projects"})
    authorize_tool(bound, "memory_handoff_list", {"project_id": "project-a"})
    with pytest.raises(MemoryToolError):
        authorize_tool(bound, "memory_handoff_push", {"project_id": "project-a"})

    async def absent(project, user):
        return {"project_id": project}, None

    monkeypatch.setattr(service, "access", absent)
    with pytest.raises(MemoryToolError):
        await service.bind(actor, "memory_project_get", {"project_id": "project-b"})


@pytest.mark.asyncio
async def test_existing_project_token_cannot_become_multi_project():
    actor = Principal("alice", "project-a", frozenset({"read", "write", "admin"}))
    assert await service.bind(actor, "memory_project_get", {"project_id": "project-b"}) == actor
    with pytest.raises(MemoryToolError):
        authorize_tool(actor, "memory_project_get", {"project_id": "project-b"})


def test_catalog_manifest_rejects_private_config_and_git_command_syntax():
    args = metadata()
    service.validate_metadata(args)
    for url in (
        "file:///tmp/repo",
        "ext::sh command",
        "https://token@example.com/repo",
        "https://a:secret@example.com/repo",
    ):
        with pytest.raises(MemoryToolError):
            service.validate_metadata({**args, "git_url": url})
    with pytest.raises(MemoryToolError):
        service.validate_metadata({**args, "git_ref": "--upload-pack=bad"})
    args["setup"]["config"]["gateway_policy"] = {"trusted_callers": []}
    with pytest.raises(MemoryToolError):
        service.validate_metadata(args)


def test_config_tampering_fails_digest():
    args = metadata()
    args["setup"]["artifacts"] = [{"unexpected": "tampered"}]
    with pytest.raises(MemoryToolError):
        service.validate_metadata(args)


def test_non_git_metadata_accepts_absence_and_rejects_partial_resource():
    args = metadata()
    args.pop("git_url")
    args.pop("git_ref")
    service.validate_metadata(args)
    service.validate_metadata({**args, "git_url": None, "git_ref": None})
    for extra in ({"git_url": "https://example.com/a.git"}, {"git_ref": "main"}, {"git_url": "", "git_ref": ""}):
        with pytest.raises(MemoryToolError):
            service.validate_metadata({**args, **extra})


def test_source_kind_is_independent_of_clone_coordinates():
    args = {**metadata(), "git_url": None, "git_ref": None}
    for kind in ("git", "directory", "unknown"):
        service.validate_metadata({**args, "source_kind": kind})
    for kind in ("directory", "unknown", "unsupported"):
        with pytest.raises(MemoryToolError):
            service.validate_metadata({**metadata(), "source_kind": kind})
