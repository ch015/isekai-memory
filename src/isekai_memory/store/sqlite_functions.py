"""Small SQLite scalar functions and lossless codecs used by repository SQL."""
import hashlib
import json
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4


def timestamp(value=None):
    return (value or datetime.now(UTC)).astimezone(UTC).isoformat(timespec='microseconds')


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def encode(value):
    if isinstance(value, datetime):
        return timestamp(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (dict, list, tuple)):
        return canonical([str(v) if isinstance(v, UUID) else v for v in value] if not isinstance(value, dict) else value)
    return value


def terms(value):
    return re.findall(r'\w+', (value or '').casefold())


def lexical_match(document, query):
    query_terms = terms(query)
    words = set(terms(document))
    return bool(query_terms) and all(term in words for term in query_terms)


def array_contains(values, item):
    if values is None or item is None:
        return None
    values = json.loads(values)
    if item in values:
        return True
    return None if None in values else False


def lexical_rank(document, query):
    words = terms(document)
    wanted = terms(query)
    return sum(words.count(term) for term in wanted) / max(1, len(words)) if lexical_match(document, query) else 0.0


def ilike(value, pattern):
    if value is None or pattern is None:
        return None
    parts, escaped = [], False
    for char in pattern:
        if escaped:
            parts.append(re.escape(char))
            escaped = False
        elif char == '\\':
            escaped = True
        else:
            parts.append('.*' if char == '%' else '.' if char == '_' else re.escape(char))
    if escaped:
        parts.append(re.escape('\\'))
    return bool(re.fullmatch(''.join(parts), value, re.IGNORECASE | re.DOTALL))


def json_type(value):
    if value is None:
        return None
    value = json.loads(value)
    return ('null' if value is None else 'boolean' if isinstance(value, bool) else
            'object' if isinstance(value, dict) else 'array' if isinstance(value, list) else
            'string' if isinstance(value, str) else 'number')


def json_set(value, path, replacement):
    value = json.loads(value)
    keys = path.strip('{}').split(',')
    parent = value
    for key in keys[:-1]:
        parent = parent[int(key)] if isinstance(parent, list) else parent[key]
    parent[int(keys[-1]) if isinstance(parent, list) else keys[-1]] = json.loads(replacement)
    return canonical(value)


def register_codecs():
    for name in ('JSONB', 'TEXT_ARRAY'):
        sqlite3.register_converter(name, json.loads)
    sqlite3.register_converter('TIMESTAMPTZ', lambda value: datetime.fromisoformat(value.decode()))
    sqlite3.register_converter('UUID', lambda value: UUID(value.decode()))
    sqlite3.register_converter('BOOLEAN', lambda value: bool(int(value)))


async def register_functions(db, clock):
    functions = [
        ('gen_random_uuid', 0, lambda: str(uuid4())),
        ('clock_timestamp', 0, timestamp),
        ('statement_timestamp', 0, timestamp),
        ('transaction_timestamp', 0, clock),
        ('memory_timestamp', 1, lambda value: timestamp(datetime.fromisoformat(value)) if value is not None else None),
        ('memory_uuid', 1, lambda value: str(UUID(str(value))) if value is not None else None),
        ('memory_shift_time', 2, lambda value, seconds: timestamp(datetime.fromisoformat(value) + timedelta(seconds=seconds))),
        ('memory_array_contains', 2, array_contains),
        ('array_to_string', 2, lambda values, separator: separator.join(json.loads(values))),
        ('repeat', 2, lambda value, count: value * count),
        ('cardinality', 1, lambda value: len(json.loads(value))),
        ('octet_length', 1, lambda value: len(value.encode('utf-8') if isinstance(value, str) else value) if value is not None else None),
        ('jsonb_typeof', 1, json_type),
        ('jsonb_array_length', 1, lambda value: len(json.loads(value)) if value is not None else None),
        ('jsonb_set', 3, json_set),
        ('md5', 1, lambda value: hashlib.md5(value.encode(), usedforsecurity=False).hexdigest()),
        ('regexp', 2, lambda pattern, value: bool(re.search(pattern, value)) if value is not None else None),
        ('memory_ilike', 2, ilike),
        ('memory_lexical_match', 2, lexical_match),
        ('memory_lexical_rank', 2, lexical_rank),
    ]
    for name, arity, function in functions:
        await db.create_function(name, arity, function, deterministic=name not in {
            'gen_random_uuid', 'clock_timestamp', 'statement_timestamp', 'transaction_timestamp',
        })
