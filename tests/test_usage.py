"""Strict usage DTOs, timezone semantics, and no caller-selected identity."""
from datetime import UTC, datetime, timedelta

import pytest
from jsonschema import Draft202012Validator

from isekai_memory.continuity.usage_metrics import Counter, normalize
from isekai_memory.continuity.usage_periods import period, source_time
from isekai_memory.continuity.usage_tools import USAGE_SCOPES, USAGE_TOOLS
from isekai_memory.server.auth import Principal, authorize_tool
from isekai_memory.server.errors import MemoryToolError
from isekai_memory.server.validation import validate_tool_arguments

UUID = "00000000-0000-4000-8000-000000000001"


def metric(total=100, quality="reported"):
    return normalize({"total_tokens": Counter(total, quality, "provider_estimate" if quality == "estimated" else None)}).as_dict()


def report_request(**overrides):
    return {"project_id": "p", "session_id": UUID, "session_token": "a"*32, "sequence": 1,
            "metrics": metric(), "semantics_version": 1, "completion_state": "final", "coverage": "complete",
            "source_occurred_at": None, **overrides}


@pytest.mark.parametrize("tool", USAGE_TOOLS, ids=lambda tool: tool["name"])
def test_strict_catalog_scope(tool):
    Draft202012Validator.check_schema(tool["inputSchema"])
    assert not tool["inputSchema"]["additionalProperties"]
    assert "project_id" in tool["inputSchema"]["required"]
    with pytest.raises(MemoryToolError):
        authorize_tool(Principal("a", "other", frozenset({"admin"})), tool["name"], {"project_id": "p"})
    if USAGE_SCOPES[tool["name"]] != "read":
        with pytest.raises(MemoryToolError):
            authorize_tool(Principal("a", "p", frozenset({"read"})), tool["name"], {"project_id": "p"})


@pytest.mark.parametrize("override", [
    {"actor_id": "other"}, {"sequence": True}, {"sequence": 0}, {"raw_event": "secret"},
    {"source_occurred_at": "2026-01-01"}, {"session_token": "short"}, {"semantics_version": 2},
    {"metrics": {"total_tokens": 1}}, {"metrics": {**metric(), "input_tokens": 30}},
    {"metrics": {**metric(), "total_tokens": {**metric()["total_tokens"], "value": True}}},
    {"metrics": {**metric(), "total_tokens": {**metric()["total_tokens"], "value": -1}}},
    {"metrics": {**metric(), "total_tokens": {**metric()["total_tokens"], "value": 10**12+1}}},
])
def test_report_rejects_untrusted_fields(override):
    with pytest.raises(MemoryToolError):
        validate_tool_arguments("memory_usage_report", report_request(**override))


@pytest.mark.parametrize(("now", "start", "hours"), [
    ("2026-03-09T03:59:00+00:00", "2026-03-08T05:00:00+00:00", 23),
    ("2026-11-02T04:59:00+00:00", "2026-11-01T04:00:00+00:00", 25),
])
def test_today_dst_is_calendar_midnight_not_fixed_24h(now, start, hours):
    instant = datetime.fromisoformat(now)
    value = period({}, instant, "America/New_York")
    assert value["start_at"] == datetime.fromisoformat(start)
    assert value["end_at"] == instant
    assert (instant-value["start_at"]).total_seconds() == hours*3600-60


def test_week_custom_bounds_and_iana_validation():
    now = datetime(2026, 9, 14, 3, tzinfo=UTC)
    assert period({"period": "week"}, now, "Asia/Seoul")["start_at"] == datetime(2026, 9, 13, 15, tzinfo=UTC)
    for args in ({"timezone": "No/Such"}, {"start_at": "2026-01-01T00:00:00Z"},
                 {"period": "custom", "start_at": "2026-01-01T00:00:00Z", "end_at": "2026-07-01T00:00:00Z"},
                 {"period": "custom", "start_at": "2026-01-01T00:00:00Z", "end_at": "2026-01-01T00:00:00Z"}):
        with pytest.raises(ValueError):
            period(args, now, "UTC")


def test_source_attribution_fallback_and_late_window():
    now = datetime(2026, 9, 14, 3, tzinfo=UTC)
    assert source_time((now-timedelta(hours=2)).isoformat(), now, 3, now)[1] == "source_reported"
    for source in (None, (now-timedelta(hours=4)).isoformat(), (now+timedelta(hours=1)).isoformat()):
        assert source_time(source, now, 3, now) == (now, "server_first_received")
