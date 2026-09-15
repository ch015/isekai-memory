"""Deterministic presence/idle boundaries, with no clock sleeps or user monitoring."""

from datetime import UTC, datetime, timedelta

import pytest

from isekai_memory.continuity.presence_state import PresencePolicy, aggregate_states, next_times, session_state

NOW = datetime(2026, 9, 11, 12, tzinfo=UTC)
POLICY = PresencePolicy()


def observation(state="idle", seconds=600, **overrides):
    return {"reported_state": state, "observation_scope": "controller", "state_observation_available": True,
            "active_work_count": 1 if state == "running" else 0,
            "last_seen_at": NOW - timedelta(seconds=3), "state_since_at": NOW - timedelta(seconds=seconds),
            "idle_since_at": NOW - timedelta(seconds=seconds) if state == "idle" else None, "ended_at": None,
            **overrides}


def derive(**options):
    return session_state(observation(**options), NOW, POLICY)


@pytest.mark.parametrize("seconds,expected", [(299, "waiting"), (300, "idle"), (1800, "idle")])
def test_idle_threshold(seconds, expected):
    result = derive(seconds=seconds)
    assert result["effective_state"] == expected and result["idle_seconds"] == seconds


@pytest.mark.parametrize("state", ["running", "waiting_approval", "blocked"])
def test_long_silent_work_and_approval_are_not_idle(state):
    result = derive(state=state, seconds=1800)
    assert result["effective_state"] == state and not result["is_idle"] and result["idle_seconds"] is None


@pytest.mark.parametrize("delay,status", [(59, "idle"), (60, "stale"), (300, "stale")])
def test_report_freshness_is_independent_of_reported_idle(delay, status):
    result = derive(last_seen_at=NOW - timedelta(seconds=delay))
    assert result["effective_state"] == status
    if status == "stale":
        assert result["idle_seconds"] is None and not result["is_idle"]


@pytest.mark.parametrize("overrides", [
    {"state_observation_available": False}, {"observation_scope": "partial"},
    {"reported_state": "unknown"}, {"active_work_count": 1}, {"active_work_count": True},
    {"active_work_count": -1}, {"active_work_count": 129}, {"idle_since_at": None},
    {"last_seen_at": NOW + timedelta(seconds=1)}, {"state_since_at": NOW + timedelta(seconds=1)},
    {"idle_since_at": NOW + timedelta(seconds=1)}, {"state_since_at": None},
])
def test_incomplete_inconsistent_or_future_observations_are_not_idle(overrides):
    result = derive(**overrides)
    assert result["effective_state"] == "unknown" and result["idle_seconds"] is None


def test_ended_wins_over_old_report_but_does_not_mean_human_offline():
    result = derive(ended_at=NOW - timedelta(seconds=2), last_seen_at=NOW - timedelta(hours=1))
    assert result["freshness"] == "ended" and result["effective_state"] == "ended"
    assert aggregate_states([result])["effective_state"] == "ended"
    assert aggregate_states([])["effective_state"] == "not_observed"


@pytest.mark.parametrize("durations,status,minimum", [([1800, 120], "waiting", 120), ([720, 480], "idle", 480)])
def test_user_idle_is_minimum_of_all_observed_open_sessions(durations, status, minimum):
    result = aggregate_states([derive(seconds=seconds) for seconds in durations])
    assert result["effective_state"] == status and result["idle_seconds"] == minimum


@pytest.mark.parametrize("other", [
    {"last_seen_at": NOW - timedelta(seconds=60)}, {"state_observation_available": False},
    {"observation_scope": "partial"},
])
def test_one_uncertain_session_prevents_all_idle(other):
    result = aggregate_states([derive(), derive(**other)])
    assert result["effective_state"] == "partially_unknown" and result["has_uncertainty"]


def test_running_with_stale_retains_both_signals():
    result = aggregate_states([derive(state="running"), derive(last_seen_at=NOW - timedelta(minutes=2))])
    assert result["effective_state"] == "running" and result["has_uncertainty"]
    assert result["counts"] == {"running": 1, "stale": 1}


@pytest.mark.parametrize("state", ["running", "waiting_approval", "blocked"])
def test_known_execution_priority_over_idle_and_partial(state):
    result = aggregate_states([derive(state=state), derive()], complete=False)
    assert result["effective_state"] == state and result["has_uncertainty"]


def test_partial_page_never_declares_all_user_sessions_idle():
    result = aggregate_states([derive()], complete=False)
    assert result["effective_state"] == "partially_unknown" and result["idle_seconds"] is None
    assert aggregate_states([], complete=False)["effective_state"] == "partially_unknown"


def test_repeated_heartbeats_preserve_idle_and_policy_change_does_not_reset():
    row = observation()
    times = next_times(row, "idle", NOW, POLICY, state_changed=False)
    assert times["idle_since_at"] == row["idle_since_at"]
    for step in range(10):
        current = NOW + timedelta(seconds=15 * step)
        times = next_times(row, "idle", current, POLICY, state_changed=False)
        row = {**row, **times, "last_seen_at": current}
    assert row["idle_since_at"] == observation()["idle_since_at"]
    changed = PresencePolicy(idle_after_seconds=1200)
    result = session_state(row, current, changed)
    assert result["effective_state"] == "waiting"
    assert result["idle_seconds"] == 600 + 15 * 9


@pytest.mark.parametrize("last_seen", [NOW - timedelta(seconds=60), NOW + timedelta(seconds=1)])
def test_reconnect_and_clock_reversal_start_a_new_continuous_interval(last_seen):
    row = observation(last_seen_at=last_seen)
    times = next_times(row, "idle", NOW, POLICY, state_changed=False)
    assert times == {"state_since_at": NOW, "idle_since_at": NOW}
    result = session_state({**row, **times, "last_seen_at": NOW}, NOW, POLICY)
    assert result["effective_state"] == "waiting" and result["idle_seconds"] == 0


def test_running_transition_clears_idle_then_starts_new_interval():
    times = next_times(observation(), "running", NOW, POLICY, state_changed=True)
    assert times["idle_since_at"] is None
    row = {**observation("running"), **times, "last_seen_at": NOW}
    later = NOW + timedelta(seconds=10)
    assert next_times(row, "idle", later, POLICY, state_changed=True)["idle_since_at"] == later


@pytest.mark.parametrize("options", [
    {"heartbeat_seconds": True}, {"heartbeat_seconds": 9}, {"heartbeat_seconds": 61},
    {"stale_after_seconds": 44}, {"stale_after_seconds": 301}, {"stale_after_seconds": 45, "heartbeat_seconds": 20},
    {"idle_after_seconds": 59}, {"idle_after_seconds": 3601},
])
def test_policy_limits_and_relationship(options):
    with pytest.raises(ValueError):
        PresencePolicy(**options)


def test_naive_clock_and_oversized_aggregate_rejected():
    with pytest.raises(ValueError):
        session_state(observation(), NOW.replace(tzinfo=None), POLICY)
    with pytest.raises(ValueError):
        aggregate_states([derive()] * 10001)
