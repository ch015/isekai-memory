"""Serverless persistence, cross-process fencing and SQLite transaction behavior."""
import asyncio
import json
import sqlite3
import subprocess
import sys
from urllib.parse import quote
from uuid import uuid4

import asyncpg
import pytest

from isekai_memory.config import Settings, load_settings
from isekai_memory.store.sqlite import APPLICATION_ID, SCHEMA_VERSION, SQLitePool, database_path
from isekai_memory.store.sqlite_dialect import compile_query
from isekai_memory.store.sqlite_functions import array_contains
from isekai_memory.store.sqlite_health import health_check


def url(path):
    return 'sqlite:///' + quote(str(path), safe='/')


@pytest.fixture
async def local(tmp_path):
    pool = await SQLitePool.open(url(tmp_path / 'memory.db'))
    try:
        yield pool
    finally:
        await pool.close()


async def test_bootstrap_persistence_private_files_and_ready(tmp_path):
    path = tmp_path / 'new' / 'memory 한글.db'
    pool = await SQLitePool.open(url(path))
    try:
        result = await health_check(pool, '020')
        assert result == {'database': 'ok', 'schema_revision': '020', 'backend': 'sqlite'}
        secret = await pool.fetchval('SELECT secret FROM memory_event_cursor_key')
        assert len(secret) == 32
        await pool.execute('INSERT INTO memory_event_heads(project_id,position) VALUES($1,$2)', 'durable', 17)
        assert path.stat().st_mode & 0o777 == 0o600
        assert await pool.fetchval('PRAGMA foreign_keys') == 1
        assert await pool.fetchval('PRAGMA journal_mode') == 'wal'
    finally:
        await pool.close()
    reopened = await SQLitePool.open(url(path))
    try:
        assert await reopened.fetchval('SELECT position FROM memory_event_heads WHERE project_id=$1', 'durable') == 17
        assert await reopened.fetchval('SELECT secret FROM memory_event_cursor_key') == secret
        assert await reopened.fetchval('PRAGMA integrity_check') == 'ok'
    finally:
        await reopened.close()


async def test_unrelated_newer_and_incomplete_files_are_not_reinitialized(tmp_path):
    path = tmp_path / 'other.db'
    with sqlite3.connect(path) as raw:
        raw.execute('CREATE TABLE user_data(value TEXT)')
        raw.execute("INSERT INTO user_data VALUES ('retain')")
    before = path.read_bytes()
    with pytest.raises(RuntimeError, match='unrelated'):
        await SQLitePool.open(url(path))
    assert path.read_bytes() == before
    with sqlite3.connect(path) as raw:
        raw.execute(f'PRAGMA application_id={APPLICATION_ID}')
        raw.execute(f'PRAGMA user_version={SCHEMA_VERSION+1}')
    before = path.read_bytes()
    with pytest.raises(RuntimeError, match='Unsupported'):
        await SQLitePool.open(url(path))
    assert path.read_bytes() == before
    with sqlite3.connect(path) as raw:
        raw.execute(f'PRAGMA user_version={SCHEMA_VERSION}')
    with pytest.raises(sqlite3.OperationalError, match='alembic_version'):
        await SQLitePool.open(url(path))


async def test_readonly_nested_savepoint_and_cancel_rollback(local):
    async with local.acquire() as conn, conn.transaction(readonly=True):
        assert await conn.fetchval('SELECT count(*) FROM memory_event_heads') == 0
        with pytest.raises(asyncpg.ReadOnlySQLTransactionError):
            await conn.execute("INSERT INTO memory_event_heads(project_id,position) VALUES('denied',1)")
    async with local.acquire() as conn, conn.transaction():
        await conn.execute("INSERT INTO memory_event_heads(project_id,position) VALUES('outer',1)")
        with pytest.raises(ValueError):
            async with conn.transaction():
                await conn.execute("INSERT INTO memory_event_heads(project_id,position) VALUES('inner',1)")
                raise ValueError('rollback savepoint')
        assert await conn.fetchval('SELECT count(*) FROM memory_event_heads') == 1
    started = asyncio.Event()

    async def cancelled_writer():
        async with local.acquire() as conn, conn.transaction():
            await conn.execute("UPDATE memory_event_heads SET position=2 WHERE project_id='outer'")
            started.set()
            await asyncio.Event().wait()
    task = asyncio.create_task(cancelled_writer())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await local.fetchval("SELECT position FROM memory_event_heads WHERE project_id='outer'") == 1
    assert await local.fetchval('PRAGMA query_only') == 0


