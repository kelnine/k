"""Golden scenarios for Model D (script 2, S11): at a 15m FVG or a key level an aggressive
selling bar (candle-estimate delta) becomes a long candidate; an aggressive buying bar
closing above its body within ``dMaxBars`` bars is the long, market entry, stop at the
lowest low since the candidate, 2R target (shorts mirror it).

Each test builds a gap-free 1m tape in New York time (``scenario.long_tape``): the 15m
zone from 10:00, the absorption from 11:00. Every rule of L627-643 and L835-924 and every
applied doc 13 decision (D3 gap guard and wrong-side levels, D4 one trade at a time with
the replace when the script's trade closed first, D6 hold and flat) is exercised on known
bars; ``test_levels.py`` covers the overnight and previous-day levels.
"""

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest

from kterminal.core.enums import Direction, SignalAction
from kterminal.domain.signals import Signal
from kterminal.domain.timeframes import M5, M15
from kterminal.strategies.ict_model_d import IctModelD
from kterminal.strategy_engine import CloseReason, PositionEventKind
from kterminal.strategy_engine.testing import StrategyTestResult
from tests.fixtures.instruments import XAUUSD
from tests.unit.strategies.ict_model_d.scenario import (
    BUYERS,
    HOLD,
    LOUD,
    QUIET_VOLUME,
    RALLY,
    SELLERS,
    SETUP,
    WAIT,
    Row,
    Tape,
    long_tape,
    ny,
    quiet_row,
    run_1m,
    with_htf,
)
from tests.unit.strategies.pine_port_support import dumps, of_kind, real_catalog, strategy_object

LONG, SHORT = SignalAction.LONG, SignalAction.SHORT
FLATTEN, NO_TRADE = SignalAction.FLATTEN, SignalAction.NO_TRADE

DAY = date(2026, 1, 6)  # a Tuesday in winter (New York = UTC-5)
LEVELS_ONLY = {"d_zone_mode": "Key levels only"}
ZONES_ONLY = {"d_zone_mode": "HTF FVG only"}


def d(
    tape: Tape,
    params: dict[str, Any] | None = None,
    *,
    mirror: float | None = None,
    **kwargs: Any,
) -> StrategyTestResult:
    result = run_1m(IctModelD, with_htf(tape.bars(mirror=mirror)), params=params, **kwargs)
    assert result.fault is None and result.rejected == []
    return result


def entries(result: StrategyTestResult) -> list[Signal]:
    return [s for s in result.signals if s.signal.is_entry]


def model(result: StrategyTestResult) -> Any:
    return strategy_object(result)


@pytest.mark.parametrize(
    "day",
    [DAY, date(2026, 3, 9), date(2026, 7, 7)],
    ids=["winter-EST", "first-EDT-monday", "summer-EDT"],
)
def test_sellers_absorbed_at_a_15m_fvg_go_long(day: date) -> None:
    """The 11:00 aggressive selling bar overlaps the bullish 15m zone; the 11:03
    aggressive buying bar closes above its body top: long, stop at the lowest low since
    the candidate, target 2R from the signal close."""
    result = d(long_tape(day))
    (signal,) = result.signals
    assert (signal.signal, signal.bar_time) == (LONG, ny(day, "11:03"))
    assert (signal.entry, signal.stop_loss, signal.take_profit) == (
        Decimal("111.25"),
        Decimal("110.35"),
        Decimal("113.05"),
    )
    meta = signal.metadata
    assert (meta["trigger"], meta["pine_signal"], meta["trade_tag"]) == (
        "D long",
        "evD",
        "D absorption",
    )
    assert (meta["absorbed"], meta["zone_mode"], meta["delta_source"]) == (
        "sellers",
        "HTF FVG + key levels",
        "Candle estimate",
    )
    cand = meta["candidate"]
    assert isinstance(cand, dict)
    assert (cand["time"], cand["bars_ago"]) == (ny(day, "11:00").isoformat(), 3)
    assert (cand["body_edge"], cand["origin"], cand["extreme"]) == (111.0, 110.4, 110.35)
    assert cand["volume"] == LOUD and cand["avg_volume"] == pytest.approx(115.0)
    assert cand["delta"] == pytest.approx(400 * (2 * 0.1 / 0.65 - 1))
    assert cand["at"] == [
        {
            "kind": "15m FVG",
            "top": 110.85,
            "bottom": 110.15,
            "first_candle": ny(day, "10:00").isoformat(),
        }
    ]
    trig = meta["trigger_bar"]
    assert isinstance(trig, dict)
    assert (trig["volume"], trig["avg_volume"]) == (LOUD, pytest.approx(130.0))
    assert trig["delta_pct"] == pytest.approx(100 * (2 * 0.9 / 0.95 - 1))
    levels = meta["levels"]
    assert isinstance(levels, dict) and set(levels.values()) == {None}  # no overnight yet
    assert (meta["script_entry"], meta["script_stop"], meta["script_target"]) == (
        111.25,
        110.35,
        pytest.approx(113.05),
    )
    assert meta["risk_points"] == pytest.approx(0.9) and meta["planned_rr"] == 2.0
    (opened,) = of_kind(result, PositionEventKind.OPENED)
    (closed,) = of_kind(result, PositionEventKind.CLOSED)
    assert (opened.time, opened.price, opened.direction) == (
        ny(day, "11:04"),
        Decimal("111.25"),
        Direction.LONG,
    )
    assert (closed.reason, closed.price, closed.time) == (
        CloseReason.TAKE_PROFIT,
        Decimal("113.05"),
        ny(day, "11:07"),
    )


