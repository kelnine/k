"""Golden scenarios for Model B (script 2, S4): the 08:00 New York candle swept after 09:00,
a close back inside, a 1m MSS and a displacement FVG arm a resting limit at the FVG edge.

Each test builds a gap-free 1m tape in New York time (``scenario.Tape``): quiet bars
around 100, the 08:00 range high 101 and low 99, and the scripted setup of
``scenario.SETUP`` from 09:00. Every rule of ``SweepModel.run`` and every applied doc 13
decision (limit cancels, window-end expiry, D6 hold and flat, D3 wrong-side levels) is
exercised on known bars.
"""

import math
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest

from kterminal.core.enums import OrderType, SignalAction
from kterminal.domain.signals import Signal
from kterminal.strategies.ict_sweep_models import ARMED, IDLE, IN_TRADE, WAIT_MSS, IctModelB
from kterminal.strategy_engine import CloseReason, PositionEventKind
from kterminal.strategy_engine.testing import StrategyTestResult
from tests.unit.strategies.ict_sweep_models.scenario import (
    ARMED_AT,
    BELOW_RANGE,
    FILLED_AT,
    HOLD,
    RETRACE,
    SETUP,
    TARGET_AT,
    Row,
    Tape,
    mirrored,
    ny,
    run_1m,
)
from tests.unit.strategies.pine_port_support import dumps, of_kind, real_catalog, strategy_object

LONG, SHORT = SignalAction.LONG, SignalAction.SHORT
EXIT_LONG, EXIT_SHORT = SignalAction.EXIT_LONG, SignalAction.EXIT_SHORT
NO_TRADE = SignalAction.NO_TRADE

DAY = date(2026, 1, 6)  # a Tuesday in winter (New York = UTC-5)
RANGE_HIGH: Row = (100.0, 101.0, 99.85, 100.1)  # 08:20
RANGE_LOW: Row = (100.0, 100.15, 99.0, 99.9)  # 08:40


def tape_for(
    day: date = DAY,
    window: tuple[Row, ...] = (*SETUP, *RETRACE),
    *,
    until: str = "12:30",
    short: bool = False,
    symbol: str = "XAUUSD",
) -> Tape:
    """07:00-``until`` New York: the 08:00 range (101 / 99) and ``window`` from 09:00."""
    flip = mirrored if short else (lambda row: row)
    tape = Tape(ny(day, "07:00"), symbol=symbol)
    tape.at(ny(day, "08:20"), flip(RANGE_HIGH))
    tape.at(ny(day, "08:40"), flip(RANGE_LOW))
    tape.at(ny(day, "09:00"), *(flip(row) for row in window))
    tape.quiet_until(ny(day, until))
    return tape


def minute(tape: Tape, signal: Signal, day: date = DAY) -> int:
    """Minutes after that day's 09:00 New York of the signal's bar."""
    assert signal.bar_time is not None
    return tape.index(signal.bar_time) - tape.index(ny(day, "09:00"))


def b(tape: Tape, params: dict[str, Any] | None = None, **kwargs: Any) -> StrategyTestResult:
    result = run_1m(IctModelB, tape.bars(), params=params, **kwargs)
    assert result.fault is None and result.rejected == []
    return result


@pytest.mark.parametrize(
    "day",
    [DAY, date(2026, 3, 9), date(2026, 7, 7)],
    ids=["winter-EST", "first-EDT-monday", "summer-EDT"],
)
def test_long_setup_arms_a_limit_at_the_fvg_edge_fills_and_takes_profit(day: date) -> None:
    tape = tape_for(day)
    result = b(tape)
    (signal,) = result.signals
    assert signal.bar_time == ny(day, "09:08")  # New York time, whatever the UTC offset
    assert (signal.signal, signal.order_type) == (LONG, OrderType.LIMIT)
    assert (signal.entry, signal.stop_loss, signal.take_profit) == (
        Decimal("99.60"),
        Decimal("98.50"),
        Decimal("101.00"),
    )
    assert signal.expires_after_bars == 171  # 09:09 … 11:59: the window's remaining bars
    meta = signal.metadata
    assert (meta["trigger"], meta["pine_signal"], meta["ev"]) == ("B long setup", "evB", 1)
    assert (meta["range_high"], meta["range_low"], meta["swept"]) == (101.0, 99.0, "low")
    assert (meta["sweep_extreme"], meta["mss_level"], meta["back_in"]) == (98.5, 100.6, True)
    assert (meta["fvg_top"], meta["fvg_bottom"], meta["target_kind"]) == (
        99.6,
        99.3,
        "Opposite level",
    )
    assert meta["range_start"] == ny(day, "08:00").isoformat() and meta["range_bars"] == 60
    first = signal.metadata["bar_index"]
    assert isinstance(first, int)
    assert meta["sweep_bar_index"] == first - 3 and meta["mss_bar_index"] == first - 1
    assert meta["fvg_bar_index"] == first - 1 and meta["mss_pivot_bar_index"] == first - 6

    opened = of_kind(result, PositionEventKind.OPENED)
    closed = of_kind(result, PositionEventKind.CLOSED)
    assert [(e.time, e.price) for e in opened] == [
        (ny(day, "09:00") + timedelta(minutes=FILLED_AT), Decimal("99.60"))
    ]
    assert [(e.reason, e.price) for e in closed] == [(CloseReason.TAKE_PROFIT, Decimal("101.00"))]
    assert closed[0].time == ny(day, "09:00") + timedelta(minutes=TARGET_AT + 1)


