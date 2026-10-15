"""A throwaway, freshly migrated database per test.

The lab store commits (it is the system of record), so these tests cannot use
the roll-back-everything session of ``tests/integration/db``. Each test gets
its own database created next to the test database and dropped afterwards.
"""

import asyncio
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import pool, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from kterminal.config.settings import DatabaseSettings
from kterminal.core.ids import uuid7
from kterminal.db import migrate
from kterminal.db.session import Database


def _async_dsn(url: str) -> str:
    return DatabaseSettings.model_validate({"url": url}).dsn()


async def _admin(url: str, statement: str) -> None:
    engine = create_async_engine(
        _async_dsn(url), poolclass=pool.NullPool, isolation_level="AUTOCOMMIT"
    )
    try:
        async with engine.connect() as conn:
            await conn.execute(text(statement))
    finally:
        await engine.dispose()


@pytest.fixture
async def fresh_url(database_url: str) -> AsyncIterator[str]:
    name = f"kt_lab_{uuid7().hex[-12:]}"
    await _admin(database_url, f'CREATE DATABASE "{name}"')
    url = make_url(database_url).set(database=name).render_as_string(hide_password=False)
    try:
        await migrate.upgrade(url)
        yield url
    finally:
        await _drop(database_url, name)


async def _drop(database_url: str, name: str) -> None:
    """Drop a test database, waiting out backends this role may not terminate.

    ``WITH (FORCE)`` refuses when another role's backend (typically an autovacuum
    worker after heavy writes) is connected; those finish within moments.
    """
    for attempt in range(50):
        try:
            await _admin(database_url, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
            return
        except DBAPIError as exc:
            if "permission denied to terminate process" not in str(exc) or attempt == 49:
                raise
            await asyncio.sleep(0.2)


@pytest.fixture
async def database(fresh_url: str) -> AsyncIterator[Database]:
    db = Database(
        DatabaseSettings.model_validate({"url": fresh_url}), application_name="kterminal-tests"
    )
    yield db
    await db.dispose()
