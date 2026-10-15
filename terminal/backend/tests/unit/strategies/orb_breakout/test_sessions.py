"""Session windows by bar OPEN time in the script's time zone, DST-correct: New York
across both US clock changes, and the London variant while the US and UK clocks
disagree (March 2026: US on 8 March, UK on 29 March)."""

from datetime import UTC, date, datetime

import pytest

from kterminal.core.enums import SignalAction
from kterminal.strategy_engine import CloseReason, PositionEventKind
from tests.unit.strategies.orb_breakout.helpers import (
    LONDON,
    at,
    day_bars,
    run,
)
from tests.unit.strategies.orb_breakout.test_rules import NO_FILTER, OR_ROWS
from tests.unit.strategies.pine_port_support import entries, of_kind

LONG_0945 = {**OR_ROWS, "09:45": (100, 101.8, 99.9, 101.6)}
LONDON_PARAMS = {
    **NO_FILTER,
    "timezone": LONDON,
    "or_session": "0800-0815",
    "levels_session": "0800-1630",
    "flatten_time": "16:30",
}
LONDON_ROWS: dict[str, tuple[float, float, float, float] | float] = {
    "07:55": (100, 105, 95, 100),
    "08:00": (100, 101, 99.5, 100.5),
    "08:05": (100.5, 101.5, 100, 101),
    "08:10": (101, 101.2, 99, 100),
    "08:15": (100, 101.8, 99.9, 101.6),
}


def utc(signal_time: datetime | None) -> str:
    assert signal_time is not None
    return signal_time.astimezone(UTC).strftime("%H:%M")


@pytest.mark.parametrize(
    ("day", "signal_utc", "flatten_utc"),
    [
        (date(2026, 3, 6), "14:45", "20:55"),  # Friday before the US change: EST (UTC-5)
        (date(2026, 3, 9), "13:45", "19:55"),  # Monday after it: EDT (UTC-4)
        (date(2026, 7, 15), "13:45", "19:55"),  # summer
        (date(2026, 10, 30), "13:45", "19:55"),  # Friday before the fall back
        (date(2026, 11, 2), "14:45", "20:55"),  # Monday after it: EST again
    ],
)
def test_new_york_windows_follow_the_us_clock(day: date, signal_utc: str, flatten_utc: str) -> None:
    result = run(day_bars(day, LONG_0945), params=NO_FILTER)
    [signal] = entries(result)
    assert utc(signal.bar_time) == signal_utc  # 09:45 New York
    assert signal.metadata["or_high"] == 101.5  # 09:30-09:40 New York, whatever UTC says
    [exit_signal] = [s for s in result.signals if s.signal.is_flatten]
    assert utc(exit_signal.bar_time) == flatten_utc  # 15:55 New York
    assert signal.metadata["flatten_at"] == (
        exit_signal.timestamp.isoformat()  # the flatten bar closes at 16:00 New York
    )


@pytest.mark.parametrize(
    ("day", "signal_utc", "flatten_utc"),
    [
        (date(2026, 3, 16), "08:15", "16:25"),  # US already on EDT, UK still on GMT
        (date(2026, 3, 30), "07:15", "15:25"),  # UK on BST
    ],
)
def test_london_variant_follows_the_uk_clock(day: date, signal_utc: str, flatten_utc: str) -> None:
    bars = day_bars(day, LONDON_ROWS, start="06:00", end="18:00", tz=LONDON)
    result = run(bars, params=LONDON_PARAMS)
    [signal] = entries(result)
    assert at([signal], tz=LONDON) == [("08:15", SignalAction.LONG)]
    assert utc(signal.bar_time) == signal_utc
    assert signal.metadata["or_high"] == 101.5
    assert signal.metadata["or_low"] == 99.0
    [exit_signal] = [s for s in result.signals if s.signal.is_flatten]
    assert at([exit_signal], tz=LONDON) == [("16:25", SignalAction.FLATTEN)]
    assert utc(exit_signal.bar_time) == flatten_utc
    [closed] = of_kind(result, PositionEventKind.CLOSED)
    assert closed.reason is CloseReason.SESSION_CLOSE


def test_london_variant_ignores_the_new_york_window() -> None:
    # A New York-time range and breakout means nothing to the London instance.
    bars = day_bars(date(2026, 3, 16), LONG_0945, start="06:00", end="18:00")
    assert entries(run(bars, params=LONDON_PARAMS)) == []


def test_sessions_apply_on_every_day_like_the_script() -> None:
    # The session strings carry no day mask (Pine v5+: all seven days), so a weekend
    # with bars (crypto) forms a range and signals too.
    saturday = date(2026, 1, 10)
    result = run(day_bars(saturday, LONG_0945, symbol="BTCUSD"), params=NO_FILTER, symbol="BTCUSD")
    assert at(entries(result)) == [("09:45", SignalAction.LONG)]


def test_a_day_mask_restricts_the_windows() -> None:
    saturday = date(2026, 1, 10)
    params = {**NO_FILTER, "or_session": "0930-0945:23456", "levels_session": "0930-1600:23456"}
    result = run(day_bars(saturday, LONG_0945, symbol="BTCUSD"), params=params, symbol="BTCUSD")
    assert entries(result) == []