def test_buyers_absorbed_at_a_bearish_zone_go_short() -> None:
    result = d(long_tape(DAY), mirror=100.0)
    (signal,) = result.signals
    assert (signal.signal, signal.bar_time) == (SHORT, ny(DAY, "11:03"))
    assert (signal.entry, signal.stop_loss, signal.take_profit) == (
        Decimal("88.75"),
        Decimal("89.65"),
        Decimal("86.95"),
    )
    meta = signal.metadata
    assert (meta["trigger"], meta["absorbed"]) == ("D short", "buyers")
    cand = meta["candidate"]
    assert isinstance(cand, dict)
    assert (cand["body_edge"], cand["origin"], cand["extreme"]) == (89.0, 89.6, 89.65)
    assert cand["at"][0]["kind"] == "15m FVG"  # type: ignore[index]
    (closed,) = of_kind(result, PositionEventKind.CLOSED)
    assert (closed.reason, closed.price) == (CloseReason.TAKE_PROFIT, Decimal("86.95"))


def test_where_to_look() -> None:
    """``dZoneMode``: the zone setup trades with zones on, not with key levels only."""
    (zones_only,) = d(long_tape(DAY), ZONES_ONLY).signals
    assert zones_only.signal is LONG
    assert d(long_tape(DAY), LEVELS_ONLY).signals == []
    # a manual level inside the selling bar's range is support with key levels only
    (at_level,) = d(long_tape(DAY), {**LEVELS_ONLY, "d_man1": 110.6}).signals
    assert at_level.signal is LONG
    cand = at_level.metadata["candidate"]
    assert isinstance(cand, dict)
    assert cand["at"] == [{"kind": "level", "name": "manual 1", "price": 110.6}]
    assert at_level.metadata["levels"]["manual 1"] == 110.6  # type: ignore[index]
    assert d(long_tape(DAY), {**LEVELS_ONLY, "d_man2": 110.6}).signals[0].signal is LONG


def test_a_key_level_is_support_and_resistance_a_zone_one_side_only() -> None:
    """Every key level marks the bar both ways (L869-871), so the mirrored setup at the
    mirrored level shorts; a bullish zone is never resistance (L410-413)."""
    (short,) = d(long_tape(DAY), {**LEVELS_ONLY, "d_man1": 89.4}, mirror=100.0).signals
    assert short.signal is SHORT
    buyers_at_bull_zone: tuple[Row, ...] = (
        (110.5, 111.0, 110.45, 110.95, LOUD),  # aggressive buying overlapping the bull zone
        (110.95, 111.0, 110.85, 110.9, QUIET_VOLUME),
        (110.9, 110.95, 110.2, 110.25, LOUD),  # aggressive selling closing below 110.5
        *HOLD,
    )
    tape = long_tape(DAY, buyers_at_bull_zone)
    assert entries(d(tape, ZONES_ONLY)) == []
    (with_level,) = entries(d(tape, {"d_man1": 110.6}))
    assert with_level.signal is SHORT