def test_short_setup_mirrors_the_long_one() -> None:
    tape = tape_for(short=True)
    result = b(tape)
    (signal,) = result.signals
    assert (minute(tape, signal), signal.signal, signal.order_type) == (
        ARMED_AT,
        SHORT,
        OrderType.LIMIT,
    )
    assert (signal.entry, signal.stop_loss, signal.take_profit) == (
        Decimal("100.40"),
        Decimal("101.50"),
        Decimal("99.00"),
    )
    assert (signal.metadata["trigger"], signal.metadata["swept"]) == ("B short setup", "high")
    closed = of_kind(result, PositionEventKind.CLOSED)
    assert [(e.reason, e.price) for e in closed] == [(CloseReason.TAKE_PROFIT, Decimal("99.00"))]


def test_no_setup_before_the_window_or_without_a_range() -> None:
    # the same setup at 08:30 sweeps nothing: the window has not started
    early = Tape(ny(DAY, "07:00")).at(ny(DAY, "08:30"), *SETUP, *RETRACE)
    early.quiet_until(ny(DAY, "12:30"))
    assert b(early).signals == []
    # the range must be < 24 h old: with no bars from 07:00 to 09:00 on the next day,
    # the range of the day before (25 h old at 09:00) is stale and B idles (L796)
    next_day = DAY + timedelta(days=1)
    stale = tape_for(window=(), until="07:00")
    stale.quiet_until(ny(next_day, "07:00"))
    today = Tape(ny(next_day, "09:00")).at(ny(next_day, "09:00"), *SETUP, *RETRACE)
    today.quiet_until(ny(next_day, "12:30"))
    result = run_1m(IctModelB, stale.bars() + today.bars())
    assert result.fault is None and result.signals == []
    model = strategy_object(result)._model
    assert model.state == IDLE and math.isnan(model.hi)  # na levels: idle all window


def test_a_close_back_inside_is_required() -> None:
    """The MSS level (a pivot high at 98.3) sits below the range low: the MSS and the FVG
    happen with every close below 99, so Model B waits; the first close back above 99
    arms the setup (needBack, L559). The engine tests run the same tape without the
    close-back rule (Model A), which arms two bars earlier."""
    tape = tape_for(window=BELOW_RANGE)
    result = b(tape)
    (signal,) = result.signals
    assert minute(tape, signal) == 11
    assert (signal.entry, signal.stop_loss) == (Decimal("97.90"), Decimal("97.50"))
    assert signal.metadata["mss_level"] == 98.3 and signal.metadata["back_in"] is True


def test_target_falls_back_to_the_fixed_rr_when_the_opposite_level_is_too_close() -> None:
    # minRR 1.5: the range high (1.4 above 99.6) is closer than 1.5 × 1.1 → 99.6 + 2 × 1.1
    result = b(tape_for(), {"min_rr": 1.5})
    (signal,) = result.signals
    assert signal.take_profit == Decimal("101.80")
    assert signal.metadata["target_kind"] == "Fixed RR"
    # Fixed RR target mode always uses bRR
    fixed = b(tape_for(), {"b_tgt": "Fixed RR", "b_rr": 3.0}).signals[0]
    assert fixed.take_profit == Decimal("102.90")


