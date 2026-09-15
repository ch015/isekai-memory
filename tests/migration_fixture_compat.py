"""Pre-013 migration fixture adapter only. Production mutation paths always require the current schema."""
from unittest.mock import AsyncMock, patch


def pre_event_fixture():
    # Historical fixtures emulate the old application's lack of an event projection.
    # Never use this adapter in runtime code or tests asserting current-schema feed behavior.
    return patch("isekai_memory.continuity.events.project_event", new=AsyncMock())
