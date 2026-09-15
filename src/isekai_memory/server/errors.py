"""Shared application and protocol errors."""

from __future__ import annotations

from typing import Any


class MemoryToolError(Exception):
    """Controlled error that can cross REST and MCP transport boundaries."""

    def __init__(
        self,
        message: str,
        *,
        code: int = -32000,
        data: dict[str, Any] | None = None,
        http_status: int = 400,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.data = data or {}
        self.http_status = http_status