def test_ce_entry_and_stop_buffer() -> None:
    result = b(tape_for(), {"entry_mode": "FVG 50% (CE)", "sl_buf_ticks": 10})
    signal, cancel = result.signals
    assert signal.entry == Decimal("99.45")  # (99.6 + 99.3) / 2
    assert signal.stop_loss == Decimal("98.40")  # 98.5 - 10 × 0.01
    # the retrace (low 99.5) stops short of the CE: the target trades first → missed
    assert (cancel.signal, cancel.metadata["trigger"]) == (EXIT_LONG, "B missed")


def test_target_traded_before_the_fill_cancels_the_limit_as_missed() -> None:
    rally: tuple[Row, ...] = (
        (100.5, 100.8, 100.4, 100.7),  # +9
        (100.7, 101.05, 100.6, 100.9),  # +10 reaches 101 before any retrace
        (100.9, 101.0, 99.0, 99.2),  # +11 would have filled
    )
    tape = tape_for(window=(*SETUP, *rally))
    result = b(tape)
    entry, cancel = result.signals
    assert (minute(tape, entry), entry.signal) == (ARMED_AT, LONG)
    assert (minute(tape, cancel), cancel.signal) == (10, EXIT_LONG)
    assert cancel.metadata["trigger"] == "B missed"
    assert cancel.reason == "Model B: target traded before the fill"
    assert of_kind(result, PositionEventKind.OPENED) == []
    model = strategy_object(result)._model
    assert model.state == IDLE  # one cycle per window: nothing more until tomorrow


def test_an_unfilled_limit_expires_with_the_windows_last_bar() -> None:
    away: tuple[Row, ...] = ((100.5, 100.6, 100.0, 100.2),)  # never back to 99.6
    tape = tape_for(window=(*SETUP, *away))
    result = b(tape)
    assert [s.signal for s in result.signals] == [LONG]  # no EXIT needed
    (expired,) = of_kind(result, PositionEventKind.ORDER_EXPIRED)
    assert expired.time == ny(DAY, "12:00")  # the close of the 11:59 bar
    assert strategy_object(result)._model.state == IDLE


def test_limit_left_resting_by_a_missing_last_bar_is_cancelled_after_the_window() -> None:
    """With the 11:58 and 11:59 bars missing the expiry (counted in bars) would outlive
    the window; the script drops the setup on the first bar outside it, so the strategy
    cancels the order there — before the book can fill it on a later bar."""
    tape = tape_for(window=(*SETUP, (100.5, 100.6, 100.0, 100.2)), until="12:10")
    bars = [bar for bar in tape.bars() if bar.open_time not in (ny(DAY, "11:58"), ny(DAY, "11:59"))]
    result = run_1m(IctModelB, bars)
    _, cancel = result.signals
    assert cancel.signal is EXIT_LONG and cancel.bar_time == ny(DAY, "12:00")
    assert cancel.metadata["trigger"] == "window end"
    assert of_kind(result, PositionEventKind.ORDER_EXPIRED) == []


def test_late_fill_after_a_missing_last_bar_is_closed_at_the_next_open() -> None:
    """The 11:58 and 11:59 bars are missing and the 12:00 bar trades through the limit:
    the book still holds the order and fills it, the script has already dropped the
    setup, so the strategy closes the position at the next open."""
    tape = tape_for(window=(*SETUP, (100.5, 100.6, 100.0, 100.2)), until="11:58")
    after = Tape(ny(DAY, "12:00"))
    after.rows = [(100.0, 100.1, 99.5, 99.8), (99.8, 99.9, 99.7, 99.8)]  # 12:00 trades 99.6
    result = run_1m(IctModelB, tape.bars() + after.bars())
    assert result.fault is None
    (opened,) = of_kind(result, PositionEventKind.OPENED)
    assert opened.time == ny(DAY, "12:00")  # the book still had the order
    exits = [s for s in result.signals if s.signal is EXIT_LONG]
    assert [(s.bar_time, s.metadata["trigger"]) for s in exits] == [(ny(DAY, "12:00"), "late fill")]
    (closed,) = of_kind(result, PositionEventKind.CLOSED)
    assert (closed.reason, closed.time) == (CloseReason.SESSION_CLOSE, ny(DAY, "12:01"))


