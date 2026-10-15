"""Golden scenarios for the PSAR port (script 4): entries on the flip bar with the doc 13 D5
stop, exits on the opposite flip regardless of the filters, reverse only when the new
side's filters pass, the trailed-SAR variant, and the D3 guards.

Short lengths (EMA 10, DMI 2/2) let a few dozen hand-built bars reach every state; each
test first checks with the indicator classes that the bars do what it relies on.
"""

from decimal import Decimal
from itertools import pairwise
from typing import Any

from kterminal.core.enums import SignalAction
from kterminal.domain.market import Bar
from kterminal.indicators import Sar
from kterminal.strategies.psar_ema200 import PsarEma200
from kterminal.strategy_engine import CloseReason, PositionEventKind
from kterminal.strategy_engine.model import OPEN_BEYOND_STOP
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

SMALL: dict[str, Any] = {"ma_slow_length": 10, "di_length": 2, "adx_smoothing": 2}

# flat, a slide (SAR flips down at 10), a rally (flips up at 19), a top, then a one-bar
# dip that flips the SAR down at 33 while the close stays above the EMA
WAVE = [100.0] * 10 + [100.0 - i for i in range(1, 8)] + [93 + 1.5 * i for i in range(1, 16)]
WAVE += [112.0, 110.0, 111.0]


def sars(bars: list[Bar]) -> tuple[list[float], list[float]]:
    """The SAR and its projection for the next bar, after every bar."""
    sar = Sar()
    values, projections = [], []
    for b in bars:
        values.append(sar.update(float(b.high), float(b.low), float(b.close)))
        projections.append(sar.projected())
    return values, projections


def price(value: float) -> Decimal:
    return XAUUSD.round_price(Decimal(repr(value)))


def test_flip_entries_exits_and_the_stop_at_the_signal_bars_sar() -> None:
    bars = path_bars(WAVE)
    sar, _ = sars(bars)
    result = run(PsarEma200, bars, params=SMALL)
    assert result.fault is None and result.rejected == []
    # 10: short; 19: exit short + long (reversal); 33: the long exits, the short side's
    # trend filter fails (close above the EMA): flat
    assert actions(result) == [(10, SHORT), (19, EXIT_SHORT), (19, LONG), (33, EXIT_LONG)]
    short, exit_short, long, exit_long = result.signals
    assert short.stop_loss == price(sar[10]) == Decimal("100.50")
    assert long.stop_loss == price(sar[19]) == Decimal("92.50")
    assert short.take_profit is None and long.take_profit is None
    assert (short.metadata["trigger"], short.metadata["pine_signal"]) == ("Short", "psShort")
    assert (exit_short.metadata["trigger"], exit_long.metadata["trigger"]) == ("ES", "EL")
    assert long.reason == "PSAR long — 200 EMA filtered"
    assert float(bars[33].close) < sar[33]  # the flip at 33 …
    assert float(bars[33].close) > long.metadata["ema"]  # … with the close above the EMA
    closed = of_kind(result, PositionEventKind.CLOSED)
    assert [(e.reason, e.price) for e in closed] == [
        (CloseReason.SIGNAL_EXIT, bars[20].open),
        (CloseReason.SIGNAL_EXIT, bars[34].open),
    ]
    assert [e.price for e in of_kind(result, PositionEventKind.OPENED)] == [
        bars[11].open,
        bars[20].open,
    ]


def test_a_weak_adx_blocks_entries() -> None:
    result = run(PsarEma200, path_bars(WAVE), params={**SMALL, "threshold": 100})
    assert result.signals == []


def test_the_protective_stop_closes_the_position_before_a_flip() -> None:
    """D5 main: the stop stays at the signal bar's SAR (92.50). A bar trading through it
    closes the long at the stop inside the bar; the SAR flip that bar's close confirms
    would only have exited at the next open, and finds the strategy already flat."""
    rows = path_bars(WAVE[:20])
    fill = (97.5, 98.0, 97.0, 98.0)  # the long fills at this open
    crash = (98.0, 98.5, 92.0, 97.9)  # through 92.50
    bars = rows + make_bars([fill, crash], start=rows[-1].close_time)
    sar, _ = sars(bars)
    assert float(bars[21].close) < sar[21]  # the crash bar also flips the SAR down
    result = run(PsarEma200, bars, params=SMALL)
    closed = of_kind(result, PositionEventKind.CLOSED)
    assert (closed[-1].reason, closed[-1].price) == (CloseReason.STOP_LOSS, Decimal("92.50"))
    assert [a for i, a in actions(result) if i == 21] == []  # flat: nothing to exit


