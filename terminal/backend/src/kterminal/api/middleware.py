"""ASGI middleware: request IDs, correlation context and access logging."""

import re
import time

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from kterminal.core.ids import uuid7
from kterminal.observability.context import correlation_scope
from kterminal.observability.logging import get_logger

REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_HEADER_KEY = REQUEST_ID_HEADER.lower().encode("latin-1")
# Client-supplied IDs are accepted only in a safe, bounded format (they end up in logs).
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")

_log = get_logger("kterminal.api.access")


class RequestContextMiddleware:
    """Binds a correlation ID to every request, echoes it as ``X-Request-ID`` and logs the
    request once it completes (method, path, status, duration — never headers or bodies)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _request_id_from(scope)
        scope.setdefault("state", {})["request_id"] = request_id
        status = 500
        started = time.perf_counter()

        async def send_with_request_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message).append(REQUEST_ID_HEADER, request_id)
            await send(message)

        with correlation_scope(request_id):
            try:
                await self.app(scope, receive, send_with_request_id)
            finally:
                path: str = scope["path"]
                log = _log.debug if path.startswith("/health/") else _log.info
                log(
                    "http.request",
                    method=scope["method"],
                    path=path,
                    status=status,
                    duration_ms=round((time.perf_counter() - started) * 1000, 2),
                    client=(scope.get("client") or ("-",))[0],
                )


def _request_id_from(scope: Scope) -> str:
    headers: list[tuple[bytes, bytes]] = scope["headers"]
    for key, value in headers:
        if key == _REQUEST_ID_HEADER_KEY:
            candidate = value.decode("latin-1")
            if _VALID_REQUEST_ID.fullmatch(candidate):
                return candidate
            break
    return str(uuid7())
