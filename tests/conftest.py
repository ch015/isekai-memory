"""Run the existing integration suite with an isolated, serverless DB via --sqlite."""
import os
import tempfile
from pathlib import Path

import pytest


def pytest_addoption(parser):
    parser.addoption('--sqlite', action='store_true', help='Use a fresh disposable SQLite file for DB integration tests')


def pytest_configure(config):
    if config.getoption('--sqlite'):
        config._sqlite_original_url = os.environ.get('MEMORY_TEST_DATABASE_URL')
        config._sqlite_directory = tempfile.TemporaryDirectory(prefix='memory-sqlite-tests-')
        os.environ['MEMORY_TEST_DATABASE_URL'] = 'sqlite:///' + str(Path(config._sqlite_directory.name) / 'memory.db')


def pytest_collection_modifyitems(items):
    if os.environ.get('MEMORY_TEST_DATABASE_URL', '').startswith('sqlite:'):
        for item in items:
            if item.get_closest_marker('postgres_only'):
                item.add_marker(pytest.mark.skip(reason='PostgreSQL lock/catalog internals; SQLite concurrency tested separately'))


def pytest_unconfigure(config):
    directory = getattr(config, '_sqlite_directory', None)
    if directory is not None:
        original = config._sqlite_original_url
        if original is None:
            os.environ.pop('MEMORY_TEST_DATABASE_URL', None)
        else:
            os.environ['MEMORY_TEST_DATABASE_URL'] = original
        directory.cleanup()
