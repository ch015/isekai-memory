"""Encrypted cursors are fixed-size, authenticated and bound to the reader's scope."""
import base64
import secrets
import struct
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.fernet import Fernet

from isekai_memory.continuity.events import RETENTION_SECONDS, binding, decode_cursor, encode_cursor
from isekai_memory.server.auth import Principal
from isekai_memory.server.errors import MemoryToolError


def test_cursor_hides_sequence_and_has_randomized_fixed_length():
    key, scope = secrets.token_bytes(32), secrets.token_bytes(32)
    first, second = encode_cursor(key, scope, 1), encode_cursor(key, scope, 10**18)
    assert len(first) == len(second) and first != encode_cursor(key, scope, 1)
    now = datetime.now(UTC)
    assert decode_cursor(key, scope, first, now) == (1, None)
    assert decode_cursor(key, scope, second, now) == (10**18, None)
    assert b"position" not in base64.urlsafe_b64decode(first)


def test_old_changed_key_corrupt_and_wrong_binding_cursors_never_return_positions():
    key, scope = secrets.token_bytes(32), secrets.token_bytes(32)
    now = datetime.now(UTC)
    old = Fernet(base64.urlsafe_b64encode(key)).encrypt_at_time(struct.pack(">B32sQ", 1, scope, 999),
                                                              int((now - timedelta(days=8)).timestamp())).decode()
    assert decode_cursor(key, scope, old, now) == (None, "cursor_expired")
    fresh = encode_cursor(key, scope, 999)
    assert decode_cursor(secrets.token_bytes(32), scope, fresh, now) == (None, "cursor_unusable")
    assert decode_cursor(key, scope, fresh[:-3] + "BAD", now) == (None, "cursor_unusable")
    with pytest.raises(MemoryToolError):
        decode_cursor(key, secrets.token_bytes(32), fresh, now)


def test_scope_binds_project_actor_permissions_and_classification_not_list_filters():
    args = {"project_id": "p", "scope": "mine", "max_classification": "internal"}
    principal = Principal("a", "p", frozenset({"read", "write"}))
    original = binding(args, principal)
    for current, actor in ((args | {"project_id": "q"}, principal), (args | {"scope": "project"}, principal),
                           (args | {"max_classification": "restricted"}, principal),
                           (args, Principal("b", "p", principal.scopes)), (args, Principal("a", "p", frozenset({"read"})))):
        assert binding(current, actor) != original
    assert binding(args | {"include_inactive": True, "limit": 1}, principal) == original
    assert RETENTION_SECONDS == 604800
