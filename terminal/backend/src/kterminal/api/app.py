"""FastAPI application factory for the ``api`` process.

Hosts the dashboard API and (Phase 6) the TradingView webhook receiver. This
process never holds broker credentials: it can record signals, not trade.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from kterminal import __version__
from kterminal.api.deps import DatabaseProbe
from kterminal.api.middleware import RequestContextMiddleware
from kterminal.api.routes import health, system
from kterminal.config.settings import Settings
from kterminal.core.clock import Clock, SystemClock
from kterminal.observability.logging import get_logger

API_PREFIX = "/api/v1"

_log = get_logger(__name__)


def create_app(settings: Settings, database: DatabaseProbe, clock: Clock | None = None) -> FastAPI:
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

    app.add_middleware(RequestContextMiddleware)
    app.add_exception_handler(Exception, _unhandled_exception)

    app.include_router(health.router)
    app.include_router(system.router, prefix=API_PREFIX)
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
