"""FastAPI application factory for the ``api`` process.

Hosts the dashboard API and (Phase 6) the TradingView webhook receiver. This
process never holds broker credentials: it can record signals, not trade.

Every ``/api/v1`` route except sign-in requires a session; state-changing
requests also need the session's CSRF token. ``/health/*`` stays open (it
reveals only whether the process and its database are up). The API serves no
static files: Caddy serves the dashboard.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from kterminal import __version__
from kterminal.api.auth.deps import csrf_protect, current_principal
from kterminal.api.auth.passwords import Passwords
from kterminal.api.auth.service import AuthService
from kterminal.api.auth.settings import AuthSettings, load_auth_settings
from kterminal.api.deps import DatabaseProbe
from kterminal.api.errors import ApiError, handle_api_error
from kterminal.api.middleware import NoStoreMiddleware, RequestContextMiddleware
from kterminal.api.routes import (
    accounts,
    auth,
    health,
    killswitches,
    market,
    strategies,
    system,
    trades,
)
from kterminal.config.settings import Settings
from kterminal.core.clock import Clock, SystemClock
from kterminal.observability.logging import get_logger

API_PREFIX = "/api/v1"

_log = get_logger(__name__)


def create_app(
    settings: Settings,
    database: DatabaseProbe,
    clock: Clock | None = None,
    *,
    auth_settings: AuthSettings | None = None,
    passwords: Passwords | None = None,
) -> FastAPI:
    """Build the API. ``database`` must also open sessions (``kterminal.db.Database`` does)
    for anything but the health probes."""
    auth_settings = auth_settings or load_auth_settings()
    if settings.is_production and not auth_settings.cookie_secure:
        raise ValueError("production requires secure session cookies (KT_AUTH__COOKIE_SECURE)")

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        _log.info(
            "api.started",
            version=__version__,
            default_mode=settings.trading.default_mode.value,
            live_trading_permitted=settings.trading.live_trading_permitted,
        )
        try:
            yield
        finally:
            await database.dispose()
            _log.info("api.stopped")

    docs = settings.expose_api_docs
    app = FastAPI(
        title="K Terminal API",
        version=__version__,
        lifespan=lifespan,
        docs_url=f"{API_PREFIX}/docs" if docs else None,
        redoc_url=None,
        openapi_url=f"{API_PREFIX}/openapi.json" if docs else None,
    )
    app.state.settings = settings
    app.state.database = database
    app.state.clock = clock or SystemClock()
    app.state.auth = AuthService(auth_settings, passwords)

    app.add_middleware(NoStoreMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.add_exception_handler(ApiError, handle_api_error)
    app.add_exception_handler(Exception, _unhandled_exception)

    app.include_router(health.router)
    app.include_router(auth.router, prefix=API_PREFIX)
    signed_in = APIRouter(
        prefix=API_PREFIX, dependencies=[Depends(current_principal), Depends(csrf_protect)]
    )
    for module in (system, accounts, trades, market, strategies, killswitches):
        signed_in.include_router(module.router)
    app.include_router(signed_in)
    return app


async def _unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    """Log the error with its correlation ID; never leak internals to the client."""
    request_id = getattr(request.state, "request_id", None)
    _log.error(
        "api.unhandled_exception",
        correlation_id=request_id,
        path=request.url.path,
        exc_info=exc,
    )
    return JSONResponse(
        status_code=500,
        content={"status": "error", "code": "INTERNAL_ERROR", "correlation_id": request_id},
    )
