"""Real member isolation, actor binding, idempotency, retrieval and erasure."""
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from isekai_memory.server.auth import Principal
from isekai_memory.server.errors import MemoryToolError
from tests.test_project_directory import metadata
from tests.test_project_directory_postgres import directory  # noqa: F401

pytestmark = pytest.mark.skipif(not os.environ.get("MEMORY_TEST_DATABASE_URL"), reason="requires disposable PostgreSQL")


@pytest.mark.asyncio
async def test_shared_records_authorization_search_retry_and_erasure(directory):  # noqa: F811 - shared pytest fixture
    dispatch, project = directory
    owner = Principal("owner-" + project, "directory", frozenset({"read", "write", "projects"}))
    reader = Principal("reader-" + project, "directory", frozenset({"read", "write", "projects"}))
    stranger = Principal("stranger-" + project, "directory", frozenset({"admin", "projects"}))
    await dispatch("memory_project_register", {**metadata(project), "source_kind": "git"}, owner)
    await dispatch("memory_project_assign", {"project_id": project, "user_id": reader.user_id, "role": "read", "expected_revision": 1}, owner)
    args = {"project_id": project, "expected_actor": owner.user_id, "record_id": str(uuid4()), "kind": "material",
            "title": "보안 검토 결과", "body": "프로젝트별 공유 자료와 작업 이력", "refs": [{"label": "보고서", "uri": "docs/report.md"}],
            "occurred_at": datetime.now(UTC).isoformat()}
    saved = await dispatch("memory_project_record_put", args, owner)
    with pytest.raises(MemoryToolError):
        await dispatch("memory_project_record_put", {**args, "record_id": str(uuid4()), "body": "가" * 8192,
            "refs": [{"label": "자료", "uri": "docs/" + "나" * 2000} for _ in range(20)]}, owner)
    assert (await dispatch("memory_project_record_put", args, owner))["already_applied"]
    with pytest.raises(MemoryToolError):
        await dispatch("memory_project_record_put", {**args, "body": "changed"}, owner)
    with pytest.raises(MemoryToolError):
        await dispatch("memory_project_record_put", {**args, "expected_actor": "changed-user"}, owner)
    for actor in (reader, stranger):
        with pytest.raises(MemoryToolError):
            await dispatch("memory_project_record_put", {**args, "expected_actor": actor.user_id}, actor)
    page = await dispatch("memory_project_record_list", {"project_id": project, "query": "공유"}, reader)
    assert len(page["items"]) == 1
    assert not page["can_share"] and not page["can_remove_any"]
    own_page = await dispatch("memory_project_record_list", {"project_id": project}, owner)
    assert own_page["can_share"] and own_page["can_remove_any"]
    assert page["items"][0]["actor_id"] == owner.user_id
    assert page["items"][0]["citation"] == "memory-project:" + saved["record_id"]
    assert not (await dispatch("memory_project_record_list", {"project_id": project, "query": "%"}, reader))["items"]
    with pytest.raises(MemoryToolError):
        await dispatch("memory_project_record_list", {"project_id": project}, stranger)
    await dispatch("memory_project_record_remove", {"project_id": project, "expected_actor": owner.user_id, "record_id": args["record_id"]}, owner)
    assert not (await dispatch("memory_project_record_list", {"project_id": project}, reader))["items"]
    assert (await dispatch("memory_project_record_put", args, owner))["removed"]
    await dispatch("memory_project_assign", {"project_id": project, "user_id": reader.user_id, "role": "remove", "expected_revision": 2}, owner)
    with pytest.raises(MemoryToolError):
        await dispatch("memory_project_record_list", {"project_id": project}, reader)


@pytest.mark.asyncio
async def test_pagination_and_explicit_source_kinds(directory):  # noqa: F811 - shared pytest fixture
    dispatch, project = directory
    owner = Principal(project, "directory", frozenset({"read", "write", "projects"}))
    args = {**metadata(project), "git_url": None, "git_ref": None, "source_kind": "directory"}
    row = await dispatch("memory_project_register", args, owner)
    assert row["source_kind"] == "directory"
    assert (await dispatch("memory_project_list", {}, owner))["items"][0]["source_kind"] == "directory"
    for n in range(3):
        await dispatch("memory_project_record_put", {"project_id": project, "expected_actor": owner.user_id,
            "record_id": str(uuid4()), "kind": "activity", "title": f"상태 {n}", "body": "", "refs": [],
            "occurred_at": datetime.now(UTC).isoformat()}, owner)
    first = await dispatch("memory_project_record_list", {"project_id": project, "limit": 2}, owner)
    second = await dispatch("memory_project_record_list", {"project_id": project, "before": first["next_cursor"], "limit": 2}, owner)
    assert len(first["items"]) == 2 and len(second["items"]) == 1 and second["next_cursor"] is None
    assert not {i["record_id"] for i in first["items"]} & {i["record_id"] for i in second["items"]}
