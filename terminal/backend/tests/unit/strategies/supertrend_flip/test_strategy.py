"""Golden scenarios for the Jetstream SuperTrend port (script 10): flips, strong-only,
the doc 13 D5 exits and stops (fixed and trailed), D3 guards and determinism.

Scenarios use ``atr_len 2, mult 1`` and a short WaveTrend so a few dozen hand-built bars
reach every state; each test first checks, with the indicator classes, that the bars do
produce the flips (and wt1 signs) it relies on.
"""

from dataclasses import dataclass
from decimal import Decimal
from itertools import pairwise
from typing import Any

import pytest
from pydantic import ValidationError

from kterminal.core.enums import SignalAction
from kterminal.domain.market import Bar
from kterminal.indicators import SuperTrend, WaveTrend, feed
from kterminal.strategies.supertrend_flip import SuperTrendFlip, SuperTrendFlipParams
from kterminal.strategies.supertrend_flip.strategy import flip_signals
from kterminal.strategy_engine import CloseReason, PositionEventKind
from kterminal.strategy_engine.model import OPEN_BEYOND_STOP
from kterminal.strategy_engine.registry import definition_from_class
from tests.fixtures.instruments import XAUUSD
from tests.unit.strategies.pine_port_support import (
    actions,
    dumps,
    index_of,
    make_bars,
    of_kind,
    path_bars,
    run,
)

LONG, SHORT = SignalAction.LONG, SignalAction.SHORT
EXIT_LONG, EXIT_SHORT = SignalAction.EXIT_LONG, SignalAction.EXIT_SHORT
MOVE_SL, NO_TRADE = SignalAction.MOVE_SL, SignalAction.NO_TRADE

SMALL: dict[str, Any] = {"atr_len": 2, "mult": 1.0, "n1": 3, "n2": 8, "sig_len": 2}

# flat, a rally (plain BUY at 6), a one-bar drop (SELL+ at 20: wt1 still > 0), a rally
# again (plain BUY at 23: wt1 already > 0)
RALLY = [100.0] * 5 + [100.0 + i for i in range(1, 16)] + [110.0]
RALLY += [110 + 1.5 * i for i in range(1, 8)]
# the mirror: plain SELL never (starts down), BUY+ at 20 (wt1 still < 0), plain SELL at 23
SLIDE = [100.0] * 5 + [100.0 - i for i in range(1, 16)] + [90.0]
SLIDE += [90 - 1.5 * i for i in range(1, 8)]


@dataclass(frozen=True)
class Flip:
    index: int
    buy: bool
    strong: bool
    line: float
    atr: float


def flips(bars: list[Bar], params: dict[str, Any] = SMALL) -> list[Flip]:
    """Every SuperTrend flip of the bars, from the indicator classes directly."""
    p = SuperTrendFlipParams.model_validate(params)
    highs = [float(b.high) for b in bars]
    lows = [float(b.low) for b in bars]
    closes = [float(b.close) for b in bars]
    supertrend = SuperTrend(p.mult, p.atr_len)
    out = []
    previous = None
    hlc3 = [(h + lo + c) / 3 for h, lo, c in zip(highs, lows, closes, strict=True)]
    waves = feed(WaveTrend(p.n1, p.n2, p.sig_len).update, hlc3)
    for i, (h, lo, c) in enumerate(zip(highs, lows, closes, strict=True)):
        line, direction = supertrend.update(h, lo, c)
        if previous is not None and direction != previous:
            buy = direction == -1
            wt1 = waves[i].wt1
            strong = (wt1 < 0) if buy else (wt1 > 0)
            out.append(Flip(i, buy, strong, line, supertrend.atr))
        previous = direction
    return out


def lines(bars: list[Bar]) -> list[float]:
    """The SuperTrend line of ``SMALL`` on every bar."""
    supertrend = SuperTrend(1.0, 2)
    return [supertrend.update(float(b.high), float(b.low), float(b.close))[0] for b in bars]


def price(value: float) -> Decimal:
    return XAUUSD.round_price(Decimal(repr(value)))


