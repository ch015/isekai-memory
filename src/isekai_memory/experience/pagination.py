"""Bounded, scope-bound keyset positions; cursors never grant authorization."""

from __future__ import annotations

import base64
import binascii
import json
from datetime import UTC, datetime
from uuid import UUID

from isekai_memory.experience.persistence import error


def encode(row: dict, scope: list[str]) -> str:
    payload = {"v": 1, "scope": scope, "at": row["created_at"].isoformat(), "id": str(row["id"])}
    return base64.urlsafe_b64encode(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()).decode().rstrip("=")


def decode(cursor: str | None, scope: list[str]) -> tuple[datetime | None, UUID | None]:
    if cursor is None:
        return None, None
    try:
        if not isinstance(cursor, str) or not 1 <= len(cursor) <= 2048:
            raise ValueError("cursor length")
        payload = json.loads(base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True))
        if (
            not isinstance(payload, dict)
            or set(payload) != {"v", "scope", "at", "id"}
            or type(payload["v"]) is not int
            or payload["v"] != 1
            or payload["scope"] != scope
        ):
            raise ValueError("cursor scope or version")
        at = datetime.fromisoformat(payload["at"])
        if at.tzinfo is None:
            raise ValueError("cursor timezone")
        return at.astimezone(UTC), UUID(payload["id"])
    except (ValueError, TypeError, AttributeError, OverflowError, RecursionError, binascii.Error) as exc:
        raise error("Invalid cursor for this project and view", "MEM-EXPERIENCE-0010", 400) from exc


def page(rows: list[dict], limit: int, scope: list[str], offset: int | None = None) -> dict:
    more = len(rows) > limit
    result = {"items": rows[:limit], "has_more": more, "next_cursor": encode(rows[limit - 1], scope) if more else None}
    if offset is not None:
        result["next_offset"] = offset + limit if more and offset + limit <= 10000 else None
    return result
