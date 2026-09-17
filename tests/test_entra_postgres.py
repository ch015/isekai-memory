"""Migration, stable user mappings and token-independent collaboration membership."""

from uuid import uuid4

import pytest

from isekai_memory.server.auth import Principal
from isekai_memory.server.errors import MemoryToolError
from isekai_memory.store import identities
from isekai_memory.store.database import get_pool
from tests.test_project_directory import metadata
from tests.test_project_directory_postgres import directory, pytestmark  # noqa: F401


async def test_identity_lifecycle_and_project_assignment(directory):  # noqa: F811
    dispatch, project = directory
    tenant, alice, bob = [str(uuid4()) for _ in range(3)]
    owner_id = await identities.resolve(tenant, alice, "DevSecOps")
    member_id = await identities.resolve(tenant, bob, "DevSecOps")
    assert owner_id == await identities.resolve(tenant, alice, "DevSecOps")
    owner = Principal(
        owner_id, None, frozenset({"read", "write", "projects"}), provider="entra", organization_id="DevSecOps"
    )
    member = Principal(member_id, None, owner.scopes, provider="entra", organization_id="DevSecOps")
    await dispatch("memory_project_register", {**metadata(project), "organization_id": "DevSecOps"}, owner)
    assert (await dispatch("memory_project_list", {}, member))["items"] == []
    assignment = {"project_id": project, "user_id": member_id, "role": "write", "expected_revision": 1}
    await dispatch("memory_project_assign", assignment, owner)
    assert (await dispatch("memory_project_list", {}, member))["items"][0]["project_id"] == project
    async with get_pool().acquire() as conn:

        async def members():
            return {
                r["user_id"]
                for r in await conn.fetch("SELECT user_id FROM memory_eligible_members WHERE project_id=$1", project)
            }

        assert await members() == {owner_id, member_id}
        await conn.execute("UPDATE memory_identities SET disabled_at=now() WHERE user_id=$1", member_id)
        assert await members() == {owner_id}
        with pytest.raises(MemoryToolError):
            await identities.resolve(tenant, bob, "DevSecOps")
        await conn.execute("UPDATE memory_identities SET disabled_at=NULL WHERE user_id=$1", member_id)
    await dispatch("memory_project_assign", {**assignment, "role": "remove", "expected_revision": 2}, owner)
    assert (await dispatch("memory_project_list", {}, member))["items"] == []
    with pytest.raises(MemoryToolError):
        await dispatch("memory_project_get", {"project_id": project}, member)


async def test_legacy_binding_is_explicit_unique_and_never_moves_history(directory):  # noqa: F811
    _, suffix = directory
    tenant, oid, other = [str(uuid4()) for _ in range(3)]
    await identities.bind_legacy(tenant, oid, suffix, "DevSecOps")
    assert await identities.resolve(tenant, oid, "DevSecOps") == suffix
    with pytest.raises(ValueError):
        await identities.bind_legacy(tenant, oid, "new-owner", "DevSecOps")
    with pytest.raises(ValueError):
        await identities.bind_legacy(tenant, other, suffix, "DevSecOps")
