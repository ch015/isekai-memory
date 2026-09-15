"""Pure observed-work presence/idle decisions. Never infers human absence."""

from collections import Counter
from dataclasses import dataclass
from datetime import datetime

REPORTED_STATES = frozenset({"running", "waiting_approval", "blocked", "idle", "unknown"})


@dataclass(frozen=True)
class PresencePolicy:
    heartbeat_seconds: int = 15
    stale_after_seconds: int = 60
    idle_after_seconds: int = 300

    def __post_init__(self):
        bounds = ((self.heartbeat_seconds, 10, 60), (self.stale_after_seconds, 45, 300),
                  (self.idle_after_seconds, 60, 3600))
        if any(type(value) is not int or not low <= value <= high for value, low, high in bounds):
            raise ValueError("Presence policy limits are invalid")
        if self.stale_after_seconds < self.heartbeat_seconds * 3:
            raise ValueError("Stale threshold must cover at least three heartbeat intervals")


def _aware(value):
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def next_times(previous, reported_state, now, policy, *, state_changed):
    """Called only after actor/sequence/report validation by the persistence service."""
    if not _aware(now) or reported_state not in REPORTED_STATES:
        raise ValueError("Invalid presence transition")
    last_seen = previous.get("last_seen_at") if previous else None
    discontinuity = (not _aware(last_seen) or now < last_seen
                     or (now - last_seen).total_seconds() >= policy.stale_after_seconds)
    changed = (previous is None or state_changed or discontinuity
               or previous.get("reported_state") != reported_state)
    state_since = now if changed else previous["state_since_at"]
    idle_since = (now if changed else previous.get("idle_since_at")) if reported_state == "idle" else None
    return {"state_since_at": state_since, "idle_since_at": idle_since}


def session_state(row, now, policy):
    """Return a decision only; this function cannot refresh timestamps or a lease."""
    if not _aware(now):
        raise ValueError("Observation time must be timezone-aware")
    reported = row.get("reported_state", "unknown")
    result = {
        "reported_state": reported if reported in REPORTED_STATES else "unknown",
        "freshness": "unknown", "effective_state": "unknown", "reason": "not_observed",
        "state_seconds": None, "idle_seconds": None, "is_idle": False,
    }
    if row.get("ended_at") is not None:
        return {**result, "freshness": "ended", "effective_state": "ended", "reason": "session_ended"}
    last_seen = row.get("last_seen_at")
    state_since = row.get("state_since_at")
    if not _aware(last_seen):
        return result
    if now < last_seen or (_aware(state_since) and now < state_since):
        return {**result, "reason": "clock_discontinuity"}
    if (now - last_seen).total_seconds() >= policy.stale_after_seconds:
        return {**result, "freshness": "stale", "effective_state": "stale", "reason": "report_delayed"}
    result["freshness"] = "fresh"
    available = row.get("state_observation_available") is True
    scope = row.get("observation_scope")
    active = row.get("active_work_count")
    if (not available or scope not in {"worker", "controller"} or reported not in REPORTED_STATES
            or not _aware(state_since) or type(active) is not int or not 0 <= active <= 128):
        return {**result, "reason": "observation_incomplete"}
    if reported == "unknown":
        return {**result, "reason": "state_unknown"}
    if (reported == "running" and active == 0) or (reported == "idle" and active != 0):
        return {**result, "reason": "inconsistent_report"}
    result["state_seconds"] = int((now - state_since).total_seconds())
    if reported != "idle":
        return {**result, "effective_state": reported, "reason": "reported_state"}
    since = row.get("idle_since_at")
    if not _aware(since) or since < state_since or since > last_seen or since > now:
        return {**result, "reason": "idle_interval_unknown"}
    seconds = int((now - since).total_seconds())
    idle = seconds >= policy.idle_after_seconds
    return {**result, "effective_state": "idle" if idle else "waiting",
            "reason": "idle_threshold_reached" if idle else "idle_threshold_pending",
            "idle_seconds": seconds, "is_idle": idle}


def aggregate_states(states, *, complete=True):
    """Aggregate ONLY the authorized project/user scope supplied by the caller."""
    if type(complete) is not bool or len(states) > 10000:
        raise ValueError("Presence aggregate is invalid or exceeds its bound")
    counts = dict(Counter(item["effective_state"] for item in states))
    opened = [item for item in states if item["freshness"] != "ended"]
    result = {"effective_state": "unknown", "idle_seconds": None, "is_idle": False,
              "coverage": "complete" if complete else "partial",
              "observed_sessions": len(states), "open_sessions": len(opened),
              "counts": counts, "has_uncertainty": not complete or any(
                  item["freshness"] in {"stale", "unknown"} or item["effective_state"] == "unknown" for item in opened)}
    # A known running session remains positive evidence, even if other sessions are uncertain.
    for status in ("running", "waiting_approval", "blocked"):
        if any(item["freshness"] == "fresh" and item["effective_state"] == status for item in opened):
            return {**result, "effective_state": status}
    if result["has_uncertainty"]:
        return {**result, "effective_state": "partially_unknown"}
    if not opened:
        return {**result, "effective_state": "ended" if states else "not_observed"}
    if all(item["freshness"] == "fresh" and item["effective_state"] in {"idle", "waiting"} for item in opened):
        seconds = min(item["idle_seconds"] for item in opened)
        idle = all(item["is_idle"] for item in opened)
        return {**result, "effective_state": "idle" if idle else "waiting", "idle_seconds": seconds, "is_idle": idle}
    return {**result, "effective_state": "partially_unknown", "has_uncertainty": True}
