"""Installed entry point: HTTP and stdio sharing a file, no PostgreSQL process."""
import asyncio
import json
import socket
import subprocess
import sys
from datetime import UTC, datetime
from uuid import uuid4

import httpx

from tests.stdio_e2e_smoke import request
from tests.test_project_directory import metadata


async def test_http_stdio_and_restart_preserve_project_history(tmp_path):
    path = tmp_path / 'memory.db'
    command = [sys.executable, '-m', 'isekai_memory.main', '--sqlite', str(path)]
    token = json.loads(subprocess.check_output(command + ['--issue-token', '--project-id', 'directory', '--user-id', 'owner', '--scopes', 'admin,projects']))['token']
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    process = subprocess.Popen(command + ['--mode', 'http', '--port', str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    project = 'sqlite-transport-' + uuid4().hex
    try:
        async with httpx.AsyncClient(base_url=f'http://127.0.0.1:{port}', timeout=3) as client:
            for _ in range(100):
                try:
                    ready = await client.get('/ready')
                    if ready.status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                assert process.poll() is None, 'HTTP process exited during startup'
                await asyncio.sleep(0.03)
            else:
                raise AssertionError('HTTP server did not become ready')
            assert ready.json()['backend'] == 'sqlite'
            headers = {'Authorization': 'Bearer ' + token}
            assert (await client.get('/tools')).status_code == 401
            setup = {**metadata(project), 'source_kind': 'directory', 'git_url': None, 'git_ref': None}
            response = await client.post('/tools/memory_project_register', headers=headers, json=setup)
            assert response.status_code == 200, response.text
            record = {'project_id': project, 'expected_actor': 'owner', 'record_id': str(uuid4()), 'kind': 'activity', 'title': '로컬 작업 결정',
                      'body': 'SQLite에서도 프로젝트 작업 내역과 결정사항을 공유합니다.', 'refs': [], 'occurred_at': datetime.now(UTC).isoformat()}
            saved = await client.post('/tools/memory_project_record_put', headers=headers, json=record)
            assert saved.status_code == 200, saved.text
            found = await client.post('/tools/memory_project_record_list', headers=headers, json={'project_id': project, 'query': '결정사항'})
            assert found.status_code == 200, found.text
            assert record['record_id'] in found.text
            # A distinct stdio process reads the same durable project record.
            frame = request(1, 'tools/call', {'name': 'memory_project_record_list', 'arguments': {'project_id': project}}) + '\n'
            completed = await asyncio.to_thread(subprocess.run, command + ['--mode', 'stdio'], input=frame, text=True, capture_output=True, timeout=10)
            assert completed.returncode == 0, completed.stderr
            result = json.loads(completed.stdout)['result']
            assert not result['isError'] and result['structuredContent']['items'][0]['record_id'] == record['record_id']
    finally:
        process.terminate()
        try:
            await asyncio.to_thread(process.wait, timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    # Restart through a different transport and verify file contents survive.
    completed = subprocess.run(command + ['--mode', 'stdio'], input=frame, text=True, capture_output=True, timeout=10)
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)['result']['structuredContent']['items'][0]['body'] == record['body']