@pytest.mark.parametrize(("tol_atr", "trades"), [(0.25, True), (0.1, False), (0.0, False)])
def test_a_level_within_the_atr_tolerance_counts(tol_atr: float, trades: bool) -> None:
    """``low <= lvl + tol and high >= lvl - tol`` with ``tol = dTolAtr × ATR(14)``: a level
    0.05 below the selling bar's low touches it with tol ≈ 0.077 (ATR ≈ 0.31), not with
    0.1 × ATR or 0."""
    params = {**LEVELS_ONLY, "d_man1": 110.35, "d_tol_atr": tol_atr}
    signals = entries(d(long_tape(DAY), params))
    if trades:
        (signal,) = signals
        atr, tol = signal.metadata["atr"], signal.metadata["tolerance"]
        assert isinstance(atr, float) and isinstance(tol, float)
        assert tol == pytest.approx(0.25 * atr) and 0.05 < tol < 0.1
    else:
        assert signals == []


def test_a_close_below_the_candidate_low_cancels_it() -> None:
    wait = (WAIT[0], (110.7, 110.75, 110.35, 110.38, QUIET_VOLUME))  # close < 110.4
    assert d(long_tape(DAY, (SELLERS, *wait, BUYERS, *RALLY))).signals == []


@pytest.mark.parametrize(("bars_after", "trades"), [(10, True), (11, False)])
def test_the_reversal_must_come_within_d_max_bars(bars_after: int, trades: bool) -> None:
    """``bar_index − dLBar > dMaxBars`` (10) cancels the candidate before the trigger test."""
    wait = tuple(quiet_row(i, 110.6) for i in range(bars_after - 1))  # lows 110.45
    signals = d(long_tape(DAY, (SELLERS, *wait, BUYERS, *HOLD))).signals
    trigger_at = ny(DAY, "11:00") + timedelta(minutes=bars_after)
    if trades:
        (signal,) = signals
        assert signal.bar_time == trigger_at
        assert signal.metadata["candidate"]["bars_ago"] == bars_after  # type: ignore[index]
    else:
        assert signals == []
    assert d(long_tape(DAY, (SELLERS, *wait, BUYERS, *HOLD)), {"d_max_bars": 11}).signals


@pytest.mark.parametrize(("close", "trades"), [(111.0, False), (111.01, True)])
def test_the_buyers_must_close_above_the_body_top(close: float, trades: bool) -> None:
    buyers: Row = (110.6, 111.3, 110.35, close, LOUD)
    signals = d(long_tape(DAY, (SELLERS, *WAIT, buyers, *HOLD))).signals
    assert [s.signal for s in signals] == ([LONG] if trades else [])


@pytest.mark.parametrize(
    ("sellers", "buyers"),
    [
        ((111.0, 111.05, 110.4, 110.5, 150.0), BUYERS),  # selling volume < 1.5 × average
        ((111.0, 111.05, 110.4, 110.7, LOUD), BUYERS),  # delta −8 % of the volume
        (SELLERS, (110.6, 111.3, 110.35, 111.25, 170.0)),  # buying volume < 1.5 × average
        (SELLERS, (110.6, 111.8, 110.35, 111.05, LOUD)),  # delta −3 %: closes mid-range
    ],
    ids=["sell-volume", "sell-delta", "buy-volume", "buy-delta"],
)
def test_aggressive_bars_need_volume_and_delta(sellers: Row, buyers: Row) -> None:
    assert d(long_tape(DAY, (sellers, *WAIT, buyers, *HOLD))).signals == []


def test_without_volume_model_d_never_trades() -> None:
    """``nz(volume)``: a feed without volume never has an aggressive bar (L636, L642)."""
    tape = long_tape(DAY)
    tape.rows = [(o, h, low, c, 0.0) for o, h, low, c, _ in tape.rows]
    assert d(tape).signals == []


@pytest.mark.parametrize(("at", "trades"), [("15:56", True), ("15:57", False)])
def test_the_window_ends_at_16_00(at: str, trades: bool) -> None:
    """The buyers come three bars after the sellers: 15:59 is the window's last bar,
    16:00 is outside it (by open time), and outside the window candidates reset."""
    signals = d(long_tape(DAY, (*SETUP, *HOLD), at=at, until="16:30")).signals
    assert [s.signal for s in signals] == ([LONG] if trades else [])