def test_trailed_stop_follows_the_projected_sar() -> None:
    bars = path_bars(WAVE)
    _, projected = sars(bars)
    result = run(PsarEma200, bars, params={**SMALL, "stop_mode": "trail"})
    short = result.signals[0]
    assert (index_of(short), short.signal) == (10, SHORT)
    assert short.stop_loss == price(projected[10])  # the level whose touch flips bar 11
    moves = [s for s in result.signals if s.signal is MOVE_SL and index_of(s) < 19]
    assert [index_of(s) for s in moves] == list(range(11, 19))
    assert [s.stop_loss for s in moves] == [price(projected[i]) for i in range(11, 19)]
    stops = [short.stop_loss] + [s.stop_loss for s in moves]
    assert all(b < a for a, b in pairwise(stops))  # a short's stop only comes down
    # bar 19 trades through the trailed stop (the bar that also flips the SAR)
    closed = of_kind(result, PositionEventKind.CLOSED)
    assert (closed[0].reason, closed[0].price) == (CloseReason.STOP_LOSS, price(projected[18]))
    # already flat when bar 19 is decided: no exit, only the new long on its projection
    later = [(i, a) for i, a in actions(result) if i >= 19 and a is not MOVE_SL]
    assert later[0] == (19, LONG)
    assert result.signals[len(moves) + 1].stop_loss == price(projected[19])


def test_a_trailed_stop_on_the_wrong_side_skips_the_entry() -> None:
    """D3: here the projected SAR of the flip bar is above its close, so a long cannot
    carry it; the fixed-SAR variant trades the same flip."""
    rows = path_bars([100.0] * 30 + [100.0 + i for i in range(1, 21)] + [118.0, 114.0])
    bars = rows + make_bars([(114.0, 130.0, 109.0, 109.05)], start=rows[-1].close_time)
    params = {**SMALL, "ma_slow_length": 50}
    sar, projected = sars(bars)
    assert sar[52] < 109.05 < projected[52]
    trailed = run(PsarEma200, bars, params={**params, "stop_mode": "trail"})
    skipped = [s for s in trailed.signals if index_of(s) == 52]
    assert [(s.signal, s.reason) for s in skipped] == [(NO_TRADE, "STOP_WRONG_SIDE")]
    assert skipped[0].metadata["pine_signal"] == "psLong" and skipped[0].persist
    fixed = run(PsarEma200, bars, params=params)
    assert [(index_of(s), s.signal) for s in fixed.signals][-1] == (52, LONG)


def test_gap_guard_cancels_the_reversal_entry_but_the_exit_still_happens() -> None:
    bars = path_bars(WAVE[:20])
    gap = (92.0, 92.5, 91.5, 92.0)  # opens below the new long's stop (92.50)
    bars += make_bars([gap], start=bars[-1].close_time)
    result = run(PsarEma200, bars, params=SMALL)
    closed = of_kind(result, PositionEventKind.CLOSED)
    assert [(e.reason, e.price) for e in closed] == [(CloseReason.SIGNAL_EXIT, Decimal("92.0"))]
    cancelled = of_kind(result, PositionEventKind.ORDER_CANCELLED)
    assert [e.detail for e in cancelled] == [OPEN_BEYOND_STOP]


def test_runs_are_deterministic() -> None:
    bars = path_bars(WAVE + WAVE[::-1])
    for mode in ("sar", "trail"):
        params = {**SMALL, "stop_mode": mode}
        assert dumps(run(PsarEma200, bars, params=params)) == dumps(
            run(PsarEma200, bars, params=params)
        )