def test_armed_on_the_last_window_bar_places_no_order() -> None:
    tape = Tape(ny(DAY, "07:00"))
    tape.at(ny(DAY, "08:20"), RANGE_HIGH).at(ny(DAY, "08:40"), RANGE_LOW)
    tape.at(ny(DAY, "11:51"), *SETUP, *RETRACE)  # +8 = 11:59, the window's last bar
    tape.quiet_until(ny(DAY, "12:30"))
    result = b(tape)
    (signal,) = result.signals
    assert (signal.signal, signal.reason, signal.persist) == (
        NO_TRADE,
        "ARMED_ON_LAST_WINDOW_BAR",
        True,
    )
    assert signal.metadata["trigger"] == "B long setup" and signal.metadata["script_entry"] == 99.6
    assert of_kind(result, PositionEventKind.OPENED) == []


def test_a_stop_on_the_wrong_side_after_rounding_is_not_traded() -> None:
    """CE entry of a one-tick gap over a zero-range first candle at the sweep extreme:
    (98.51 + 98.50) / 2 = 98.505 rounds (half even) onto the 98.50 stop (doc 13 D3)."""
    window: tuple[Row, ...] = (
        *SETUP[:5],
        (99.5, 99.6, 98.6, 99.2),  # +5 sweep: low 98.6
        (98.5, 98.5, 98.5, 98.5),  # +6 zero-range candle at the new extreme 98.5
        (98.5, 100.9, 98.5, 100.85),  # +7 displacement, MSS
        (100.8, 100.95, 98.51, 100.5),  # +8 low 98.51: a one-tick FVG over 98.50
    )
    result = b(tape_for(window=window), {"entry_mode": "FVG 50% (CE)"})
    (signal,) = result.signals
    assert (signal.signal, signal.reason) == (NO_TRADE, "STOP_WRONG_SIDE")
    assert signal.metadata["script_entry"] == pytest.approx(98.505)
    assert signal.metadata["script_stop"] == 98.5
    edge = b(tape_for(window=window)).signals[0]  # the FVG edge (98.51) is tradable
    assert (edge.signal, edge.entry, edge.stop_loss) == (LONG, Decimal("98.51"), Decimal("98.50"))


def test_fill_bar_through_the_stop_is_a_loss_and_a_gap_fills_at_the_open() -> None:
    crash: tuple[Row, ...] = ((100.5, 100.6, 100.0, 100.2), (99.0, 99.1, 98.2, 98.4))
    result = b(tape_for(window=(*SETUP, *crash)))
    (opened,) = of_kind(result, PositionEventKind.OPENED)
    (closed,) = of_kind(result, PositionEventKind.CLOSED)
    assert opened.price == Decimal("99.00")  # opened below the 99.60 limit: filled there
    assert (closed.reason, closed.price) == (CloseReason.STOP_LOSS, Decimal("98.50"))
    assert closed.time == ny(DAY, "09:11")  # the fill bar's close
    model = strategy_object(result)._model
    assert model.state == IN_TRADE  # the script booked the loss; idle until tomorrow


def test_hold_closes_the_trade_at_the_next_window_start() -> None:
    """D6 main: a filled trade still open after 12:00 is held overnight and closed at the
    next 09:00 bar (the script's neutral close), filling at 09:01."""
    tape = tape_for(window=(*SETUP, *HOLD))
    next_day = DAY + timedelta(days=1)
    tape.quiet_until(ny(next_day, "09:30"))
    result = b(tape)
    entry, exit_ = result.signals
    assert entry.signal is LONG
    assert (exit_.signal, exit_.bar_time) == (EXIT_LONG, ny(next_day, "09:00"))
    assert exit_.reason == CloseReason.SESSION_CLOSE
    assert (exit_.metadata["trigger"], exit_.metadata["pine_signal"]) == (
        "closed",
        "closeTrade(0)",
    )
    (closed,) = of_kind(result, PositionEventKind.CLOSED)
    assert (closed.reason, closed.time) == (CloseReason.SESSION_CLOSE, ny(next_day, "09:01"))
    # the new day's range is quiet (100.15 / 99.85): the model starts waiting for a sweep
    assert strategy_object(result)._model.state == 0


