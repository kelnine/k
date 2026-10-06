"""Domain events and the in-process event bus.

Modules announce what happened (``TradeOpened``, ``RiskRejected``,
``KillSwitchActivated`` …) by publishing immutable events; interested modules
(notifications, analytics, the dashboard push channel) subscribe. Publishers
never know who listens, which is what lets a module be added or removed
without touching the others.

The bus is in-process and deterministic: handlers run sequentially in
subscription order, so a backtest produces identical side effects on every
run. A failing handler is isolated — it is reported and never breaks the
publisher or the remaining handlers. Events that must reach another process
are additionally written to the database outbox in the same transaction as
the state change (Phase 2).
"""

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Protocol, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from kterminal.core.clock import ensure_utc
from kterminal.core.ids import uuid7

_log = logging.getLogger(__name__)


class DomainEvent(BaseModel):
    """Base class for all domain events. Subclasses add their own fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: UUID = Field(default_factory=uuid7)
    occurred_at: datetime  # taken from the injected Clock, never implicitly from the wall clock
    correlation_id: UUID | None = None

    @field_validator("occurred_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    @property
    def event_type(self) -> str:
        return type(self).__name__


E = TypeVar("E", bound=DomainEvent)
Handler = Callable[[E], Awaitable[None]]
ErrorHook = Callable[[DomainEvent, Callable[..., Awaitable[None]], Exception], None]


class Subscription:
    """Handle returned by :meth:`EventBus.subscribe`; call :meth:`cancel` to unsubscribe."""

    def __init__(self, cancel: Callable[[], None]) -> None:
        self._cancel = cancel
        self._active = True

    @property
    def active(self) -> bool:
        return self._active

    def cancel(self) -> None:
        if self._active:
            self._cancel()
            self._active = False


class EventBus(Protocol):
    def subscribe(self, event_type: type[E], handler: Handler[E]) -> Subscription:
        """Call ``handler`` for every published event that is an instance of ``event_type``."""
        ...

    async def publish(self, event: DomainEvent) -> None:
        """Deliver ``event`` to all matching handlers."""
        ...


def _log_handler_error(
    event: DomainEvent, handler: Callable[..., Awaitable[None]], exc: Exception
) -> None:
    _log.error(
        "event handler failed",
        exc_info=exc,
        extra={
            "event_type": event.event_type,
            "event_id": str(event.event_id),
            "handler": getattr(handler, "__qualname__", repr(handler)),
        },
    )


class InMemoryEventBus:
    """Sequential, deterministic, failure-isolated in-process event bus."""

    def __init__(self, on_error: ErrorHook | None = None) -> None:
        self._handlers: list[tuple[type[DomainEvent], Callable[..., Awaitable[None]]]] = []
        self._on_error = on_error or _log_handler_error

    def subscribe(self, event_type: type[E], handler: Handler[E]) -> Subscription:
        entry: tuple[type[DomainEvent], Callable[..., Awaitable[None]]] = (event_type, handler)
        self._handlers.append(entry)
        return Subscription(lambda: self._handlers.remove(entry))

    async def publish(self, event: DomainEvent) -> None:
        # Snapshot so handlers may (un)subscribe while an event is being delivered.
        for event_type, handler in list(self._handlers):
            if not isinstance(event, event_type):
                continue
            try:
                await handler(event)
            except Exception as exc:  # isolation: one bad subscriber must not stop trading
                self._on_error(event, handler, exc)

    @property
    def subscriber_count(self) -> int:
        return len(self._handlers)
