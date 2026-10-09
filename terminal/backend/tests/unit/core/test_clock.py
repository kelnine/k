from datetime import UTC, datetime, timedelta, timezone

import pytest

from kterminal.core.clock import Clock, SimulatedClock, SystemClock, ensure_utc
from kterminal.core.errors import ClockError

T0 = datetime(2026, 10, 5, 14, 30, tzinfo=UTC)


def test_system_clock_is_utc_aware() -> None:
    now = SystemClock().now()
    assert now.tzinfo is UTC


def test_clocks_satisfy_protocol() -> None:
    assert isinstance(SystemClock(), Clock)
    assert isinstance(SimulatedClock(T0), Clock)


def test_ensure_utc_converts_and_rejects_naive() -> None:
    new_york = timezone(timedelta(hours=-4))
    assert ensure_utc(datetime(2026, 10, 5, 10, 30, tzinfo=new_york)) == T0
    with pytest.raises(ClockError, match="naive"):
        ensure_utc(datetime(2026, 10, 5, 14, 30))  # noqa: DTZ001 - deliberately naive


def test_simulated_clock_advances_and_never_goes_back() -> None:
    clock = SimulatedClock(T0)
    assert clock.advance(timedelta(minutes=5)) == T0 + timedelta(minutes=5)
    clock.set(T0 + timedelta(hours=1))
    assert clock.now() == T0 + timedelta(hours=1)
    with pytest.raises(ClockError, match="backwards"):
        clock.set(T0)
    with pytest.raises(ClockError, match="negative"):
        clock.advance(timedelta(seconds=-1))