async def test_statement_budget_and_parameter_literals(local):
    value = "quoted $1, $2 ::uuid; ' OR 1=1 -- 한글"
    assert await local.fetchval('SELECT $1::text', value) == value
    assert await local.fetchval("SELECT '$1,$2::uuid'") == '$1,$2::uuid'
    assert await local.fetchval("SELECT $1::timestamptz=$2::timestamptz", '2026-01-01T09:00:00+09:00', '2026-01-01T00:00:00Z')
    async with local.acquire() as conn, conn.transaction():
        await conn.execute("SET LOCAL statement_timeout='1ms'")
        with pytest.raises(asyncpg.QueryCanceledError):
            await conn.fetchval('WITH RECURSIVE numbers(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM numbers WHERE n<10000000) SELECT sum(n) FROM numbers')
    assert await local.fetchval('SELECT 1') == 1
    assert array_contains('["a"]', None) is None
    assert array_contains('["a",null]', 'b') is None
    assert array_contains('["a"]', 'b') is False


async def test_independent_connections_serialize_commit_and_rollback(tmp_path):
    path = tmp_path / 'concurrent.db'
    first, second = await asyncio.gather(SQLitePool.open(url(path)), SQLitePool.open(url(path)))
    try:
        started = asyncio.Event()

        async def next_writer():
            started.set()
            async with second.acquire() as conn, conn.transaction():
                await conn.execute("UPDATE memory_event_heads SET position=position+1 WHERE project_id='work'")
        async with first.acquire() as conn, conn.transaction():
            await conn.execute("INSERT INTO memory_event_heads(project_id,position) VALUES('work',1)")
            waiting = asyncio.create_task(next_writer())
            await started.wait()
            await asyncio.sleep(0.03)
            assert not waiting.done()
        await asyncio.wait_for(waiting, 3)
        assert await first.fetchval("SELECT position FROM memory_event_heads WHERE project_id='work'") == 2
        with pytest.raises(ValueError):
            async with first.acquire() as conn, conn.transaction():
                await conn.execute("UPDATE memory_event_heads SET position=3 WHERE project_id='work'")
                raise ValueError('abort')
        assert await second.fetchval("SELECT position FROM memory_event_heads WHERE project_id='work'") == 2
    finally:
        await first.close()
        await second.close()


def test_two_processes_use_same_file_without_lost_updates(tmp_path):
    script = '''
import asyncio,sys
from isekai_memory.store.sqlite import SQLitePool
async def run():
    pool=await SQLitePool.open(sys.argv[1])
    try:
        for _ in range(25):
            async with pool.acquire() as conn, conn.transaction():
                await conn.execute("INSERT INTO memory_event_heads(project_id,position) VALUES('shared',1) ON CONFLICT(project_id) DO UPDATE SET position=memory_event_heads.position+1")
    finally:
        await pool.close()
asyncio.run(run())
'''
    path = tmp_path / 'processes.db'
    workers = [subprocess.Popen([sys.executable, '-c', script, url(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
    try:
        for worker in workers:
            _, errors = worker.communicate(timeout=20)
            assert worker.returncode == 0, errors.decode()
    finally:
        for worker in workers:
            if worker.poll() is None:
                worker.kill()
                worker.wait()
    with sqlite3.connect(path) as raw:
        assert raw.execute("SELECT position FROM memory_event_heads WHERE project_id='shared'").fetchone() == (50,)


def test_cli_tokens_reopen_and_settings(tmp_path, monkeypatch):
    monkeypatch.delenv('ISEKAI_MEMORY_HOST', raising=False)
    monkeypatch.delenv('ISEKAI_MEMORY_DATABASE_URL', raising=False)
    path = tmp_path / 'cli.db'
    command = [sys.executable, '-m', 'isekai_memory.main', '--sqlite', str(path)]
    issued = json.loads(subprocess.check_output(command + ['--issue-token', '--project-id', 'project-local', '--user-id', 'local-test']))
    assert issued['token'] and issued['user_id'] == 'local-test'
    revoked = json.loads(subprocess.check_output(command + ['--revoke-token', issued['token_id']]))
    assert revoked['revoked']
    assert Settings(database_url=url(path)).host == '127.0.0.1'
    assert Settings(database_url=url(path), host='0.0.0.0').host == '0.0.0.0'
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'database_url': url(path)}))
    assert load_settings(config).database_url == url(path)
    assert database_path(url(tmp_path / '한글 #1.db')) == tmp_path / '한글 #1.db'
    for value in ('sqlite://host/db', 'sqlite:///', 'sqlite:///:memory:', 'sqlite:///db?mode=rw'):
        with pytest.raises(ValueError):
            Settings(database_url=value)


def test_compiler_does_not_rewrite_literal_content():
    compiled, locked = compile_query("SELECT '$1,$2::text FOR UPDATE' AS text, $1::uuid FOR UPDATE")
    assert "'$1,$2::text FOR UPDATE'" in compiled and ':p1' in compiled and locked
    assert str(uuid4()) not in compiled
