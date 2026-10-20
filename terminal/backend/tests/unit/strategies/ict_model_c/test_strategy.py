"""Golden scenarios for Model C (script 2, S9): the 1H PD-array bias picks the side, a 5m
FVG of that side is tapped (around the clock), and in 09:30-12:00 New York a 1m IFVG or a
close beyond the zone's CISD level triggers a market entry.

Each test builds a gap-free 1m tape in New York time (``scenario.long_tape``): the bias
and the draw on liquidity overnight, the zone and its tap from 09:00, the trigger at
09:30. Every rule of L801-830 and every applied doc 13 decision (D3 gap guard and
wrong-side levels, D6 hold and flat, the replace at the next window start) is exercised
on known bars.
"""

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest

from kterminal.core.enums import Direction, SignalAction
from kterminal.domain.signals import Signal
from kterminal.domain.timeframes import H1, M5, M15
from kterminal.strategies.ict_model_c import IctModelC
from kterminal.strategy_engine import CloseReason, PositionEventKind
from kterminal.strategy_engine.testing import StrategyTestResult
from tests.fixtures.instruments import XAUUSD
from tests.unit.strategies.ict_model_c.scenario import (
    EXTREME_AT,
    HOLD,
    IFVG,
    RALLY,
    SPIKE,
    TRIGGER,
    ZONE,
    Row,
    Tape,
    long_tape,
    mirrored,
    ny,
    quiet_row,
    run_1m,
    with_htf,
)
from tests.unit.strategies.pine_port_support import dumps, of_kind, real_catalog, strategy_object

LONG, SHORT = SignalAction.LONG, SignalAction.SHORT
FLATTEN, NO_TRADE = SignalAction.FLATTEN, SignalAction.NO_TRADE

DAY = date(2026, 1, 6)  # a Tuesday in winter (New York = UTC-5)


def c(
    tape: Tape,
    params: dict[str, Any] | None = None,
    *,
    mirror: float | None = None,
    **kwargs: Any,
) -> StrategyTestResult:
    result = run_1m(IctModelC, with_htf(tape.bars(mirror=mirror)), params=params, **kwargs)
    assert result.fault is None and result.rejected == []
    return result


def entries(result: StrategyTestResult) -> list[Signal]:
    return [s for s in result.signals if s.signal.is_entry]


def model(result: StrategyTestResult) -> Any:
    return strategy_object(result)


def shifted(rows: tuple[Row, ...], by: float) -> tuple[Row, ...]:
    return tuple((o + by, h + by, low + by, cl + by) for o, h, low, cl in rows)


@pytest.mark.parametrize(
    "day",
    [DAY, date(2026, 3, 9), date(2026, 7, 7)],
    ids=["winter-EST", "first-EDT-monday", "summer-EDT"],
)
def test_cisd_after_a_tap_before_the_window_goes_long_at_09_30(day: date) -> None:
    """The zone is tapped at 09:20, before the window: the first window bar closes above
    the CISD level (a level test, not a cross) and goes long, stop at the zone extreme,
    target the 1H buy-side liquidity."""
    result = c(long_tape(day))
    (signal,) = result.signals
    assert (signal.signal, signal.bar_time) == (LONG, ny(day, "09:30"))
    assert (signal.entry, signal.stop_loss, signal.take_profit) == (
        Decimal("103.65"),
        Decimal("102.90"),
        Decimal("105.00"),
    )
    meta = signal.metadata
    assert (meta["trigger"], meta["pine_signal"], meta["trade_tag"]) == ("C long", "evC", "C CISD")
    assert (meta["via_cisd"], meta["via_ifvg"], meta["bias"]) == (True, False, 1)
    # every 1h bar since 06:00 wicked into the 1H FVG and held: the 08:00 bar set it last
    assert meta["bias_set_by_bar"] == ny(day, "08:00").isoformat()
    assert meta["bias_from_bar"] == ny(day, "08:00").isoformat()
    zone = meta["zone"]
    assert isinstance(zone, dict)
    assert (zone["top"], zone["bottom"], zone["dir"], zone["tf"]) == (103.35, 102.65, 1, "5m")
    assert zone["first_candle"] == ny(day, "09:00").isoformat()
    assert zone["added"] == ny(day, "09:15").isoformat()
    assert (zone["extreme"], zone["cisd_level"]) == (102.9, 103.6)
    bar_index = meta["bar_index"]
    assert isinstance(bar_index, int)
    assert zone["tap_bar_index"] == bar_index - 10 and zone["extreme_bar_index"] == bar_index - 7
    assert (meta["draw_on_liquidity"], meta["dol_ok"], meta["target_kind"]) == (
        105.0,
        True,
        "Draw on liquidity",
    )
    assert meta["dol_pivot_time"] == ny(day, "05:00").isoformat()
    assert (meta["script_entry"], meta["script_stop"], meta["script_target"]) == (
        103.65,
        102.9,
        105.0,
    )
    assert meta["risk_points"] == pytest.approx(0.75)
    (opened,) = of_kind(result, PositionEventKind.OPENED)
    (closed,) = of_kind(result, PositionEventKind.CLOSED)
    assert (opened.time, opened.price) == (ny(day, "09:31"), Decimal("103.65"))
    assert (closed.reason, closed.price, closed.time) == (
        CloseReason.TAKE_PROFIT,
        Decimal("105.00"),
        ny(day, "09:34"),
    )


