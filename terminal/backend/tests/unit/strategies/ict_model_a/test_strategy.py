"""Golden scenarios for Model A (script 2, S5): after 20:00 New York a sweep of the most
recent untaken 15m swing high or low, a 1m MSS and a displacement FVG arm a resting limit.

The 15m swing levels come from ``f_liqSwings(2)`` through ``request.security(...,
lookahead_on)`` (L616): the tapes put a 15m pivot high of 101 at the 15:00 bar and a pivot
low of 99 at the 16:00 bar (1m spikes at 15:07 and 16:07), then run ``scenario.SETUP`` at
20:00. The 15m bars are the lab aggregator's (``scenario.with_15m``).
"""

import math
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest

from kterminal.core.enums import OrderType, SignalAction
from kterminal.strategies.ict_sweep_models import IDLE, WAIT_SWEEP, IctModelA
from kterminal.strategy_engine import CloseReason, PositionEventKind
from kterminal.strategy_engine.testing import StrategyTestResult
from tests.unit.strategies.ict_sweep_models.scenario import (
    ARMED_AT,
    BELOW_RANGE,
    HOLD,
    RETRACE,
    SETUP,
    TARGET_AT,
    Row,
    Tape,
    mirrored,
    ny,
    run_1m,
    with_15m,
)
from tests.unit.strategies.pine_port_support import dumps, of_kind, real_catalog, strategy_object

LONG, SHORT = SignalAction.LONG, SignalAction.SHORT
EXIT_LONG = SignalAction.EXIT_LONG
FLATTEN = SignalAction.FLATTEN

DAY = date(2026, 1, 6)  # a Tuesday in winter (New York = UTC-5)
SWING_HIGH: Row = (100.0, 101.0, 99.85, 100.1)  # a 1m spike making the 15m pivot high
SWING_LOW: Row = (100.0, 100.15, 99.0, 99.9)


def tape_for(
    day: date = DAY,
    window: tuple[Row, ...] = (*SETUP, *RETRACE),
    *,
    until: str = "21:00",
    days: int = 0,
    short: bool = False,
    extra: tuple[tuple[str, Row], ...] = (),
    symbol: str = "XAUUSD",
    window_at: str = "20:00",
) -> Tape:
    """14:00 New York to ``until`` ``days`` later: 15m swing levels 101 / 99, optional
    ``extra`` scripted bars, and ``window`` from ``window_at``."""
    flip = mirrored if short else (lambda row: row)
    tape = Tape(ny(day, "14:00"), symbol=symbol)
    scripted = sorted((("15:07", SWING_HIGH), ("16:07", SWING_LOW), *extra))
    for hhmm, row in scripted:
        tape.at(ny(day, hhmm), flip(row))
    tape.at(ny(day, window_at), *(flip(row) for row in window))
    tape.quiet_until(ny(day + timedelta(days=days), until))
    return tape


def a(tape: Tape, params: dict[str, Any] | None = None, **kwargs: Any) -> StrategyTestResult:
    result = run_1m(IctModelA, with_15m(tape.bars()), params=params, **kwargs)
    assert result.fault is None and result.rejected == []
    return result


@pytest.mark.parametrize("short", [False, True], ids=["long", "short"])
def test_sweep_of_a_15m_swing_arms_a_limit_and_takes_profit(short: bool) -> None:
    tape = tape_for(short=short)
    result = a(tape)
    (signal,) = result.signals
    assert signal.bar_time == ny(DAY, "20:00") + timedelta(minutes=ARMED_AT)
    assert signal.order_type is OrderType.LIMIT
    if short:
        levels = (Decimal("100.40"), Decimal("101.50"), Decimal("99.00"))
        assert signal.signal is SHORT and signal.metadata["trigger"] == "A short setup"
    else:
        levels = (Decimal("99.60"), Decimal("98.50"), Decimal("101.00"))
        assert signal.signal is LONG and signal.metadata["trigger"] == "A long setup"
    assert (signal.entry, signal.stop_loss, signal.take_profit) == levels
    assert signal.expires_after_bars == 351  # 20:09 … 01:59
    meta = signal.metadata
    assert (meta["pine_signal"], meta["range_high"], meta["range_low"]) == ("evA", 101.0, 99.0)
    high_pivot, low_pivot = ("16:00", "15:00") if short else ("15:00", "16:00")
    assert meta["level_high_pivot_time"] == ny(DAY, high_pivot).isoformat()
    assert meta["level_low_pivot_time"] == ny(DAY, low_pivot).isoformat()
    assert meta["levels_from_15m_bar"] == ny(DAY, "19:45").isoformat()
    (closed,) = of_kind(result, PositionEventKind.CLOSED)
    assert closed.reason is CloseReason.TAKE_PROFIT and closed.price == levels[2]
    assert closed.time == ny(DAY, "20:00") + timedelta(minutes=TARGET_AT + 1)


def test_no_close_back_inside_is_needed() -> None:
    """The tape on which Model B waits for a close back inside the range (09:11) arms
    Model A as soon as the MSS and the FVG are there (needBack false, L781)."""
    tape = tape_for(window=BELOW_RANGE)
    (signal,) = a(tape).signals
    assert signal.bar_time == ny(DAY, "20:09")
    assert (signal.entry, signal.stop_loss) == (Decimal("97.90"), Decimal("97.50"))
    assert signal.metadata["back_in"] is False


