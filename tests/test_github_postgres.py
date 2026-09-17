"""GitHub/Entra users share explicit project roles, never implicit email linking."""

from uuid import uuid4

import pytest

from isekai_memory.server.auth import Principal
from isekai_memory.server.errors import MemoryToolError
from isekai_memory.store import github_identities, identities
from isekai_memory.store.database import get_pool
from tests.test_project_directory import metadata
from tests.test_project_directory_postgres import directory, pytestmark  # noqa: F401


async def test_github_entra_assignment_and_disable(directory):  # noqa: F811
    dispatch, project = directory
    identifier = str(uuid4().int % 10**18 + 1)
    github_id = await github_identities.resolve(identifier, "DevSecOps")
    entra_id = await identities.resolve(str(uuid4()), str(uuid4()), "DevSecOps")
    owner = Principal(
        github_id, None, frozenset({"read", "write", "projects"}), provider="github", organization_id="DevSecOps"
    )
    member = Principal(entra_id, None, owner.scopes, provider="entra", organization_id="DevSecOps")
    await dispatch("memory_project_register", {**metadata(project), "organization_id": "DevSecOps"}, owner)
    assert (await dispatch("memory_project_list", {}, member))["items"] == []
    await dispatch(
        "memory_project_assign",
        {"project_id": project, "user_id": entra_id, "role": "write", "expected_revision": 1},
        owner,
    )
    assert (await dispatch("memory_project_list", {}, member))["items"][0]["project_id"] == project
    with pytest.raises(MemoryToolError):
        await dispatch("memory_project_register", {**metadata(project), "organization_id": "other"}, owner)
    async with get_pool().acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM memory_eligible_members WHERE project_id=$1", project)
        assert {row["user_id"] for row in rows} == {github_id, entra_id}
        await conn.execute("UPDATE memory_github_identities SET disabled_at=now() WHERE github_id=$1", identifier)
        with pytest.raises(MemoryToolError):
            await github_identities.resolve(identifier, "DevSecOps")
        rows = await conn.fetch("SELECT user_id FROM memory_eligible_members WHERE project_id=$1", project)
        assert {row["user_id"] for row in rows} == {entra_id}


async def test_github_prelogin_binding_cannot_move_history(directory):  # noqa: F811
    _, actor = directory
    identifier = str(uuid4().int % 10**18 + 1)
    await github_identities.bind_legacy(identifier, actor, "DevSecOps")
    assert await github_identities.resolve(identifier, "DevSecOps") == actor
    with pytest.raises(ValueError):
        await github_identities.bind_legacy(identifier, "different", "DevSecOps")
    with pytest.raises(ValueError):
        await github_identities.bind_legacy(str(int(identifier) + 1), actor, "DevSecOps")