def test_flip_signals_follow_the_script() -> None:
    nan = float("nan")
    assert flip_signals(-2.0, -5.0) == (True, False, True, False)  # BUY+
    assert flip_signals(-2.0, 5.0) == (True, False, False, False)  # BUY
    assert flip_signals(2.0, 5.0) == (False, True, False, True)  # SELL+
    assert flip_signals(2.0, -5.0) == (False, True, False, False)  # SELL
    assert flip_signals(2.0, 0.0) == (False, True, False, False)  # wt1 == 0 is not strong
    assert flip_signals(0.0, -5.0) == (False, False, False, False)  # no flip
    assert flip_signals(nan, -5.0) == (False, False, False, False)  # first bar: change is na
    assert flip_signals(-2.0, nan) == (True, False, False, False)  # wt1 warming up: plain


def test_the_scenarios_produce_the_flips_they_are_built_for() -> None:
    assert [(f.index, f.buy, f.strong) for f in flips(path_bars(RALLY))] == [
        (6, True, False),
        (20, False, True),
        (23, True, False),
    ]
    assert [(f.index, f.buy, f.strong) for f in flips(path_bars(SLIDE))] == [
        (20, True, True),
        (23, False, False),
    ]


def test_stop_and_reverse_on_every_flip_with_a_stop_one_atr_beyond_the_line() -> None:
    bars = path_bars(RALLY)
    result = run(SuperTrendFlip, bars, params=SMALL)
    assert result.fault is None and result.rejected == []
    assert actions(result) == [
        (6, LONG),
        (20, EXIT_LONG),
        (20, SHORT),
        (23, EXIT_SHORT),
        (23, LONG),
    ]
    by_index = {f.index: f for f in flips(bars)}
    for signal in result.signals:
        if signal.signal.is_entry:
            flip = by_index[index_of(signal)]
            offset = flip.atr if flip.buy else -flip.atr
            assert signal.stop_loss == price(flip.line - offset)
            assert signal.take_profit is None  # the script has no target
            assert signal.entry == bars[flip.index].close
    meta = result.signals[1].metadata
    assert (meta["trigger"], meta["pine_signal"], meta["strong"]) == ("SELL+", "strongSell", True)
    assert result.signals[1].reason == "SuperTrend flip (SELL+)"
    # the book: each flip closes at the next open (SIGNAL_EXIT) and enters at that open
    closed = of_kind(result, PositionEventKind.CLOSED)
    opened = of_kind(result, PositionEventKind.OPENED)
    assert [(e.reason, e.price) for e in closed] == [
        (CloseReason.SIGNAL_EXIT, bars[21].open),
        (CloseReason.SIGNAL_EXIT, bars[24].open),
    ]
    assert [e.price for e in opened] == [bars[7].open, bars[21].open, bars[24].open]


def test_strong_only_enters_on_plus_signals_and_exits_flat_on_any_opposite_flip() -> None:
    result = run(SuperTrendFlip, path_bars(RALLY), params={**SMALL, "signals": "strong"})
    # the plain BUY at 6 is not traded; SELL+ at 20 is; the plain BUY at 23 only exits
    assert actions(result) == [(20, SHORT), (23, EXIT_SHORT)]
    slide = run(SuperTrendFlip, path_bars(SLIDE), params={**SMALL, "signals": "strong"})
    assert actions(slide) == [(20, LONG), (23, EXIT_LONG)]
    assert slide.signals[0].metadata["trigger"] == "BUY+"