def test_short_mirrors_the_long_setup() -> None:
    result = c(long_tape(DAY), mirror=100.0)
    (signal,) = result.signals
    assert (signal.signal, signal.bar_time) == (SHORT, ny(DAY, "09:30"))
    assert (signal.entry, signal.stop_loss, signal.take_profit) == (
        Decimal("96.35"),
        Decimal("97.10"),
        Decimal("95.00"),
    )
    meta = signal.metadata
    assert (meta["trigger"], meta["bias"], meta["trade_tag"]) == ("C short", -1, "C CISD")
    zone = meta["zone"]
    assert isinstance(zone, dict)
    assert (zone["dir"], zone["top"], zone["bottom"], zone["cisd_level"]) == (
        -1,
        97.35,
        96.65,
        96.4,
    )
    assert meta["draw_on_liquidity"] == 95.0  # the 1H sell-side liquidity
    (closed,) = of_kind(result, PositionEventKind.CLOSED)
    assert (closed.reason, closed.price) == (CloseReason.TAKE_PROFIT, Decimal("95.00"))


def test_an_inverted_1m_gap_triggers_below_the_cisd_level() -> None:
    """A bearish 1m gap formed after the tap is closed through (bullish IFVG) at 09:33;
    the CISD level 103.6 is never reached."""
    tape = long_tape(DAY, IFVG)
    (signal,) = c(tape).signals
    assert (signal.signal, signal.bar_time) == (LONG, ny(DAY, "09:33"))
    assert (signal.entry, signal.stop_loss, signal.take_profit) == (
        Decimal("103.10"),
        Decimal("102.90"),
        Decimal("105.00"),
    )
    meta = signal.metadata
    assert (meta["via_ifvg"], meta["via_cisd"], meta["trade_tag"]) == (True, False, "C IFVG")
    bar_index = meta["bar_index"]
    assert isinstance(bar_index, int)
    assert meta["inverted_gap_bar_index"] == bar_index - 2  # the gap's middle candle
    assert meta["inverted_gap_levels"] == [103.05]
    # the trigger option switches either trigger off
    assert c(tape, {"c_trig": "CISD only"}).signals == []
    assert c(long_tape(DAY), {"c_trig": "IFVG only"}).signals == []
    (cisd,) = c(long_tape(DAY), {"c_trig": "CISD only"}).signals
    assert cisd.bar_time == ny(DAY, "09:30")


