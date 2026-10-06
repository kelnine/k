"""Alembic environment for K Terminal.

There is no ``alembic.ini``: :mod:`kterminal.db.migrate` builds the Alembic
``Config`` in code with ``script_location = "kterminal.db:migrations"``, so the
migrations ship inside the package (and the Docker image) and run anywhere the
package is installed.

How the database is reached, in order of preference:

1. ``config.attributes["connection"]`` — a *sync* SQLAlchemy connection that
   :mod:`kterminal.db.migrate` obtained from an asyncpg engine with
   ``AsyncConnection.run_sync``; the migration joins its transaction.
2. ``config.attributes["dsn"]`` or the ``sqlalchemy.url`` main option.
3. The application settings (``KT_DATABASE__URL`` / ``KT_DATABASE__PASSWORD``).

Offline mode (``--sql``) renders the SQL for review without connecting.
"""

import asyncio
from typing import Any

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from kterminal.config.settings import DatabaseSettings, Settings
from kterminal.db.models import Base
from kterminal.db.partitions import is_partition_name

config = context.config
target_metadata = Base.metadata


def include_name(name: str | None, type_: str, parent_names: Any) -> bool:
    """Skip run-time partitions: they are created by ``ensure_monthly_partitions``."""
    return not (type_ == "table" and name is not None and is_partition_name(name))


def _dsn() -> str:
    explicit = config.attributes.get("dsn") or config.get_main_option("sqlalchemy.url")
    if explicit:
        return DatabaseSettings.model_validate({"url": explicit}).dsn()
    return Settings().database.dsn()


def _configure(**kwargs: Any) -> None:
    context.configure(
        target_metadata=target_metadata,
        include_name=include_name,
        compare_type=True,
        **kwargs,
    )


def run_migrations_offline() -> None:
    _configure(url=_dsn(), literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_async_engine(_dsn(), poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(do_run_migrations)
            await connection.commit()
    finally:
        await engine.dispose()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        do_run_migrations(connection)
    else:
        asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
