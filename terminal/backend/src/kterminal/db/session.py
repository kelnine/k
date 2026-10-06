"""Async PostgreSQL engine and session management."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from kterminal.config.settings import DatabaseSettings
from kterminal.observability.logging import get_logger

_log = get_logger(__name__)


class Database:
    """Owns the connection pool for one process.

    Creating a ``Database`` does not connect; the first query does. That lets
    the API start (and report "not ready") while PostgreSQL is still booting.
    """

    def __init__(self, settings: DatabaseSettings, *, application_name: str = "kterminal") -> None:
        self._engine: AsyncEngine = create_async_engine(
            settings.dsn(),
            pool_size=settings.pool_size,
            max_overflow=settings.max_overflow,
            pool_timeout=settings.pool_timeout_s,
            pool_pre_ping=True,
            echo=settings.echo,
            hide_parameters=True,  # never echo bound values (could contain secrets) in errors
            connect_args={
                "timeout": settings.connect_timeout_s,
                "server_settings": {"application_name": application_name},
            },
        )
        self._sessions = async_sessionmaker(self._engine, expire_on_commit=False)

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Unit of work: commits on success, rolls back on any exception."""
        async with self._sessions() as session:
            try:
                yield session
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

    async def ping(self, timeout_s: float = 2.0) -> bool:
        """True if a trivial query succeeds within ``timeout_s``."""
        try:
            async with asyncio.timeout(timeout_s), self._engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception as exc:
            _log.warning("database.ping_failed", error=type(exc).__name__)
            return False
        return True

    async def dispose(self) -> None:
        await self._engine.dispose()