def test_the_bias_follows_the_lagged_1h_bar() -> None:
    """``request.security("60", f_pdBias(3), lookahead_on)`` returns ``bias[1]``: the
    bullish event of the 06:00 1h bar is visible from the 07:00 1m bar, not at 06:59."""
    at_0659 = model(c(_bias_only(until="06:59")))
    at_0700 = model(c(_bias_only(until="07:01")))
    assert (at_0659._bias.bias, at_0659._bias_last) == (0, ny(DAY, "05:00"))
    assert (at_0700._bias.bias, at_0700._bias_last) == (1, ny(DAY, "06:00"))
    assert at_0700._bias.bias_time == ny(DAY, "06:00") and at_0700._bias.bias_events == (1, 0)
    assert at_0700._bias.bull_gaps == [(102.35, 100.15)]
    # the 05:00 pivot high (105) needs three 1h bars after it: visible from 09:00
    assert at_0700._bias.liq_highs == []
    at_0900 = model(c(_bias_only(until="09:01")))
    assert at_0900._bias.bsl == 105.0 and at_0900._bias.bsl_time == ny(DAY, "05:00")


def _bias_only(*, until: str) -> Tape:
    tape = Tape(ny(DAY, "00:00"))
    tape.quiet_until(ny(DAY, "04:00"), 100.0).walk_until(ny(DAY, "05:00"), 102.5)
    tape.at(ny(DAY, "05:30"), SPIKE).quiet_until(ny(DAY, until), 102.5)
    return tape


def test_the_zone_is_added_on_the_first_1m_bar_of_the_next_5m_bar() -> None:
    """``f_htfFvg`` via lookahead_on: the gap completed by the 09:10 5m bar becomes a zone
    on the 09:15 1m bar (cFresh), not on the 09:14 bar that closes with it."""
    tape = long_tape(DAY, ())
    rows = tape.rows[: tape.index(ny(DAY, "09:15"))]
    early = Tape(tape.start)
    early.rows = rows
    assert model(c(early))._zones.zones == []
    early.rows = tape.rows[: tape.index(ny(DAY, "09:16"))]
    (zone,) = model(c(early))._zones.zones
    assert (zone.dir, zone.top, zone.bot, zone.tapped) == (1, 103.35, 102.65, False)
    assert zone.added == ny(DAY, "09:15")


def test_no_bias_no_trade() -> None:
    """Without a 1H PD-array reaction the bias stays 0 (``var int bias = 0``): no trade."""
    tape = Tape(ny(DAY, "00:00"), level=102.5).quiet_until(ny(DAY, "09:00"))
    tape.at(ny(DAY, "09:00"), *ZONE, TRIGGER, *RALLY).quiet_until(ny(DAY, "12:30"))
    assert c(tape).signals == []
    tape.rows = tape.rows[: tape.index(ny(DAY, "09:31"))]
    assert model(c(tape))._bias.bias == 0


def test_a_zone_against_the_bias_is_never_traded() -> None:
    """A bearish 1H bias (the bias part mirrored about 102.5) with the bullish 5m zone:
    the zone's direction must equal the bias (L816)."""
    tape = Tape(ny(DAY, "00:00"), level=105.0).quiet_until(ny(DAY, "04:00"))
    tape.walk_until(ny(DAY, "05:00"), 102.5)
    tape.at(ny(DAY, "05:30"), mirrored(SPIKE, 102.5)).quiet_until(ny(DAY, "09:00"), 102.5)
    tape.at(ny(DAY, "09:00"), *ZONE, TRIGGER, *RALLY).quiet_until(ny(DAY, "12:30"))
    assert c(tape).signals == []
    tape.rows = tape.rows[: tape.index(ny(DAY, "09:31"))]
    at_0930 = model(c(tape))
    assert at_0930._bias.bias == -1
    assert [(z.dir, z.tapped, z.used) for z in at_0930._zones.zones] == [(1, True, False)]


