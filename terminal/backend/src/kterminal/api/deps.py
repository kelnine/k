"""FastAPI dependencies that expose process-wide services to route handlers."""

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from typing import Protocol, cast, runtime_checkable

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from kterminal.api.errors import ApiError
from kterminal.config.settings import Settings
from kterminal.core.clock import Clock


class DatabaseProbe(Protocol):
    """What the API needs from the database in Phase 1 (``kterminal.db.Database`` satisfies it)."""

    async def ping(self, timeout_s: float = 2.0) -> bool: ...

    async def dispose(self) -> None: ...


@runtime_checkable
class SessionProvider(Protocol):
    """A database that also opens units of work (``kterminal.db.Database`` does)."""

    def session(self) -> AbstractAsyncContextManager[AsyncSession]: ...


def get_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def get_database(request: Request) -> DatabaseProbe:
    return cast(DatabaseProbe, request.app.state.database)


def get_clock(request: Request) -> Clock:
    return cast(Clock, request.app.state.clock)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """One database session (one transaction) per request; committed when the request
    succeeds. Write endpoints commit explicitly before they answer."""
    database = request.app.state.database
    if not isinstance(database, SessionProvider):
        raise ApiError(503, "DATABASE_UNAVAILABLE", "the database is not configured")
    async with database.session() as session:
        yield session