def test_a_candidate_before_09_30_is_dropped() -> None:
    """Outside the window every candidate resets (L878-880): sellers at 09:28 and buyers at
    09:31 do not trade; sellers at 09:30 and buyers at 09:33 do."""
    for at, trades in (("09:28", False), ("09:30", True)):
        tape = Tape(ny(DAY, "09:00"), level=110.6).quiet_until(ny(DAY, at))
        tape.at(ny(DAY, at), *SETUP, *HOLD).quiet_until(ny(DAY, "10:00"))
        signals = d(tape, {**LEVELS_ONLY, "d_man1": 110.6}).signals
        assert [s.signal for s in signals] == ([LONG] if trades else []), at


def test_one_trade_at_a_time_and_no_daily_cap() -> None:
    """While the script's trade is open no candidate forms; once its target is hit the
    next absorption trades again the same day."""
    during = (*SETUP, *HOLD, *SETUP, *HOLD)
    assert [s.signal for s in d(long_tape(DAY, during)).signals] == [LONG]
    lift = 113.2 - 111.0  # the second setup 2.2 higher, at a level
    after = (*SETUP, *RALLY, *(quiet_row(i, 113.2) for i in range(20)))
    second = tuple((o + lift, h + lift, lo + lift, c + lift, v) for o, h, lo, c, v in SETUP)
    tape = long_tape(DAY, (*after, *second, *HOLD))
    signals = d(tape, {"d_man1": 110.6 + lift}).signals
    assert [(s.signal, s.bar_time) for s in signals] == [
        (LONG, ny(DAY, "11:03")),
        (LONG, ny(DAY, "11:30")),
    ]
    closed = of_kind(d(tape, {"d_man1": 110.6 + lift}), PositionEventKind.CLOSED)
    assert [e.reason for e in closed] == [CloseReason.TAKE_PROFIT]


def test_a_new_candidate_can_form_on_the_bar_that_stops_the_trade() -> None:
    """``tD.manage`` runs first (L779): the bar that stops the first trade is itself an
    aggressive selling bar at the zone, and the buyers that follow open the second."""
    stop_and_sell: Row = (111.5, 111.55, 110.3, 110.4, LOUD)  # stop 110.35 touched
    wait = ((110.4, 110.65, 110.32, 110.6, QUIET_VOLUME),)
    buyers: Row = (110.6, 111.6, 110.32, 111.55, LOUD)  # close > 111.5
    result = d(long_tape(DAY, (*SETUP, *HOLD, stop_and_sell, *wait, buyers, *HOLD)))
    first, second = result.signals
    assert (first.signal, second.signal) == (LONG, LONG)
    assert (second.stop_loss, second.take_profit) == (Decimal("110.30"), Decimal("114.05"))
    cand = second.metadata["candidate"]
    assert isinstance(cand, dict) and cand["time"] == ny(DAY, "11:06").isoformat()
    closed = of_kind(result, PositionEventKind.CLOSED)
    assert [e.reason for e in closed] == [CloseReason.STOP_LOSS]
    assert len(of_kind(result, PositionEventKind.OPENED)) == 2


def test_a_live_candidate_is_not_refreshed() -> None:
    """A second aggressive selling bar does not move the candidate (``dLS == 0`` only):
    the body top stays 111.0, so a close at 111.1 (below the second bar's 111.2) trades."""
    second_sellers: Row = (111.2, 111.25, 110.45, 110.55, LOUD)
    buyers: Row = (110.6, 111.15, 110.35, 111.1, LOUD)
    (signal,) = d(long_tape(DAY, (SELLERS, second_sellers, buyers, *HOLD))).signals
    cand = signal.metadata["candidate"]
    assert isinstance(cand, dict)
    assert (cand["time"], cand["body_edge"], cand["bars_ago"]) == (
        ny(DAY, "11:00").isoformat(),
        111.0,
        2,
    )


def test_the_long_branch_runs_first() -> None:
    """At a key level the buying bar is also an aggressive buy at resistance, but the long
    trigger takes it and clears both candidates (L895-896); no short candidate remains."""
    result = d(long_tape(DAY, (*SETUP, *HOLD)), {**LEVELS_ONLY, "d_man1": 110.6})
    assert [s.signal for s in result.signals] == [LONG]
    st = model(result)
    assert st._long is None and st._short is None