def test_flat_variant_closes_the_trade_at_the_window_end() -> None:
    tape = tape_for(window=(*SETUP, *HOLD), until="13:00")
    result = b(tape, {"after_window": "flat"})
    _, exit_ = result.signals
    assert (exit_.signal, exit_.bar_time) == (EXIT_LONG, ny(DAY, "11:59"))
    assert exit_.reason == CloseReason.SESSION_CLOSE and exit_.metadata["trigger"] == "window end"
    (closed,) = of_kind(result, PositionEventKind.CLOSED)
    assert (closed.reason, closed.time) == (CloseReason.SESSION_CLOSE, ny(DAY, "12:00"))


def test_a_new_extreme_restarts_the_mss_search() -> None:
    """After the MSS and the FVG, a lower low before arming (here a close back inside is
    still missing) moves the stop down and drops the FVG: the setup arms on the next
    displacement FVG only (L520-538)."""
    window: tuple[Row, ...] = (
        *SETUP[:5],
        (99.5, 99.6, 98.5, 98.8),  # +5 sweep, close 98.8 (not back in)
        (98.8, 98.9, 98.6, 98.85),  # +6 gap candle 1 (high 98.9)
        (98.85, 100.7, 98.8, 98.95),  # +7 MSS needs close > 100.6: not yet
        (98.95, 99.0, 98.2, 98.3),  # +8 new extreme 98.2: restarts
        (98.3, 98.35, 98.25, 98.3),  # +9 gap candle 1 (high 98.35)
        (98.3, 100.9, 98.3, 100.85),  # +10 displacement, MSS (close > 100.6), back in
        (100.8, 100.95, 98.6, 100.5),  # +11 low 98.6 > 98.35: FVG 98.35-98.6 → armed
    )
    result = b(tape_for(window=window))
    (signal,) = result.signals
    assert (signal.entry, signal.stop_loss) == (Decimal("98.60"), Decimal("98.20"))
    assert signal.metadata["sweep_extreme"] == 98.2


def test_sweeping_the_other_side_before_arming_flips_the_setup() -> None:
    window: tuple[Row, ...] = (
        (100.0, 100.15, 98.8, 99.0),  # 09:00 sweeps the low: long setup
        (99.2, 101.2, 99.1, 101.1),  # 09:01 sweeps the high: flips to a short setup
    )
    tape = tape_for(window=window, until="09:30")
    result = b(tape)
    model = strategy_object(result)._model
    assert (model.dir, model.ext, model.state) == (-1, 101.2, WAIT_MSS)


def test_an_outside_bar_sweeping_both_sides_becomes_a_long_setup() -> None:
    tape = tape_for(window=((100.0, 101.3, 98.7, 100.0),), until="09:30")
    model = strategy_object(b(tape))._model
    assert (model.dir, model.ext) == (1, 98.7)  # the low check runs second (L529-538)


def test_no_new_fvg_more_than_three_bars_after_the_mss() -> None:
    """The MSS happens at +6 without a gap; a displacement FVG whose middle candle is
    5 bars after it is ignored (L544), so the setup stalls in state 1."""
    window: tuple[Row, ...] = (
        *SETUP[:5],
        (99.5, 99.6, 98.5, 99.2),  # +5 sweep
        (99.2, 100.7, 99.1, 100.65),  # +6 MSS (close > 100.6)
        (100.65, 100.7, 99.5, 99.7),  # +7 low 99.5 <= 99.6: no gap after the MSS candle
        (99.7, 99.8, 99.6, 99.75),  # +8
        (99.75, 99.8, 99.65, 99.7),  # +9
        (99.7, 99.75, 99.6, 99.7),  # +10 gap candle 1 (high 99.75)
        (99.7, 100.95, 99.65, 100.9),  # +11 displacement: middle candle 5 bars after the MSS
        (100.9, 100.95, 100.0, 100.8),  # +12 FVG 99.75-100.0: too late
    )
    result = b(tape_for(window=window, until="09:30"))
    assert result.signals == []
    model = strategy_object(result)._model
    assert (model.state, model.mss) == (WAIT_MSS, True)
    assert math.isnan(model.fvg_top)  # na: never recorded


