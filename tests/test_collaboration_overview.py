"""M9 read-model schemas and privilege boundaries without a database."""

from contextlib import asynccontextmanager

import pytest
from jsonschema import Draft202012Validator

from isekai_memory.continuity import overview
from isekai_memory.continuity.tools import CONTINUITY_TOOLS
from isekai_memory.server.auth import Principal, authorize_tool
from isekai_memory.server.errors import MemoryToolError
from isekai_memory.server.validation import validate_tool_arguments


@pytest.mark.parametrize("name", ["memory_collaboration_overview", "memory_collaboration_list"])
def test_read_tools_are_strict_and_project_authorized(name):
    tool = next(tool for tool in CONTINUITY_TOOLS if tool["name"] == name)
    Draft202012Validator.check_schema(tool["inputSchema"])
    args = {"project_id": "p", **({"view": "work"} if name.endswith("list") else {})}
    validate_tool_arguments(name, args)
    authorize_tool(Principal("a", "p", frozenset({"read"})), name, args)
    for principal in (Principal("a", "q", frozenset({"admin"})), Principal("a", "p", frozenset({"write"}))):
        with pytest.raises(MemoryToolError):
            authorize_tool(principal, name, args)


@pytest.mark.parametrize("extra", [
    {"actor_id": "someone"}, {"scope": "global"}, {"max_classification": "secret"},
    {"include_inactive": 1}, {"include_acknowledged": "yes"}, {"from_user_id": "someone"},
    {"limit": True}, {"limit": 0}, {"limit": 51}, {"cursor": ""}, {"view": "sessions"},
])
def test_invalid_listing_options(extra):
    with pytest.raises(MemoryToolError):
        validate_tool_arguments("memory_collaboration_list", {"project_id": "p", "view": "work", **extra})


@pytest.mark.parametrize("method", ["overview", "listing"])
async def test_project_scope_denied_before_any_database_access(monkeypatch, method):
    monkeypatch.setattr(overview, "get_pool", lambda: pytest.fail("must authorize first"))
    args = {"project_id": "p", "scope": "project", "view": "work"}
    with pytest.raises(MemoryToolError) as error:
        await getattr(overview, method)(args, principal=Principal("a", "p", frozenset({"read"})))
    assert error.value.http_status == 403


async def test_query_timeout_is_not_a_zero_count(monkeypatch):
    @asynccontextmanager
    async def unavailable():
        raise TimeoutError()
        yield  # pragma: no cover

    class Pool:
        acquire = staticmethod(unavailable)

    monkeypatch.setattr(overview, "get_pool", lambda: Pool())
    with pytest.raises(MemoryToolError) as error:
        async with overview.read_transaction():
            pytest.fail("timed out")
    assert error.value.http_status == 503
    assert error.value.data["error_code"] == "MEM-COLLABORATION-0002"