# ── decisions ──────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("first_open", "detail", "script_result"),
    [(110.3, "OPEN_BEYOND_STOP", -1), (113.1, "OPEN_BEYOND_TARGET", 1)],
)
def test_d3_skips_the_entry_when_the_next_open_passed_a_level(
    first_open: float, detail: str, script_result: int
) -> None:
    """The script prices the entry at the 11:03 close; the lab fills at the 11:04 open and
    skips it when that open is at or beyond the stop or the target (D3). The script's own
    trade is closed on that bar by the same touch."""
    gap: Row = (first_open, first_open + 0.1, first_open - 0.1, first_open, QUIET_VOLUME)
    result = d(long_tape(DAY, (*SETUP, gap)))
    (signal,) = result.signals
    assert signal.signal is LONG
    assert of_kind(result, PositionEventKind.OPENED) == []
    (cancelled,) = of_kind(result, PositionEventKind.ORDER_CANCELLED)
    assert (cancelled.detail, cancelled.time) == (detail, ny(DAY, "11:04"))
    trade = model(result)._trade
    assert (trade.live, trade.result) == (False, script_result)


def test_d3_no_trade_when_the_stop_rounds_onto_the_entry() -> None:
    """On a 5.0 tick the entry (111.25) and its stop (110.35) both round to 110."""
    coarse = replace(XAUUSD, tick_size=Decimal("5"))
    (signal,) = d(long_tape(DAY, (*SETUP, *HOLD)), instrument=coarse).signals
    assert (signal.signal, signal.reason, signal.persist) == (NO_TRADE, "STOP_WRONG_SIDE", True)
    assert signal.metadata["script_entry"] == 111.25
    assert model(d(long_tape(DAY, (*SETUP, *HOLD)), instrument=coarse))._trade.live


def test_the_book_keeps_a_trade_the_script_closed_until_the_next_one_replaces_it() -> None:
    """On a 0.1 tick the target 113.08 rounds to 113.1: a high of 113.09 closes the
    script's trade but not the book's. The next setup — a short at a key level — first
    closes the book's long at the next open (D4: one trade at a time), then shorts there."""
    tick = replace(XAUUSD, tick_size=Decimal("0.1"))
    buyers: Row = (110.6, 111.3, 110.35, 111.26, LOUD)  # risk 0.91, target 113.08
    to_target = (
        (111.26, 111.6, 111.2, 111.55, QUIET_VOLUME),
        (111.55, 112.4, 111.5, 112.35, QUIET_VOLUME),
        (112.35, 113.09, 112.3, 113.0, QUIET_VOLUME),  # 113.09: the script's target
    )
    short_setup = (
        (112.9, 113.05, 112.85, 113.03, LOUD),  # aggressive buying at the 113 level
        (113.0, 113.04, 112.5, 112.55, LOUD),  # aggressive selling below 112.9
        (112.55, 112.6, 112.45, 112.5, QUIET_VOLUME),
    )
    tape = long_tape(DAY, (SELLERS, *WAIT, buyers, *to_target, *short_setup))
    result = d(tape, {"d_man1": 113.0}, instrument=tick)
    assert [(s.signal, s.bar_time) for s in result.signals] == [
        (LONG, ny(DAY, "11:03")),
        (FLATTEN, ny(DAY, "11:08")),
        (SHORT, ny(DAY, "11:08")),
    ]
    flatten = result.signals[1]
    assert flatten.metadata["trigger"] == "replaced" and flatten.reason is not None
    assert result.ignored == []
    (closed,) = of_kind(result, PositionEventKind.CLOSED)
    assert (closed.reason, closed.time) == (CloseReason.SIGNAL_EXIT, ny(DAY, "11:09"))
    opened = of_kind(result, PositionEventKind.OPENED)
    assert [(e.direction, e.time) for e in opened] == [
        (Direction.LONG, ny(DAY, "11:04")),
        (Direction.SHORT, ny(DAY, "11:09")),
    ]