def test_a_close_below_the_fvg_drops_it() -> None:
    """Without the close back inside the FVG waits; a close below its bottom kills it."""
    window: tuple[Row, ...] = (
        *SETUP[:5],
        (99.5, 99.6, 98.5, 98.7),  # +5 sweep, close 98.7 (not back in)
        (98.7, 98.75, 98.6, 98.7),  # +6 gap candle 1 (high 98.75)
        (98.62, 98.98, 98.6, 98.97),  # +7 displacement (no MSS: 100.6 far)
        (98.97, 98.99, 98.8, 98.9),  # +8 low 98.8 > 98.75: FVG 98.75-98.8
        (98.9, 98.95, 98.6, 98.7),  # +9 close 98.7 < 98.75: dropped
    )
    model = strategy_object(b(tape_for(window=window[:-1], until="09:09")))._model
    assert (model.state, model.fvg_top, model.fvg_bot) == (WAIT_MSS, 98.8, 98.75)
    model = strategy_object(b(tape_for(window=window, until="09:30")))._model
    assert model.state == WAIT_MSS and math.isnan(model.fvg_top)


def test_window_and_range_on_a_sunday_for_crypto() -> None:
    """ALL_DAYS (L27): the window runs on Sundays; BTCUSD trades through the weekend."""
    btc = real_catalog().instrument("BTCUSD")
    sunday = date(2026, 1, 4)
    tape = tape_for(sunday, symbol="BTCUSD")
    result = run_1m(IctModelB, tape.bars(), instrument=btc)
    assert result.fault is None
    assert [(s.signal, s.bar_time) for s in result.signals] == [(LONG, ny(sunday, "09:08"))]


def test_armed_state_is_visible_on_the_strategy() -> None:
    tape = tape_for(window=SETUP, until="09:09")
    model = strategy_object(b(tape))._model
    assert (model.state, model.entry, model.sl, model.tp) == (ARMED, 99.6, 98.5, 101.0)


def test_runs_are_deterministic() -> None:
    tape = tape_for(window=(*SETUP, *HOLD))
    tape.quiet_until(ny(DAY + timedelta(days=1), "10:00"))
    for params in ({}, {"after_window": "flat"}):
        assert dumps(b(tape, params)) == dumps(b(tape, params))


def ce_window(gap_bottom: float, *after: Row) -> tuple[Row, ...]:
    """The golden setup with the gap's first candle topping at ``gap_bottom``."""
    return (*SETUP[:6], (99.2, gap_bottom, 99.1, 99.25), *SETUP[7:], *after)


CE = {"entry_mode": "FVG 50% (CE)"}


def test_a_ce_limit_rounded_towards_the_market_keeps_its_early_fill() -> None:
    """CE (99.6 + 99.31) / 2 = 99.455 is ordered at 99.46: the book fills on a low of
    99.46 a bar before the script would (99.40); the trade is kept."""
    early = (100.5, 100.6, 99.46, 100.2)
    later = (100.2, 100.3, 99.4, 99.8)
    result = b(tape_for(window=ce_window(99.31, early, later)), CE)
    (signal,) = result.signals
    assert (signal.entry, signal.metadata["script_entry"]) == (Decimal("99.46"), 99.455)
    (opened,) = of_kind(result, PositionEventKind.OPENED)
    assert (opened.time, opened.price) == (ny(DAY, "09:09"), Decimal("99.46"))
    assert of_kind(result, PositionEventKind.CLOSED) == []


def test_a_rounded_fill_on_the_bar_the_script_misses_is_closed() -> None:
    """The same order fills on a bar that also reaches the 101 target: the script calls
    the setup missed (it never filled at 99.455), so the book's trade is closed."""
    both = (100.5, 101.05, 99.46, 100.5)
    result = b(tape_for(window=ce_window(99.31, both)), CE)
    _, exit_ = result.signals
    assert (exit_.signal, exit_.bar_time, exit_.metadata["trigger"]) == (
        EXIT_LONG,
        ny(DAY, "09:09"),
        "late fill",
    )
    (closed,) = of_kind(result, PositionEventKind.CLOSED)
    assert (closed.reason, closed.time) == (CloseReason.SESSION_CLOSE, ny(DAY, "09:10"))


def test_a_script_fill_the_book_cannot_match_cancels_the_order() -> None:
    """CE 99.445 is ordered at 99.44; a bar trading off the tick grid down to 99.443
    fills the script but not the book, so the resting order is cancelled."""
    off_grid = (100.5, 100.6, 99.443, 100.2)
    result = b(tape_for(window=ce_window(99.29, off_grid)), CE)
    entry, cancel = result.signals
    assert entry.entry == Decimal("99.44")
    assert (cancel.signal, cancel.metadata["trigger"]) == (EXIT_LONG, "fill not matched")
    assert of_kind(result, PositionEventKind.OPENED) == []
    assert strategy_object(result)._model.state == IN_TRADE