def test_trailing_variant_moves_the_stop_onto_the_line_every_bar() -> None:
    bars = path_bars(RALLY)
    params = {**SMALL, "trail_stop": True, "stop_atr_mult": 0.0}
    result = run(SuperTrendFlip, bars, params=params)
    line = lines(bars)
    entry = result.signals[0]
    assert (index_of(entry), entry.signal) == (6, LONG)
    assert entry.stop_loss == price(line[6])  # on the line itself
    moves = [s for s in result.signals if s.signal is MOVE_SL and index_of(s) < 20]
    # from the fill bar (7) on, every bar the rising line tightens the long's stop
    assert [index_of(s) for s in moves] == list(range(7, 20))
    assert [s.stop_loss for s in moves] == [price(line[i]) for i in range(7, 20)]
    stops = [entry.stop_loss] + [s.stop_loss for s in moves]
    assert all(b > a for a, b in pairwise(stops))  # never widens
    # bar 20 drops through the trailed stop: closed there, before the flip is even seen
    closed = of_kind(result, PositionEventKind.CLOSED)
    assert (closed[0].reason, closed[0].price) == (CloseReason.STOP_LOSS, price(line[19]))
    later = [(i, a) for i, a in actions(result) if i >= 20 and a is not MOVE_SL]
    assert later == [(20, SHORT), (23, LONG)]  # flat at the flips: no exits
    # the short is trailed too, downwards, until bar 23's rally takes it out
    short_moves = [
        s.stop_loss for s in result.signals if s.signal is MOVE_SL and 20 < index_of(s) < 23
    ]
    assert short_moves and all(m is not None and m < price(line[20]) for m in short_moves)
    assert of_kind(result, PositionEventKind.STOP_MOVED)


def test_no_stop_move_while_the_line_does_not_tighten() -> None:
    """The flat stretch after a peak keeps the lower band (it only rises): no MOVE_SL."""
    closes = [100.0] * 5 + [100.0 + i for i in range(1, 8)] + [107.0, 106.0, 107.0, 106.5]
    bars = path_bars(closes)
    result = run(SuperTrendFlip, bars, params={**SMALL, "trail_stop": True, "stop_atr_mult": 0.0})
    moved = [index_of(s) for s in result.signals if s.signal is MOVE_SL]
    line = lines(bars)
    unchanged = [i for i in range(8, len(bars)) if line[i] == line[i - 1]]
    assert unchanged and not set(unchanged) & set(moved)


def test_gap_guard_cancels_the_new_side_but_the_flip_still_exits() -> None:
    """D3: a reversal whose fill bar opens beyond the new short's stop exits the long at
    that open and skips the short."""
    bars = path_bars(RALLY)[:21]
    short = run(SuperTrendFlip, bars, params=SMALL).signals[-1]
    assert short.signal is SHORT and short.stop_loss is not None
    gap = float(short.stop_loss) + 1.0
    bars.append(make_bars([(gap, gap + 0.5, gap - 0.5, gap)], start=bars[-1].close_time)[0])
    result = run(SuperTrendFlip, bars, params=SMALL)
    closed = of_kind(result, PositionEventKind.CLOSED)
    assert [(e.reason, e.price) for e in closed] == [(CloseReason.SIGNAL_EXIT, Decimal(repr(gap)))]
    cancelled = of_kind(result, PositionEventKind.ORDER_CANCELLED)
    assert [e.detail for e in cancelled] == [OPEN_BEYOND_STOP]


def test_a_stop_below_zero_is_not_traded() -> None:
    """D3: a stop that cannot exist (here 100 ATR below the line) skips the entry, recorded
    as a NO_TRADE with the script's levels."""
    result = run(SuperTrendFlip, path_bars(RALLY)[:8], params={**SMALL, "stop_atr_mult": 100.0})
    assert actions(result) == [(6, NO_TRADE)]
    assert result.signals[0].reason == "STOP_NOT_POSITIVE" and result.signals[0].persist


def test_runs_are_deterministic() -> None:
    bars = path_bars(RALLY + SLIDE)
    assert dumps(run(SuperTrendFlip, bars, params=SMALL)) == dumps(
        run(SuperTrendFlip, bars, params=SMALL)
    )


def test_params_and_definition() -> None:
    p = SuperTrendFlipParams()
    assert (p.atr_len, p.mult, p.n1, p.n2, p.sig_len) == (10, 3.0, 10, 21, 4)
    assert (p.signals, p.stop_atr_mult, p.trail_stop) == ("all", 1.0, False)
    for bad in ({"signals": "htf"}, {"mult": 0.0}, {"stop_atr_mult": -1.0}, {"atr_len": 0}):
        with pytest.raises(ValidationError):
            SuperTrendFlipParams.model_validate(bad)
    meta = definition_from_class(SuperTrendFlip).meta
    assert (meta.id, meta.on_opposite_signal, meta.skip_entry_beyond_levels) == (
        "supertrend_flip",
        "reverse",
        True,
    )
    assert meta.warmup_bars >= 300