def test_hold_closes_the_trade_at_the_next_09_30() -> None:
    """D6 main: the trade is not closed at 16:00; the next window start flattens it."""
    result = d(long_tape(DAY, (*SETUP, *HOLD), until="09:35", days=1))
    entry, exit_ = result.signals
    next_day = DAY + timedelta(days=1)
    assert entry.signal is LONG
    assert (exit_.signal, exit_.bar_time) == (FLATTEN, ny(next_day, "09:30"))
    assert exit_.reason == CloseReason.SESSION_CLOSE and exit_.metadata["trigger"] == "closed"
    assert exit_.metadata["pine_signal"] == "closeTrade(0)"
    (closed,) = of_kind(result, PositionEventKind.CLOSED)
    assert (closed.reason, closed.time) == (CloseReason.SESSION_CLOSE, ny(next_day, "09:31"))
    assert model(result)._trade.live is False  # the script closed it too (neutral)


def test_flat_variant_closes_the_trade_at_16_00() -> None:
    result = d(long_tape(DAY, (*SETUP, *HOLD), until="16:30"), {"after_window": "flat"})
    _, exit_ = result.signals
    assert (exit_.signal, exit_.bar_time) == (FLATTEN, ny(DAY, "15:59"))
    assert exit_.metadata["trigger"] == "window end"
    (closed,) = of_kind(result, PositionEventKind.CLOSED)
    assert (closed.reason, closed.time) == (CloseReason.SESSION_CLOSE, ny(DAY, "16:00"))


def test_flat_variant_does_not_enter_on_the_last_window_bar() -> None:
    tape = long_tape(DAY, (*SETUP, *HOLD), at="15:56", until="16:30")
    (held,) = d(tape).signals
    assert (held.signal, held.bar_time) == (LONG, ny(DAY, "15:59"))
    (skipped,) = d(tape, {"after_window": "flat"}).signals
    assert (skipped.signal, skipped.reason) == (NO_TRADE, "ENTRY_ON_LAST_WINDOW_BAR")
    assert skipped.persist and skipped.metadata["trigger"] == "D long"


def test_the_window_start_flatten_is_ignored_when_the_trade_already_closed() -> None:
    result = d(long_tape(DAY, until="09:35", days=1))
    assert [(s.signal, s.bar_time) for s in result.signals] == [
        (LONG, ny(DAY, "11:03")),
        (FLATTEN, ny(DAY + timedelta(days=1), "09:30")),
    ]
    ((ignored, reason),) = result.ignored
    assert ignored.signal is FLATTEN and str(reason) == "NOTHING_TO_FLATTEN"


# ── sessions, instruments, determinism ─────────────────────────────────────────────
def test_crypto_trades_on_sunday() -> None:
    """The window includes Saturday and Sunday (ALL_DAYS ':1234567', L27)."""
    sunday = date(2026, 1, 11)
    btc = real_catalog().instrument("BTCUSD")
    (signal,) = d(long_tape(sunday, symbol="BTCUSD"), instrument=btc).signals
    assert (signal.signal, signal.bar_time) == (LONG, ny(sunday, "11:03"))


def test_a_zone_timeframe_must_be_declared() -> None:
    tape = long_tape(DAY)
    failed = run_1m(IctModelD, with_htf(tape.bars()), params={"d_fvg_tf": "5m"})
    assert failed.fault is not None and "context_timeframes" in failed.fault.message
    ok = run_1m(
        IctModelD,
        with_htf(tape.bars(), M5, M15),
        params={"d_fvg_tf": "5m"},
        context_timeframes=["5m"],
    )
    assert ok.fault is None
    # with key levels only no zone timeframe is read
    levels_only = run_1m(IctModelD, with_htf(tape.bars()), params={**LEVELS_ONLY, "d_fvg_tf": "5m"})
    assert levels_only.fault is None


def test_intrabar_delta_is_not_available() -> None:
    with pytest.raises(ValueError, match="Candle estimate"):
        IctModelD.Params.model_validate({"d_delta": "Intrabar (lower TF)"})


def test_runs_are_deterministic() -> None:
    tape = long_tape(DAY, (*SETUP, *HOLD), until="09:35", days=1)
    for params in ({}, {"after_window": "flat"}, LEVELS_ONLY | {"d_man1": 110.6}):
        assert dumps(d(tape, params)) == dumps(d(tape, params))
