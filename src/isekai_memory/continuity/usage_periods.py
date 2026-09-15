"""Timezone-aware half-open periods and pinned run attribution; no I/O."""
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def timezone(value):
    try:
        return ZoneInfo(value)
    except (ValueError, TypeError, ZoneInfoNotFoundError) as exc:
        raise ValueError("Unknown IANA timezone") from exc


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("A timezone is required")
    return parsed.astimezone(UTC)


def period(arguments, now, default_timezone):
    name = arguments.get("timezone", default_timezone)
    zone = timezone(name)
    kind = arguments.get("period", "today")
    if kind == "custom":
        start, end = timestamp(arguments["start_at"]), timestamp(arguments["end_at"])
    else:
        if "start_at" in arguments or "end_at" in arguments:
            raise ValueError("Explicit bounds require custom period")
        date = now.astimezone(zone).date()
        if kind == "week":
            date -= timedelta(days=date.weekday())
        elif kind != "today":
            raise ValueError("Unknown period")
        start, end = datetime.combine(date, time.min, tzinfo=zone).astimezone(UTC), now
    if not start < end or end - start > timedelta(days=93):
        raise ValueError("Usage periods must be positive and bounded to 93 days")
    return {"kind": kind, "timezone": name, "start_at": start, "end_at": end,
            "interval": "half_open", "bucket_semantics": "exclusive_run_end_not_time_prorated"}


def source_time(value, now, hours, fallback):
    if value is not None:
        candidate = timestamp(value)
        if now - timedelta(hours=hours) <= candidate <= now + timedelta(minutes=5):
            return candidate, "source_reported"
    return fallback, "server_first_received"