def test_levels_are_the_most_recent_untaken_swings() -> None:
    # a newer, lower swing high (100.8 at the 17:00 bar) is the level
    newer = (("17:07", (100.0, 100.8, 99.85, 100.1)),)
    model = strategy_object(a(tape_for(window=(), extra=newer)))._model
    assert (model.hi, model.lo, model.state) == (100.8, 99.0, WAIT_SWEEP)
    # the 19:30 bar takes it (100.9 > 100.8) without confirming a new pivot by 20:00:
    # the older survivor (101) is the level again
    taken = (*newer, ("19:37", (100.0, 100.9, 99.85, 100.1)))
    model = strategy_object(a(tape_for(window=(), extra=taken)))._model
    assert (model.hi, model.lo) == (101.0, 99.0)
    # a bar above every swing high leaves none: the model idles that night (L483)
    gone = (("19:37", (100.0, 101.2, 99.85, 100.1)),)
    result = a(tape_for(extra=gone))
    model = strategy_object(result)._model
    assert math.isnan(model.hi) and model.state == IDLE and result.signals == []


def test_levels_follow_tradingview_lookahead_timing() -> None:
    """``request.security(..., lookahead_on)`` with ``[1]``: a 1m bar sees the 15m swings
    as of the previous 15m bar. A pivot high at the 19:15 bar is confirmed by the 19:45
    bar, which is visible from 20:00 — so a window starting at 20:00 uses it, while one
    starting at 19:59 (inside the 19:45 bar) does not yet (docs/05 §5.2.1)."""
    late_pivot = (("19:22", (100.0, 100.9, 99.85, 100.1)),)
    at_20 = strategy_object(a(tape_for(window=(), extra=late_pivot)))._model
    assert at_20.hi == 100.9
    early = a(tape_for(window=(), extra=late_pivot), {"a_win": "1959-0200"})
    assert strategy_object(early)._model.hi == 101.0


def test_the_sweep_can_happen_on_the_first_window_bar() -> None:
    tape = tape_for(window=(*SETUP, *RETRACE), window_at="19:55")  # +5 is 20:00
    (signal,) = a(tape).signals
    assert signal.bar_time == ny(DAY, "20:03")
    bar_index = signal.metadata["bar_index"]
    assert isinstance(bar_index, int) and signal.metadata["sweep_bar_index"] == bar_index - 3


def test_hold_closes_the_trade_at_the_next_20_00() -> None:
    """D6 main: the trade is not closed at 02:00; the next window start closes it."""
    tape = tape_for(window=(*SETUP, *HOLD), until="20:30", days=1)
    result = a(tape)
    _, exit_ = result.signals
    next_day = DAY + timedelta(days=1)
    assert (exit_.signal, exit_.bar_time) == (FLATTEN, ny(next_day, "20:00"))
    assert exit_.reason == CloseReason.SESSION_CLOSE and exit_.metadata["trigger"] == "closed"
    (closed,) = of_kind(result, PositionEventKind.CLOSED)
    assert (closed.reason, closed.time) == (CloseReason.SESSION_CLOSE, ny(next_day, "20:01"))


def test_flat_variant_closes_the_trade_at_02_00() -> None:
    tape = tape_for(window=(*SETUP, *HOLD), until="03:00", days=1)
    result = a(tape, {"after_window": "flat"})
    _, exit_ = result.signals
    next_day = DAY + timedelta(days=1)
    assert (exit_.signal, exit_.bar_time) == (FLATTEN, ny(next_day, "01:59"))
    assert exit_.metadata["trigger"] == "window end"
    (closed,) = of_kind(result, PositionEventKind.CLOSED)
    assert (closed.reason, closed.time) == (CloseReason.SESSION_CLOSE, ny(next_day, "02:00"))


def test_the_window_spans_the_repeated_hour_when_the_clocks_go_back() -> None:
    """2026-11-01: New York falls back at 02:00 EDT to 01:00 EST, so 20:00-02:00 lasts
    seven hours (00:00-07:00 UTC). A limit armed at 01:08 EDT (05:08 UTC) can fill on the
    111 bars up to 07:00 UTC; unfilled, it expires with the 01:59 EST bar."""
    saturday = date(2026, 10, 31)
    btc = real_catalog().instrument("BTCUSD")
    away: tuple[Row, ...] = ((100.5, 100.6, 100.0, 100.2),)
    tape = tape_for(saturday, window=(), until="20:01", symbol="BTCUSD")
    tape.at(ny(date(2026, 11, 1), "01:00"), *SETUP, *away)  # first 01:00: EDT, 05:00 UTC
    tape.quiet_until(ny(date(2026, 11, 1), "09:00"))
    result = a(tape, instrument=btc)
    (signal,) = result.signals
    assert signal.bar_time is not None and signal.bar_time.hour == 5  # 05:08 UTC
    assert signal.expires_after_bars == 111
    (expired,) = of_kind(result, PositionEventKind.ORDER_EXPIRED)
    assert expired.time.hour == 7 and expired.time.minute == 0  # 02:00 EST


def test_runs_are_deterministic() -> None:
    tape = tape_for(window=(*SETUP, *HOLD), until="20:30", days=1)
    for params in ({}, {"after_window": "flat"}):
        assert dumps(a(tape, params)) == dumps(a(tape, params))
