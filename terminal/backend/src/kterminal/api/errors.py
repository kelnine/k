"""Error responses of the dashboard API.

Every error has the same shape as the unhandled-exception response:
``{"status": "error", "code": "...", "message": "...", "correlation_id": "..."}``.
Messages are written for the operator; they never contain internals.
"""

from collections.abc import Mapping

from fastapi import Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    """An expected failure with a stable, machine-readable ``code``."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str = "",
        *,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(message or code)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.headers = dict(headers or {})


def not_found(what: str) -> ApiError:
    return ApiError(404, "NOT_FOUND", f"{what} not found")


async def handle_api_error(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, ApiError):  # pragma: no cover - registered for ApiError only
        raise exc
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "status": "error",
            "code": exc.code,
            "message": exc.message,
            "correlation_id": getattr(request.state, "request_id", None),
        },
        headers=exc.headers,
    )
