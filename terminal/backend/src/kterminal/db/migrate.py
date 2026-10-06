"""Schema migrations: upgrade, downgrade, inspect and verify the live database.

Alembic is driven programmatically — there is no ``alembic.ini``. The scripts
live in the package (``kterminal.db:migrations``) so they ship with the wheel
and the Docker image, and every function here takes a plain DSN
(``postgresql://…`` or ``postgresql+asyncpg://…``).

The functions are coroutines: they run Alembic synchronously on a connection
borrowed from an asyncpg engine (``AsyncConnection.run_sync``), which is the
only way to migrate from inside a running event loop (the API, the tests).
Migrations run in one transaction under an advisory lock, so two processes
starting at once cannot both apply the same revision.

:func:`check` compares the declarative models with the live database
(Alembic's autogenerate comparison) and reports any drift; it must be empty
after :func:`upgrade`, and the start-up readiness check can use it to refuse
to trade on a schema that does not match the code.
"""

from collections.abc import AsyncIterator, Callable, Iterable
from contextlib import asynccontextmanager
from typing import Any, Final

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.schema import SchemaItem

from kterminal.config.settings import DatabaseSettings
from kterminal.db.locks import lock_key
from kterminal.db.models import Base
from kterminal.db.partitions import is_partition_name
from kterminal.observability.logging import get_logger

_log = get_logger(__name__)

SCRIPT_LOCATION: Final = "kterminal.db:migrations"
MIGRATION_LOCK: Final = "kterminal.db.migrate"


def alembic_config() -> Config:
    """An Alembic ``Config`` without an ini file (also usable with ``alembic.command``)."""
    config = Config()
    config.set_main_option("script_location", SCRIPT_LOCATION)
    return config


def head_revision() -> str | None:
    """The newest revision shipped with this version of the code."""
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def _async_dsn(dsn: str) -> str:
    """Normalise ``postgres://`` / ``postgresql://`` to the asyncpg driver."""
    return DatabaseSettings.model_validate({"url": dsn}).dsn()


@asynccontextmanager
async def _engine(dsn: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(_async_dsn(dsn), poolclass=pool.NullPool)
    try:
        yield engine
    finally:
        await engine.dispose()


def _run_command(connection: Connection, action: Callable[..., None], revision: str) -> None:
    connection.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": lock_key(MIGRATION_LOCK)})
    config = alembic_config()
    config.attributes["connection"] = connection
    action(config, revision)


async def upgrade(dsn: str, revision: str = "head") -> None:
    """Apply migrations up to ``revision`` (default: the newest)."""
    async with _engine(dsn) as engine, engine.begin() as conn:
        await conn.run_sync(_run_command, command.upgrade, revision)
    _log.info("db.migrated", direction="upgrade", revision=revision)


async def downgrade(dsn: str, revision: str) -> None:
    """Revert migrations down to ``revision`` (``"base"`` removes the whole schema)."""
    async with _engine(dsn) as engine, engine.begin() as conn:
        await conn.run_sync(_run_command, command.downgrade, revision)
    _log.warning("db.migrated", direction="downgrade", revision=revision)


def _current_revision(connection: Connection) -> str | None:
    return MigrationContext.configure(connection).get_current_revision()


async def current(dsn: str) -> str | None:
    """The revision the database is at, or ``None`` if it was never migrated."""
    async with _engine(dsn) as engine, engine.connect() as conn:
        return await conn.run_sync(_current_revision)


def _include_name(name: str | None, type_: str, parent_names: Any) -> bool:
    return not (type_ == "table" and name is not None and is_partition_name(name))


def _describe_value(value: Any) -> str:
    if isinstance(value, SchemaItem):
        table = getattr(value, "table", None)
        owner = f"{table.name}." if table is not None and hasattr(table, "name") else ""
        return f"{type(value).__name__}({owner}{getattr(value, 'name', '')})"
    return repr(value)


def _describe(diff: Any) -> Iterable[str]:
    if isinstance(diff, list):  # column modifications come grouped per column
        for item in diff:
            yield from _describe(item)
        return
    operation, *details = diff
    yield f"{operation}: " + ", ".join(_describe_value(d) for d in details if d is not None)


def _compare(connection: Connection) -> list[str]:
    context = MigrationContext.configure(
        connection,
        opts={"compare_type": True, "include_name": _include_name},
    )
    differences = [
        line for diff in compare_metadata(context, Base.metadata) for line in _describe(diff)
    ]
    at, head = context.get_current_revision(), head_revision()
    if at != head:
        differences.insert(0, f"revision: database is at {at!r}, code expects {head!r}")
    return differences


async def check(dsn: str) -> list[str]:
    """Differences between the models (and newest revision) and the live database.

    An empty list means the database schema is exactly what the code expects.
    Partitions created at run time are ignored; Alembic does not compare CHECK
    constraints, triggers or server defaults.
    """
    async with _engine(dsn) as engine, engine.connect() as conn:
        return await conn.run_sync(_compare)