@pytest.mark.parametrize(("hold", "trades"), [(29, True), (30, False)])
def test_the_extreme_must_be_at_most_c_look_bars_old(hold: int, trades: bool) -> None:
    """``bar_index − z.extBar <= cLook`` (30): the extreme is at 09:23; a trigger 30 bars
    later (09:53) trades, 31 bars later (09:54) does not."""
    waiting = tuple(quiet_row(i, 103.1) for i in range(hold - 6))  # lows 102.95 > 102.9
    tape = long_tape(DAY, (*waiting, TRIGGER, *RALLY))
    trigger_at = ny(DAY, "09:24") + timedelta(minutes=len(waiting) + 6)
    signals = c(tape).signals
    assert int((trigger_at - ny(DAY, "09:00")).total_seconds() // 60) - EXTREME_AT == hold + 1
    if trades:
        (signal,) = signals
        assert signal.bar_time == trigger_at
    else:
        assert signals == []


def test_one_trade_per_window_and_the_zone_is_used() -> None:
    """After the 09:30 trade (cTaken = 1) a later IFVG on the same zone does nothing."""
    tape = long_tape(DAY, (TRIGGER, *HOLD, *IFVG))
    result = c(tape)
    assert [s.signal for s in result.signals] == [LONG]
    st = model(result)
    assert st._taken == 1 and st._zones.zones[0].used


def test_a_close_through_the_zone_kills_it() -> None:
    """A 1m close below the zone's bottom before the trigger removes it (L377-381)."""
    close_through: Row = (103.0, 103.05, 102.5, 102.6)  # close 102.6 < 102.65
    zone = list(ZONE)
    zone[25] = close_through  # 09:25
    tape = Tape(ny(DAY, "00:00"))
    long = long_tape(DAY, ())
    tape.rows = long.rows[: long.index(ny(DAY, "09:00"))]
    tape.level = 102.5
    tape.at(ny(DAY, "09:00"), *zone, TRIGGER, *RALLY).quiet_until(ny(DAY, "12:30"))
    assert c(tape).signals == []


@pytest.mark.parametrize(
    ("params", "target", "kind"),
    [
        ({}, "105.00", "Draw on liquidity"),
        ({"min_rr": 2.0}, "105.15", "Fixed RR"),  # 1.35 < 2 × 0.75: 2R from the close
        ({"c_tgt": "Fixed RR"}, "105.15", "Fixed RR"),
        ({"c_tgt": "Fixed RR", "c_rr": 3.0}, "105.90", "Fixed RR"),
        ({"min_rr": 1.8}, "105.00", "Draw on liquidity"),  # exactly 1.8R away: >= holds
    ],
)
def test_target_is_the_draw_on_liquidity_or_the_fixed_rr(
    params: dict[str, Any], target: str, kind: str
) -> None:
    (signal,) = entries(c(long_tape(DAY, (TRIGGER, *HOLD)), params))
    assert signal.take_profit == Decimal(target)
    assert signal.metadata["target_kind"] == kind


def test_without_untaken_liquidity_the_target_is_2r() -> None:
    """No spike, no 1H pivot high: ``dol`` is na and the target falls back to 2R (L824)."""
    tape = Tape(ny(DAY, "00:00"))
    tape.quiet_until(ny(DAY, "04:00"), 100.0).walk_until(ny(DAY, "05:00"), 102.5)
    tape.quiet_until(ny(DAY, "09:00"), 102.5)
    tape.at(ny(DAY, "09:00"), *ZONE, TRIGGER, *HOLD).quiet_until(ny(DAY, "12:30"))
    (signal,) = entries(c(tape))
    assert signal.take_profit == Decimal("105.15")
    assert signal.metadata["draw_on_liquidity"] is None
    assert signal.metadata["target_kind"] == "Fixed RR"


def test_stop_buffer_moves_the_stop_by_ticks() -> None:
    (signal,) = entries(c(long_tape(DAY, (TRIGGER, *HOLD)), {"sl_buf_ticks": 5}))
    assert signal.stop_loss == Decimal("102.85")  # 102.9 − 5 × 0.01
    assert signal.metadata["risk_points"] == pytest.approx(0.8)


def test_hold_closes_the_trade_at_the_next_09_30() -> None:
    """D6 main: the trade is not closed at 12:00; the next window start flattens it."""
    tape = long_tape(DAY, (TRIGGER, *HOLD), until="09:35", days=1)
    result = c(tape)
    entry, exit_ = result.signals
    next_day = DAY + timedelta(days=1)
    assert entry.signal is LONG
    assert (exit_.signal, exit_.bar_time) == (FLATTEN, ny(next_day, "09:30"))
    assert exit_.reason == CloseReason.SESSION_CLOSE and exit_.metadata["trigger"] == "closed"
    assert exit_.metadata["pine_signal"] == "closeTrade(0)"
    (closed,) = of_kind(result, PositionEventKind.CLOSED)
    assert (closed.reason, closed.time) == (CloseReason.SESSION_CLOSE, ny(next_day, "09:31"))


def test_flat_variant_closes_the_trade_at_12_00() -> None:
    tape = long_tape(DAY, (TRIGGER, *HOLD), until="12:30")
    result = c(tape, {"after_window": "flat"})
    _, exit_ = result.signals
    assert (exit_.signal, exit_.bar_time) == (FLATTEN, ny(DAY, "11:59"))
    assert exit_.metadata["trigger"] == "window end"
    (closed,) = of_kind(result, PositionEventKind.CLOSED)
    assert (closed.reason, closed.time) == (CloseReason.SESSION_CLOSE, ny(DAY, "12:00"))


def test_flat_variant_does_not_enter_on_the_last_window_bar() -> None:
    """A trigger at 11:59 would fill at the 12:00 open the window-end flatten closes it
    at: the flat variant records it as a NO_TRADE, the hold variant trades it."""
    tape = long_tape(DAY, (TRIGGER, *HOLD), zone_at="11:29", until="12:30")
    (held,) = c(tape).signals
    assert (held.signal, held.bar_time) == (LONG, ny(DAY, "11:59"))
    (skipped,) = c(tape, {"after_window": "flat"}).signals
    assert (skipped.signal, skipped.reason) == (NO_TRADE, "ENTRY_ON_LAST_WINDOW_BAR")
    assert skipped.persist and skipped.metadata["trigger"] == "C long"


def test_the_next_window_start_replaces_the_held_trade() -> None:
    """Day 2 at 09:30 closes day 1's trade and opens the new one at the same open. Day 2
    repeats the setup 0.6 higher, so day 1's stop (102.9) and target (105) stay untouched."""
    tape = long_tape(DAY, (TRIGGER, *HOLD), until="23:00")
    day2 = DAY + timedelta(days=1)
    tape.walk_until(ny(day2, "08:00"), 103.1).quiet_until(ny(day2, "09:00"))
    tape.at(ny(day2, "09:00"), *shifted((*ZONE, TRIGGER, *HOLD), 0.6))
    tape.quiet_until(ny(day2, "10:00"))
    result = c(tape)
    assert [(s.signal, s.bar_time) for s in result.signals] == [
        (LONG, ny(DAY, "09:30")),
        (FLATTEN, ny(day2, "09:30")),
        (LONG, ny(day2, "09:30")),
    ]
    assert result.ignored == []
    closed = of_kind(result, PositionEventKind.CLOSED)
    opened = of_kind(result, PositionEventKind.OPENED)
    assert [(e.reason, e.time) for e in closed] == [(CloseReason.SESSION_CLOSE, ny(day2, "09:31"))]
    assert [e.time for e in opened] == [ny(DAY, "09:31"), ny(day2, "09:31")]


@pytest.mark.parametrize(
    ("first_open", "detail"),
    [(102.8, "OPEN_BEYOND_STOP"), (105.2, "OPEN_BEYOND_TARGET")],
)
def test_d3_skips_the_entry_when_the_next_open_passed_a_level(
    first_open: float, detail: str
) -> None:
    """The script prices the entry at the 09:30 close; the lab fills at the 09:31 open
    and skips it when that open is at or beyond the stop or the target (D3)."""
    gap: Row = (first_open, first_open + 0.1, first_open - 0.1, first_open)
    result = c(long_tape(DAY, (TRIGGER, gap)))
    (signal,) = result.signals
    assert signal.signal is LONG
    assert of_kind(result, PositionEventKind.OPENED) == []
    (cancelled,) = of_kind(result, PositionEventKind.ORDER_CANCELLED)
    assert (cancelled.detail, cancelled.time) == (detail, ny(DAY, "09:31"))
    assert model(result)._taken == 1  # the script counted the trade


def test_d3_no_trade_when_the_stop_rounds_onto_the_entry() -> None:
    """On a 1.0 tick the IFVG entry (103.1) and its stop (102.9) both round to 103."""
    coarse = replace(XAUUSD, tick_size=Decimal("1"))
    (signal,) = c(long_tape(DAY, IFVG), instrument=coarse).signals
    assert (signal.signal, signal.reason, signal.persist) == (NO_TRADE, "STOP_WRONG_SIDE", True)
    assert signal.metadata["script_entry"] == 103.1


def test_crypto_trades_on_sunday() -> None:
    """The windows include Saturday and Sunday (ALL_DAYS ':1234567', L27)."""
    sunday = date(2026, 1, 11)
    btc = real_catalog().instrument("BTCUSD")
    (signal,) = c(long_tape(sunday, symbol="BTCUSD"), instrument=btc).signals
    assert (signal.signal, signal.bar_time) == (LONG, ny(sunday, "09:30"))


def test_a_setup_timeframe_must_be_declared() -> None:
    tape = long_tape(DAY, ())
    failed = run_1m(IctModelC, with_htf(tape.bars()), params={"c_fvg_tf": "15m"})
    assert failed.fault is not None and "context_timeframes" in failed.fault.message
    ok = run_1m(
        IctModelC,
        with_htf(tape.bars(), M5, M15, H1),
        params={"c_fvg_tf": "15m"},
        context_timeframes=["15m"],
    )
    assert ok.fault is None


def test_runs_are_deterministic() -> None:
    tape = long_tape(DAY, (TRIGGER, *HOLD), until="09:35", days=1)
    for params in ({}, {"after_window": "flat"}):
        assert dumps(c(tape, params)) == dumps(c(tape, params))


def test_position_direction_matches_the_bias() -> None:
    result = c(long_tape(DAY))
    (opened,) = of_kind(result, PositionEventKind.OPENED)
    assert opened.direction is Direction.LONG


def test_a_trigger_before_09_30_waits_for_the_window() -> None:
    """The 09:29 bar already closes above the CISD level but is outside ``cWin``; the
    09:30 bar, still above it, triggers (a level test, L818)."""
    zone = list(ZONE)
    zone[-1] = TRIGGER  # 09:29 closes 103.65 > 103.6
    tape = long_tape(DAY, ())
    tape.rows = tape.rows[: tape.index(ny(DAY, "09:00"))]
    tape.level = 102.5
    tape.at(ny(DAY, "09:00"), *zone, *RALLY).quiet_until(ny(DAY, "12:30"))
    (signal,) = c(tape).signals
    assert (signal.signal, signal.bar_time, signal.entry) == (
        LONG,
        ny(DAY, "09:30"),
        Decimal("103.85"),
    )


@pytest.mark.parametrize(("zone_at", "trades"), [("11:29", True), ("11:30", False)])
def test_the_window_ends_at_12_00(zone_at: str, trades: bool) -> None:
    """The trigger bar comes 30 minutes after the zone rows start: 11:59 is the window's
    last bar, 12:00 is outside it (bars belong to the window by their open time)."""
    signals = c(long_tape(DAY, (TRIGGER, *HOLD), zone_at=zone_at, until="12:40")).signals
    assert [s.signal for s in signals] == ([LONG] if trades else [])


def test_the_window_start_flatten_is_ignored_when_the_trade_already_closed() -> None:
    """Day 1's trade reached its target; day 2's 09:30 still sends the time exit (it would
    close a position the account kept), which the book records as having nothing to do."""
    result = c(long_tape(DAY, until="09:35", days=1))
    assert [(s.signal, s.bar_time) for s in result.signals] == [
        (LONG, ny(DAY, "09:30")),
        (FLATTEN, ny(DAY + timedelta(days=1), "09:30")),
    ]
    ((ignored, reason),) = result.ignored
    assert ignored.signal is FLATTEN and str(reason) == "NOTHING_TO_FLATTEN"
    (closed,) = of_kind(result, PositionEventKind.CLOSED)
    assert closed.reason is CloseReason.TAKE_PROFIT
    # no fill since that exit: the day after sends nothing
    assert model(result)._traded is False
