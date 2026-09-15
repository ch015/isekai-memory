"""Presence transport schema validation before any observation is stored."""

import pytest
from jsonschema import Draft202012Validator

from isekai_memory.continuity.presence_tools import PRESENCE_SCOPES, PRESENCE_TOOLS
from isekai_memory.server.auth import Principal, authorize_tool
from isekai_memory.server.errors import MemoryToolError
from isekai_memory.server.validation import validate_tool_arguments

UUID = "00000000-0000-4000-8000-000000000001"


@pytest.mark.parametrize("tool", PRESENCE_TOOLS, ids=lambda tool: tool["name"])
def test_presence_catalog_strict_project_scope(tool):
    Draft202012Validator.check_schema(tool["inputSchema"])
    assert tool["inputSchema"]["additionalProperties"] is False
    assert "project_id" in tool["inputSchema"]["required"]
    with pytest.raises(MemoryToolError):
        authorize_tool(Principal("a", "foreign", frozenset({"admin"})), tool["name"], {"project_id": "p"})
    if PRESENCE_SCOPES[tool["name"]] != "read":
        with pytest.raises(MemoryToolError):
            authorize_tool(Principal("a", "p", frozenset({"read"})), tool["name"], {"project_id": "p"})


@pytest.mark.parametrize("overrides", [
    {"sequence": True}, {"sequence": 0}, {"state_sequence": -1}, {"sequence": 2147483647},
    {"active_work_count": True}, {"active_work_count": 129}, {"session_token": "short"},
    {"actor_id": "someone"}, {"last_seen_at": "2026-09-11T00:00:00Z"}, {"host_path": "/private"},
    {"observation_scope": "whole_computer"}, {"reported_state": "human_away"}, {"session_id": "invalid"},
])
def test_report_rejects_spoofed_identity_time_and_invalid_values(overrides):
    args = {"project_id": "p", "session_id": UUID, "session_token": "a"*32, "sequence": 1, "state_sequence": 1,
            "reported_state": "idle", "observation_scope": "controller", "state_observation_available": True,
            "active_work_count": 0, "policy_version": 1, "classification": "internal",
            "work_unit_id": None, "checkpoint_id": None, **overrides}
    with pytest.raises(MemoryToolError):
        validate_tool_arguments("memory_presence_heartbeat", args)
