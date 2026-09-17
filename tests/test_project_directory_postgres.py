"""Disposable PostgreSQL tests for directory ownership, assignments, stale updates and token isolation."""

import os
from uuid import uuid4

import pytest
import pytest_asyncio

from isekai_memory.config import Settings
from isekai_memory.main import ToolDispatcher
from isekai_memory.server.auth import Principal
from isekai_memory.server.errors import MemoryToolError
from isekai_memory.store.database import close_pool, get_pool, health_check, init_pool
from tests.test_project_directory import metadata

pytestmark = pytest.mark.skipif(not os.environ.get("MEMORY_TEST_DATABASE_URL"), reason="requires disposable PostgreSQL")


@pytest_asyncio.fixture
async def directory():
    settings = Settings(database_url=os.environ["MEMORY_TEST_DATABASE_URL"], db_pool_min=1, db_pool_max=3)
    await init_pool(settings)
    try:
        assert (await health_check())["schema_revision"] == "015"
        yield ToolDispatcher(settings), "directory-" + uuid4().hex
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_owner_assignment_revocation_and_revision_guards(directory):
    dispatch, project = directory
    owner = Principal("alice-" + project, "directory", frozenset({"read", "write", "projects"}))
    bob = Principal("bob-" + project, "directory", frozenset({"read", "write", "projects"}))
    scoped = Principal(owner.user_id, project + "-other", frozenset({"admin"}))
    row = await dispatch("memory_project_register", metadata(project), owner)
    assert row["revision"] == 1
    assert (await dispatch("memory_project_register", metadata(project), owner))["revision"] == 1
    assert (await dispatch("memory_project_list", {}, bob))["items"] == []
    with pytest.raises(MemoryToolError):
        await dispatch("memory_project_get", {"project_id": project}, bob)
    with pytest.raises(MemoryToolError):
        await dispatch("memory_project_get", {"project_id": project}, scoped)
    assignment = {"project_id": project, "user_id": bob.user_id, "role": "read", "expected_revision": 1}
    assert (await dispatch("memory_project_assign", assignment, owner))["revision"] == 2
    assert (await dispatch("memory_project_assign", assignment, owner))["changed"] is False
    assert (await dispatch("memory_project_list", {}, bob))["items"][0]["role"] == "read"
    assert (await dispatch("memory_project_get", {"project_id": project}, bob))["setup"]["digest"] == row["setup"][
        "digest"
    ]
    with pytest.raises(MemoryToolError):
        await dispatch("memory_project_register", {**metadata(project), "name": "hijack", "expected_revision": 2}, bob)
    with pytest.raises(MemoryToolError):
        await dispatch("memory_project_register", {**metadata(project), "name": "stale", "expected_revision": 1}, owner)
    with pytest.raises(MemoryToolError):
        await dispatch("memory_project_assign", {**assignment, "role": "remove", "expected_revision": 1}, owner)
    await dispatch("memory_project_assign", {**assignment, "role": "remove", "expected_revision": 2}, owner)
    assert (await dispatch("memory_project_list", {}, bob))["items"] == []
    with pytest.raises(MemoryToolError):
        await dispatch("memory_project_get", {"project_id": project}, bob)


@pytest.mark.asyncio
async def test_project_token_listing_cannot_discover_other_projects_of_same_actor(directory):
    dispatch, project = directory
    owner = Principal(project, "directory", frozenset({"read", "write", "projects"}))
    for suffix in ("-a", "-b"):
        await dispatch("memory_project_register", metadata(project + suffix), owner)
    scoped = Principal(project, project + "-a", frozenset({"read"}))
    result = await dispatch("memory_project_list", {}, scoped)
    assert [item["project_id"] for item in result["items"]] == [project + "-a"]
    first = await dispatch("memory_project_list", {"limit": 1}, owner)
    assert first["next_cursor"] == project + "-a"
    second = await dispatch("memory_project_list", {"limit": 1, "after": first["next_cursor"]}, owner)
    assert second["items"][0]["project_id"] == project + "-b"


@pytest.mark.asyncio
async def test_global_registration_cannot_claim_preexisting_memory_namespace(directory):
    dispatch, project = directory
    async with get_pool().acquire() as conn:
        await conn.execute(
            "INSERT INTO memory_usage_policies(project_id,version,policy,updated_by) VALUES($1,1,'{}','original-admin')",
            project,
        )
    outsider = Principal("new-user", "directory", frozenset({"admin", "projects"}))
    with pytest.raises(MemoryToolError) as caught:
        await dispatch("memory_project_register", metadata(project), outsider)
    assert caught.value.data["error_code"] == "MEM-PROJECT-LEGACY"
    scoped_admin = Principal("original-admin", project, frozenset({"admin"}))
    registered = await dispatch("memory_project_register", metadata(project), scoped_admin)
    assert registered["owner_id"] == scoped_admin.user_id
    assert (await dispatch("memory_project_list", {}, outsider))["items"] == []
