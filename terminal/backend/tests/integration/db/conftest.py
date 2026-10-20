"""Fixtures for the PostgreSQL schema tests (set KT_TEST_DATABASE_URL to run them).

The test database is reset (``DROP SCHEMA public CASCADE``) and migrated to
the newest revision once per test process. Every test then works inside one
transaction that is rolled back afterwards — repositories never commit — so
tests cannot see each other's rows. Tests that must commit (the migration
round trip) leave the schema at head when they finish.
"""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from kterminal.config.settings import DatabaseSettings
from kterminal.db import migrate

_PREPARED: set[str] = set()


def async_dsn(url: str) -> str:
    return DatabaseSettings.model_validate({"url": url}).dsn()


async def reset_schema(url: str) -> None:
    engine = create_async_engine(async_dsn(url), poolclass=pool.NullPool)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
    finally:
        await engine.dispose()


@pytest.fixture
async def migrated_url(database_url: str) -> str:
    """The test database URL, with a freshly migrated schema (prepared once per process)."""
    if database_url not in _PREPARED:
        await reset_schema(database_url)
        await migrate.upgrade(database_url)
        _PREPARED.add(database_url)
    return database_url


@pytest.fixture
async def engine(migrated_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(async_dsn(migrated_url), poolclass=pool.NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """A session inside an outer transaction that is always rolled back."""
    async with engine.connect() as conn:
        outer = await conn.begin()
        db_session = AsyncSession(
            bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        try:
            yield db_session
        finally:
            await db_session.close()
            await outer.rollback()
