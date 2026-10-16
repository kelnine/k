"""Injected time.

Components never call ``datetime.now()`` directly: they receive a
:class:`Clock`. Live processes use :class:`SystemClock`; backtests drive a
:class:`SimulatedClock` bar by bar, which is what makes a backtest
deterministic and lets the exact same code run in both.
"""

from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable

from kterminal.core.errors import ClockError


def ensure_utc(value: datetime) -> datetime:
    """Return ``value`` converted to UTC; reject naive datetimes outright."""
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ClockError(f"naive datetime not allowed (timezone required): {value!r}")
    return value.astimezone(UTC)


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime:
        """Current time as a timezone-aware UTC datetime."""
        ...


class SystemClock:
    """Wall-clock time (UTC)."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class SimulatedClock:
    """Manually driven clock for backtests and tests. Time never moves backwards."""

    def __init__(self, start: datetime) -> None:
        self._now = ensure_utc(start)

    def now(self) -> datetime:
        return self._now

    def set(self, value: datetime) -> None:
        value = ensure_utc(value)
        if value < self._now:
            raise ClockError(
                f"time cannot move backwards: {value.isoformat()} < {self._now.isoformat()}"
            )
        self._now = value

    def advance(self, delta: timedelta) -> datetime:
        if delta < timedelta(0):
            raise ClockError(f"cannot advance by a negative duration: {delta}")
        self._now += delta
        return self._now
