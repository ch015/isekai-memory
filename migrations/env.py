"""Alembic environment configuration."""

import os

from alembic import context

config = context.config

# Use the same environment contract as the application. DATABASE_URL remains a
# compatibility fallback for generic Alembic tooling.
url = (
    os.environ.get("ISEKAI_MEMORY_DATABASE_URL")
    or os.environ.get("DATABASE_URL")
    or config.get_main_option("sqlalchemy.url")
)
if url.startswith("postgresql://"):
    url = "postgresql+psycopg://" + url.removeprefix("postgresql://")


def run_migrations_offline() -> None:
    context.configure(url=url, target_metadata=None, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    from sqlalchemy import create_engine

    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=None)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
