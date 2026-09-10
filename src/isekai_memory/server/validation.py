"""Runtime enforcement of advertised MCP tool input schemas."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from isekai_memory.server.errors import MemoryToolError
from isekai_memory.server.tools import TOOL_MAP

_FORMAT_CHECKER = FormatChecker()


@_FORMAT_CHECKER.checks("date-time", raises=(ValueError, OverflowError))
def _is_date_time(value: Any) -> bool:
    """Validate timezone-bearing timestamps without jsonschema's optional extras."""
    if not isinstance(value, str):
        return True  # The schema's type check handles non-strings.
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-](?:[01]\d|2[0-3]):[0-5]\d)", value):
        return False
    # The standard library checks calendar dates; RFC3339 leap seconds are not
    # accepted because PostgreSQL/Python expiry comparisons cannot preserve them.
    return datetime.fromisoformat(value.upper().replace("Z", "+00:00")).astimezone(UTC).utcoffset() is not None


_VALIDATORS = {
    name: Draft202012Validator(tool["inputSchema"], format_checker=_FORMAT_CHECKER)
    for name, tool in TOOL_MAP.items()
}


def validate_tool_arguments(tool_name: str, arguments: dict[str, Any]) -> None:
    validator = _VALIDATORS.get(tool_name)
    if validator is None:
        raise MemoryToolError(
            f"Unknown tool: {tool_name}",
            code=-32602,
            data={"error_code": "MEM-TOOL-0001"},
            http_status=404,
        )
    errors = sorted(validator.iter_errors(arguments), key=lambda error: list(error.absolute_path))
    if not errors:
        return
    details = []
    for error in errors[:20]:
        path_items = [str(item) for item in error.absolute_path]
        details.append(
            {
                "path": "/" + "/".join(path_items),
                "message": (
                    "claim token failed validation" if "claim_token" in path_items else
                    "archive failed validation" if "archive_base64" in path_items else error.message
                ),
            }
        )
    raise MemoryToolError(
        "Tool arguments failed schema validation",
        code=-32602,
        data={"error_code": "MEM-TOOL-0002", "validation": details},
        http_status=400,
    )
