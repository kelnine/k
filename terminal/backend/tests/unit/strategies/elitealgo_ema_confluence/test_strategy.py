"""Golden scenarios for the EliteAlgo port (script 9): each rule fires, each filter blocks.

Most scenarios use short indicator lengths (``FAST``) so a hand-built sequence of a
dozen bars reaches every state; the long defaults are covered by the reference
comparison in ``test_reference.py``.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from kterminal.core.enums import SignalAction
from kterminal.domain.market import Bar
from kterminal.indicators import Ema, feed
from kterminal.strategies.elitealgo_ema_confluence import EliteAlgoEmaConfluence
from kterminal.strategy_engine import CloseReason, PositionEventKind
from kterminal.strategy_engine.model import OPEN_BEYOND_STOP, OPEN_BEYOND_TARGET
from tests.fixtures.instruments import T0
from tests.unit.strategies.pine_port_support import (
    actions,
    dumps,
    entries,
    index_of,
    make_bars,
    of_kind,
    path_bars,
    run,
)

LONG, SHORT, NO_TRADE = SignalAction.LONG, SignalAction.SHORT, SignalAction.NO_TRADE

# Short lengths: every indicator is defined within a few bars.
FAST: dict[str, Any] = {
    "fast_len": 2,
    "slow_len": 4,
    "trend_len": 6,
    "rsi_len": 2,
    "adx_len": 2,
    "adx_smoothing": 2,
    "atr_len": 2,
    "pulse_fast": 2,
    "pulse_slow": 3,
    "pulse_signal": 2,
}
ANY_CROSS = {**FAST, "min_confluence": 0, "use_trend_filter": False}
WIDE = {**ANY_CROSS, "sl_mult": 3.0}  # stops and targets out of reach of alternating()
FLAT = (100.0, 100.5, 99.5, 100.0)


def flat_then(*rows: tuple[float, ...], count: int = 10) -> list[Bar]:
    """``count`` flat bars at 100 (true range 1), then ``rows``."""
    return make_bars([FLAT] * count + list(rows))  # type: ignore[arg-type]


def mirror(bars: list[Bar], axis: Decimal = Decimal(200)) -> list[Bar]:
    """The same sequence upside down (prices reflected around ``axis / 2``)."""
    return [
        Bar.of(
            b.instrument,
            b.timeframe,
            b.open_time,
            axis - b.open,
            axis - b.low,
            axis - b.high,
            axis - b.close,
            b.volume,
        )
        for b in bars
    ]


def test_long_on_the_crossover_bar_with_the_scripts_bracket() -> None:
    """Flat at 100, then a bar closing at 101: EMA2 crosses EMA4 (L64). Six of seven checks
    are bullish (no VWAP before the first trading-day anchor). ATR(2) = (1 + 2) / 2 = 1.5,
    so the stop is 101 − 1.5 × 1.5 and the target 2R above (L95-98)."""
    result = run(EliteAlgoEmaConfluence, flat_then((100.0, 101.5, 99.5, 101.0)), params=FAST)
    assert result.fault is None
    assert actions(result) == [(10, LONG)]
    signal = result.signals[0]
    assert (signal.entry, signal.stop_loss, signal.take_profit) == (
        Decimal("101.00"),
        Decimal("98.75"),
        Decimal("105.50"),
    )
    assert signal.confidence == 0.71  # |6 − 1| / 7 → 71 % (L73)
    meta = signal.metadata
    assert meta["pine_signal"] == "longSig" and meta["trigger"] == "Buy"
    assert (meta["bull_count"], meta["bear_count"], meta["stars"]) == (6, 1, 3)
    assert meta["checks"] == {
        "close_above_ema_trend": True,
        "ema_fast_above_ema_slow": True,
        "rsi_above_50": True,
        "di_plus_above_di_minus": True,
        "pulse_hist_above_0": True,
        "close_above_open": True,
        "close_above_vwap": False,
    }
    assert meta["vwap"] is None and meta["atr"] == 1.5 and meta["bar_index"] == 10


def test_short_mirrors_the_long_and_gets_the_na_vwap_point() -> None:
    """The mirrored drop: all seven checks bearish — the na VWAP counts for the short."""
    result = run(EliteAlgoEmaConfluence, flat_then((100.0, 100.5, 98.5, 99.0)), params=FAST)
    assert actions(result) == [(10, SHORT)]
    signal = result.signals[0]
    assert (signal.entry, signal.stop_loss, signal.take_profit) == (
        Decimal("99.00"),
        Decimal("101.25"),
        Decimal("94.50"),
    )
    assert signal.confidence == 1.0
    assert signal.metadata["bear_count"] == 7 and signal.metadata["trigger"] == "Sell"


def test_a_doji_cross_is_a_bearish_point_for_both_directions() -> None:
    """close == open is not bullish (L53): it removes a long's point and adds a short's."""
    doji_up = flat_then((101.0, 101.5, 99.5, 101.0))
    assert run(EliteAlgoEmaConfluence, doji_up, params=FAST).signals[0].metadata["bull_count"] == 5
    assert run(EliteAlgoEmaConfluence, doji_up, params={**FAST, "min_confluence": 6}).signals == []
    assert actions(run(EliteAlgoEmaConfluence, doji_up, params={**FAST, "min_confluence": 5})) == [
        (10, LONG)
    ]
    doji_down = flat_then((99.0, 100.5, 98.5, 99.0))
    short = run(EliteAlgoEmaConfluence, doji_down, params={**FAST, "min_confluence": 7})
    assert actions(short) == [(10, SHORT)]


def test_minimum_confluence_blocks_a_cross() -> None:
    bars = flat_then((100.0, 101.5, 99.5, 101.0))  # 6 of 7
    assert run(EliteAlgoEmaConfluence, bars, params={**FAST, "min_confluence": 7}).signals == []
    assert len(run(EliteAlgoEmaConfluence, bars, params={**FAST, "min_confluence": 6}).signals) == 1


def declining_then_bump() -> list[Bar]:
    """40 bars falling 0.5 a bar, then a jump that crosses EMA2 over EMA4 while the close
    is still below a 20-bar EMA."""
    closes = [120.0 - 0.5 * i for i in range(41)] + [101.5]
    return path_bars(closes)


TREND = {**FAST, "trend_len": 20, "min_confluence": 0}


@pytest.mark.parametrize("side", ["long", "short"])
def test_the_trend_filter_blocks_a_cross_on_the_wrong_side_of_the_trend_ema(side: str) -> None:
    bars = declining_then_bump() if side == "long" else mirror(declining_then_bump())
    closes = [float(b.close) for b in bars]
    fast, slow = feed(Ema(2).update, closes), feed(Ema(4).update, closes)
    trend = feed(Ema(20).update, closes)
    last = len(bars) - 1
    if side == "long":  # preconditions: a crossover, the close below the trend EMA
        assert fast[last] > slow[last] and fast[last - 1] <= slow[last - 1]
        assert closes[last] < trend[last]
    else:
        assert fast[last] < slow[last] and fast[last - 1] >= slow[last - 1]
        assert closes[last] > trend[last]
    blocked = run(EliteAlgoEmaConfluence, bars, params=TREND)
    assert [i for i, _ in actions(blocked)] == []
    unfiltered = run(EliteAlgoEmaConfluence, bars, params={**TREND, "use_trend_filter": False})
    assert actions(unfiltered) == [(last, LONG if side == "long" else SHORT)]


def alternating(count: int = 20) -> list[Bar]:
    """Flat, then closes alternating 101 / 99: EMA2 and EMA4 cross on every bar."""
    closes = [100.0] * 10 + [101.0 if i % 2 == 0 else 99.0 for i in range(count)]
    bars = path_bars(closes)
    fast = feed(Ema(2).update, closes)
    slow = feed(Ema(4).update, closes)
    for i in range(10, len(closes)):  # precondition: a cross on every one of these bars
        assert (fast[i] > slow[i]) != (fast[i - 1] > slow[i - 1])
    return bars


def test_the_cooldown_is_shared_by_both_directions() -> None:
    """A signal blocks every signal of the next four bars, long or short (L60, L93);
    the fifth bar may signal again."""
    result = run(EliteAlgoEmaConfluence, alternating(), params=ANY_CROSS)
    assert actions(result) == [(10, LONG), (15, SHORT), (20, LONG), (25, SHORT)]


@pytest.mark.parametrize(
    ("cooldown", "expected"),
    [(0, list(range(10, 30))), (1, list(range(10, 30))), (2, list(range(10, 30, 2)))],
)
def test_cooldown_length(cooldown: int, expected: list[int]) -> None:
    params = {**ANY_CROSS, "cooldown_bars": cooldown}
    assert [i for i, _ in actions(run(EliteAlgoEmaConfluence, alternating(), params=params))] == (
        expected
    )


def test_a_cross_blocked_by_the_cooldown_is_lost_not_deferred() -> None:
    closes = [100.0] * 10 + [101.0, 99.0, 101.0] + [101.0 + i for i in range(1, 15)]
    result = run(EliteAlgoEmaConfluence, path_bars(closes), params=ANY_CROSS)
    assert actions(result) == [(10, LONG)]


def test_ignored_signals_still_restart_the_cooldown() -> None:
    """D4 'ignore' (the definition's default): the short at bar 15 meets the open long and
    is refused by the position rules, yet the cooldown counts it, so the long cross of
    bar 16 … 19 stays blocked. (A wide stop keeps the long open throughout.)"""
    result = run(EliteAlgoEmaConfluence, alternating(), params=WIDE)
    assert actions(result) == [(10, LONG), (15, SHORT), (20, LONG), (25, SHORT)]
    opened = of_kind(result, PositionEventKind.OPENED)
    assert len(opened) == 1 and index_of_event(opened[0].time) == 11  # filled at the next open
    assert of_kind(result, PositionEventKind.CLOSED) == []  # the long is never reversed


def test_the_reverse_variant_reverses_at_the_next_open() -> None:
    result = run(EliteAlgoEmaConfluence, alternating(), params=WIDE, on_opposite_signal="reverse")
    closed = of_kind(result, PositionEventKind.CLOSED)
    assert [(index_of_event(e.time), e.reason) for e in closed] == [
        (16, CloseReason.REVERSAL),
        (21, CloseReason.REVERSAL),
        (26, CloseReason.REVERSAL),
    ]
    opened = of_kind(result, PositionEventKind.OPENED)
    assert [index_of_event(e.time) for e in opened] == [11, 16, 21, 26]


def index_of_event(at: datetime) -> int:
    return int((at - T0) / timedelta(minutes=5))


@pytest.mark.parametrize(
    ("next_open", "detail"), [(98.0, OPEN_BEYOND_STOP), (106.0, OPEN_BEYOND_TARGET)]
)
def test_gap_guard_skips_an_entry_whose_fill_bar_opens_past_its_levels(
    next_open: float, detail: str
) -> None:
    """D3: the bracket stays at the signal close's levels (stop 98.75, target 105.50);
    a next open at or beyond either cancels the entry."""
    gap = (next_open, next_open + 0.5, next_open - 0.5, next_open)
    bars = flat_then((100.0, 101.5, 99.5, 101.0), gap)
    result = run(EliteAlgoEmaConfluence, bars, params=FAST)
    cancelled = of_kind(result, PositionEventKind.ORDER_CANCELLED)
    assert [e.detail for e in cancelled] == [detail]
    assert of_kind(result, PositionEventKind.OPENED) == []
    # without the guard (an instance override) the entry fills at that open
    unguarded = run(EliteAlgoEmaConfluence, bars, params=FAST, skip_entry_beyond_levels=False)
    assert len(of_kind(unguarded, PositionEventKind.OPENED)) == 1


def test_the_bracket_closes_the_trade_at_stop_or_target() -> None:
    target_hit = flat_then((100.0, 101.5, 99.5, 101.0), (101.0, 106.0, 100.8, 105.0))
    closed = of_kind(run(EliteAlgoEmaConfluence, target_hit, params=FAST), PositionEventKind.CLOSED)
    assert [(e.reason, e.price) for e in closed] == [(CloseReason.TAKE_PROFIT, Decimal("105.50"))]
    stop_hit = flat_then((100.0, 101.5, 99.5, 101.0), (101.0, 101.2, 98.0, 98.5))
    closed = of_kind(run(EliteAlgoEmaConfluence, stop_hit, params=FAST), PositionEventKind.CLOSED)
    assert [(e.reason, e.price) for e in closed] == [(CloseReason.STOP_LOSS, Decimal("98.75"))]


def test_a_stop_that_rounds_onto_the_entry_is_not_traded_but_counts_for_the_cooldown() -> None:
    """D3 wrong-side rule: 0.1 × ATR(2) = 0.0015 is below half a tick, so the stop rounds
    to the entry; the script would still draw the lines, so the cooldown restarts."""
    tiny = [(100.0, 100.01, 100.0, 100.0)] * 10 + [
        (100.0, 100.02, 100.0, 100.02),  # cross up: skipped
        (100.02, 100.02, 99.99, 99.99),  # cross down inside the cooldown: blocked
    ]
    params = {**ANY_CROSS, "sl_mult": 0.1}
    result = run(EliteAlgoEmaConfluence, make_bars(tiny), params=params)  # type: ignore[arg-type]
    assert actions(result) == [(10, NO_TRADE)]
    skipped = result.signals[0]
    assert skipped.reason == "STOP_WRONG_SIDE" and skipped.persist
    assert skipped.metadata["pine_signal"] == "longSig"
    assert entries(result) == []
    assert (
        run(EliteAlgoEmaConfluence, make_bars(tiny), params={**params, "cooldown_bars": 0})
        .signals[1]
        .signal
        == NO_TRADE
    )  # the next cross is a script signal too


def test_runs_are_deterministic() -> None:
    bars = alternating(40)
    first = run(EliteAlgoEmaConfluence, bars, params=ANY_CROSS)
    second = run(EliteAlgoEmaConfluence, bars, params=ANY_CROSS)
    assert dumps(first) == dumps(second) and len(first.signals) > 5


def test_signals_carry_this_bar_and_instance_identity() -> None:
    result = run(EliteAlgoEmaConfluence, flat_then((100.0, 101.5, 99.5, 101.0)), params=FAST)
    signal = result.signals[0]
    assert signal.bar_time == T0 + 10 * timedelta(minutes=5)
    assert signal.timestamp == signal.bar_time + timedelta(minutes=5)
    assert signal.strategy_id == "test_instance" and signal.timeframe == "5m"
    assert index_of(signal) == 10
    assert result.rejected == []


def test_bar_index_counts_warmup_bars_for_the_cooldown() -> None:
    """The cooldown counts primary bars from the first warm-up bar on (Pine bar_index)."""
    bars = alternating()
    warm, live = bars[:13], bars[13:]
    result = run(EliteAlgoEmaConfluence, live, params=ANY_CROSS, warmup_bars=warm)
    # the warm-up signal at bar 10 is discarded but still blocks bars 13 and 14
    assert [index_of(s) for s in result.signals] == [15, 20, 25]
