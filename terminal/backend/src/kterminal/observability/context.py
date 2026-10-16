"""Correlation-ID propagation.

A correlation ID is bound at the edge (an HTTP request, a closed bar, a
scheduled job) and automatically attached to every log line emitted while
handling it — across ``await`` points, because it lives in a ``ContextVar``.
The same ID is stored on every database row the event causes, so logs and
records can be joined.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

import structlog

from kterminal.core.ids import new_correlation_id

CORRELATION_ID_KEY = "correlation_id"


def get_correlation_id() -> str | None:
    value = structlog.contextvars.get_contextvars().get(CORRELATION_ID_KEY)
    return str(value) if value is not None else None


@contextmanager
def correlation_scope(correlation_id: str | UUID | None = None, **extra: object) -> Iterator[str]:
    """Bind a correlation ID (new if not given) plus extra fields for the enclosed block."""
    cid = str(correlation_id or new_correlation_id())
    with structlog.contextvars.bound_contextvars(**{CORRELATION_ID_KEY: cid}, **extra):
        yield cid
