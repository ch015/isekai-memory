"""File-backed SQLite with serialized async access and durable transactions.

One worker connection per process is deliberate: local Memory needs no pool or
DB daemon. BEGIN IMMEDIATE serializes writers across processes as well. WAL
allows external readers; foreign keys and immutable-history triggers stay on.
"""
from __future__ import annotations

import asyncio
import os
import re
import secrets
import sqlite3
import time
from contextlib import asynccontextmanager
from datetime import datetime
from importlib.resources import files
from pathlib import Path
from urllib.parse import unquote

import aiosqlite
import asyncpg

from .sqlite_dialect import compile_query
from .sqlite_functions import encode, register_codecs, register_functions, timestamp

APPLICATION_ID = 0x49534B4D
SCHEMA_VERSION = 20


def database_path(url: str) -> Path:
    if not url.startswith('sqlite:///') or '?' in url or '#' in url:
        raise ValueError('Use sqlite:///relative.db or sqlite:////absolute/path.db (no URI options)')
    value = unquote(url.removeprefix('sqlite:///'))
    if not value or value == ':memory:' or '\x00' in value:
        raise ValueError('SQLite mode requires a persistent file path')
    return Path(value).expanduser().absolute()


class SQLiteConnection:
    backend = 'sqlite'

    def __init__(self, db):
        self.db = db
        self.depth = 0
        self.started_at = None
        self.deadline = None

    def clock(self):
        return self.started_at or timestamp()

    @asynccontextmanager
    async def transaction(self, *, isolation=None, readonly=False):
        outer = self.depth == 0
        savepoint = f'memory_{self.depth}'
        try:
            if outer and readonly:
                await self.db.execute('PRAGMA query_only=ON')
            await self.db.execute(('BEGIN' if readonly else 'BEGIN IMMEDIATE') if outer else f'SAVEPOINT {savepoint}')
            if outer:
                self.started_at = timestamp()
            self.depth += 1
            yield self
            await self.db.execute('COMMIT' if outer else f'RELEASE SAVEPOINT {savepoint}')
        except BaseException as exc:
            # Queued after an interrupted worker statement, before the next user
            # of the connection. Even cancellation must finish rollback.
            self.deadline = None
            if isinstance(exc, asyncio.CancelledError):
                await self.db.interrupt()
            if outer:
                await self.db.rollback()
            else:
                await self.db.execute(f'ROLLBACK TO SAVEPOINT {savepoint}')
                await self.db.execute(f'RELEASE SAVEPOINT {savepoint}')
            if isinstance(exc, sqlite3.OperationalError) and getattr(exc, 'sqlite_errorcode', None) in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
                raise asyncpg.QueryCanceledError('SQLite database is busy; retry the operation') from exc
            raise
        finally:
            self.depth = max(0, self.depth - 1)
            if outer:
                self.started_at = None
                self.deadline = None
                if readonly:
                    await self.db.execute('PRAGMA query_only=OFF')

    async def _run(self, sql, args):
        normalized = ' '.join(sql.strip().split())
        timeout = re.fullmatch(r"SET LOCAL statement_timeout\s*=\s*'(\d+)(ms|s)'", normalized, re.I)
        if timeout:
            if not self.depth:
                raise RuntimeError('SET LOCAL requires a transaction')
            self.deadline = time.monotonic() + int(timeout[1]) / (1000 if timeout[2] == 'ms' else 1)
            return [], 'SET'
        if re.fullmatch(r'SELECT pg_advisory_xact_lock\(hashtextextended\(\$1,\s*0\)\)', normalized, re.I):
            if not self.depth:
                raise RuntimeError('Advisory lock requires a SQLite write transaction')
            return [], 'SELECT 1'
        statement, locked = compile_query(sql)
        if locked and not self.depth:
            async with self.transaction():
                return await self._run(sql, args)
        try:
            async with self.db.execute(statement, {'p'+str(i): encode(value) for i, value in enumerate(args, 1)}) as cursor:
                raw = await cursor.fetchall()
                columns = [item[0] for item in cursor.description or ()]
                rows = [dict(zip(columns, row, strict=True)) for row in raw]
                # SQLite only applies declared-type codecs to direct columns.
                # Clock expressions and aggregate timestamps need decoding too.
                for row in rows:
                    for name, value in row.items():
                        if name in {'expired', 'preview_truncated'} and value is not None:
                            row[name] = bool(value)
                        if (isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}T.*[+]00:00', value)
                                and (name.endswith(('_at', '_until', '_from'))
                                     or name.lower() in {'clock_timestamp()', 'transaction_timestamp()'})):
                            row[name] = datetime.fromisoformat(value)
                count = cursor.rowcount
                if count < 0 and re.search(r'\b(UPDATE|DELETE|INSERT)\b', statement, re.I):
                    async with self.db.execute('SELECT changes()') as changed:
                        count = (await changed.fetchone())[0]
                operation = normalized.split()[0].upper()
                if operation == 'WITH':
                    operation = 'UPDATE'  # The repository's mutation CTEs retire sessions.
                status = f'INSERT 0 {count}' if operation == 'INSERT' else f'{operation} {max(count, len(rows))}'
                return rows, status
        except sqlite3.IntegrityError as exc:
            # Preserve the repository's existing, backend-neutral caller contract.
            code = getattr(exc, 'sqlite_errorname', '')
            error = {'SQLITE_CONSTRAINT_FOREIGNKEY': asyncpg.ForeignKeyViolationError,
                     'SQLITE_CONSTRAINT_UNIQUE': asyncpg.UniqueViolationError,
                     'SQLITE_CONSTRAINT_PRIMARYKEY': asyncpg.UniqueViolationError,
                     'SQLITE_CONSTRAINT_CHECK': asyncpg.CheckViolationError,
                     'SQLITE_CONSTRAINT_NOTNULL': asyncpg.NotNullViolationError,
                     'SQLITE_CONSTRAINT_TRIGGER': asyncpg.RaiseError}.get(code, asyncpg.IntegrityConstraintViolationError)
            if str(exc).startswith('FOREIGN KEY'):
                error = asyncpg.ForeignKeyViolationError
            elif str(exc).startswith('guard_experience_'):
                error = asyncpg.CheckViolationError
            raise error(str(exc)) from exc
        except sqlite3.OperationalError as exc:
            if getattr(exc, 'sqlite_errorcode', None) == sqlite3.SQLITE_READONLY:
                raise asyncpg.ReadOnlySQLTransactionError('SQLite transaction is read-only') from exc
            if getattr(exc, 'sqlite_errorcode', None) in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED, sqlite3.SQLITE_INTERRUPT}:
                raise asyncpg.QueryCanceledError('SQLite operation exceeded its time budget') from exc
            raise

    async def fetch(self, sql, *args):
        return (await self._run(sql, args))[0]

    async def fetchrow(self, sql, *args):
        rows = await self.fetch(sql, *args)
        return rows[0] if rows else None

    async def fetchval(self, sql, *args, column=0):
        row = await self.fetchrow(sql, *args)
        return list(row.values())[column] if row else None

    async def execute(self, sql, *args):
        return (await self._run(sql, args))[1]


