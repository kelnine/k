"""FastAPI dependencies that expose process-wide services to route handlers."""

from typing import Protocol, cast

from fastapi import Request

from kterminal.config.settings import Settings
from kterminal.core.clock import Clock


class DatabaseProbe(Protocol):
    """What the API needs from the database in Phase 1 (``kterminal.db.Database`` satisfies it)."""

    async def ping(self, timeout_s: float = 2.0) -> bool: ...

    async def dispose(self) -> None: ...


def get_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def get_database(request: Request) -> DatabaseProbe:
    return cast(DatabaseProbe, request.app.state.database)


def get_clock(request: Request) -> Clock:
    return cast(Clock, request.app.state.clock)