class SQLitePool:
    backend = 'sqlite'

    def __init__(self, db):
        self.db = db
        self.connection = SQLiteConnection(db)
        self.lock = asyncio.Lock()
        self.owner = None

    @classmethod
    async def open(cls, url):
        if sqlite3.sqlite_version_info < (3, 38):
            raise RuntimeError('SQLite mode requires SQLite 3.38 or newer (JSON and RETURNING support)')
        path = database_path(url)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        os.close(descriptor)
        register_codecs()
        db = await aiosqlite.connect(path, isolation_level=None, timeout=5, detect_types=sqlite3.PARSE_DECLTYPES)
        pool = cls(db)
        try:
            await register_functions(db, pool.connection.clock)
            await db.execute('PRAGMA foreign_keys=ON')
            await db.execute('PRAGMA recursive_triggers=ON')
            await db.execute('PRAGMA synchronous=FULL')
            await pool._initialize()
            await pool._enable_wal()
            from .sqlite_health import health_check
            await health_check(pool, '020')
            await db.set_progress_handler(lambda: int(pool.connection.deadline is not None and time.monotonic() >= pool.connection.deadline), 1000)
        except BaseException:
            await db.close()
            raise
        return pool

    async def _enable_wal(self):
        # Journal-mode changes may return BUSY immediately during concurrent
        # first starts even with busy_timeout. Retry only this bounded setup step.
        deadline = time.monotonic() + 5
        while True:
            try:
                async with self.db.execute('PRAGMA journal_mode=WAL') as cursor:
                    if (await cursor.fetchone())[0] != 'wal':
                        raise RuntimeError('Could not enable SQLite WAL mode')
                return
            except sqlite3.OperationalError as exc:
                if getattr(exc, 'sqlite_errorcode', None) != sqlite3.SQLITE_BUSY or time.monotonic() >= deadline:
                    raise
                await asyncio.sleep(0.025)

    async def _initialize(self):
        async with self.connection.transaction():
            async with self.db.execute('PRAGMA user_version') as cursor:
                version = (await cursor.fetchone())[0]
            async with self.db.execute('PRAGMA application_id') as cursor:
                identity = (await cursor.fetchone())[0]
            if version or identity:
                if (identity, version) != (APPLICATION_ID, SCHEMA_VERSION):
                    raise RuntimeError('Unsupported SQLite Memory schema; database was not modified')
                return
            async with self.db.execute("SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'") as cursor:
                if await cursor.fetchone():
                    raise RuntimeError('Refusing to initialize an existing unrelated SQLite database')
            for resource in sorted(files('isekai_memory.store').joinpath('sqlite_schema').iterdir(), key=lambda item: item.name):
                if resource.name.endswith('.sql'):
                    statement = ''
                    for line in resource.read_text(encoding='utf-8').splitlines(keepends=True):
                        statement += line
                        if sqlite3.complete_statement(statement):
                            await self.db.execute(statement)
                            statement = ''
                    if statement.strip():
                        raise RuntimeError(f'Incomplete SQLite schema resource: {resource.name}')
            await self.db.execute("INSERT INTO alembic_version VALUES ('020')")
            await self.db.execute('INSERT INTO memory_event_cursor_key(singleton,secret) VALUES(1,?)', (secrets.token_bytes(32),))
            await self.db.execute(f'PRAGMA application_id={APPLICATION_ID}')
            await self.db.execute(f'PRAGMA user_version={SCHEMA_VERSION}')

    @asynccontextmanager
    async def acquire(self):
        task = asyncio.current_task()
        if self.owner is task:
            if self.connection.depth:
                raise RuntimeError('Pass the existing connection inside a SQLite transaction')
            yield self.connection
            return
        async with self.lock:
            self.owner = task
            try:
                yield self.connection
            finally:
                self.connection.deadline = None
                # Drain cancelled autocommit statements before releasing the lock.
                try:
                    await self.db.rollback()
                finally:
                    self.owner = None

    async def close(self):
        async with self.lock:
            await self.db.close()

    async def execute(self, sql, *args):
        async with self.acquire() as conn:
            return await conn.execute(sql, *args)

    async def fetch(self, sql, *args):
        async with self.acquire() as conn:
            return await conn.fetch(sql, *args)

    async def fetchrow(self, sql, *args):
        async with self.acquire() as conn:
            return await conn.fetchrow(sql, *args)

    async def fetchval(self, sql, *args):
        async with self.acquire() as conn:
            return await conn.fetchval(sql, *args)
