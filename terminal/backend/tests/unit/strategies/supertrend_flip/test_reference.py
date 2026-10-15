"""The SuperTrend port against the flips computed directly from the indicator classes, on
long synthetic runs: an entry on every (strong) flip with the D5 stop, an exit on every
flip that meets an opposite position, nothing else (apart from trailing stop moves)."""

from datetime import datetime
from decimal import Decimal
from typing import Any

import pytest

from kterminal.core.enums import Direction, SignalAction
from kterminal.domain.market import Bar
from kterminal.domain.timeframes import Timeframe
from kterminal.indicators import SuperTrend, WaveTrend
from kterminal.marketdata.synthetic import synthetic_bars
from kterminal.strategies.supertrend_flip import SuperTrendFlip, SuperTrendFlipParams
from tests.fixtures.instruments import T0, XAUUSD
from tests.unit.strategies.pine_port_support import SESSIONS, positions_at_decisions, run


def gold(seed: int, count: int = 2_000) -> list[Bar]:
    return list(
        synthetic_bars(
            "XAUUSD",
            start=T0,
            count=count,
            start_price=Decimal("2650.00"),
            tick_size=Decimal("0.01"),
            timeframe=Timeframe.parse("15m"),
            seed=seed,
            volatility=0.002,
            regime_change_probability=0.02,
            is_open=SESSIONS.calendar("metals_otc").is_open,
        )
    )


Flips = dict[int, tuple[bool, bool, float]]


def reference_flips(bars: list[Bar], p: SuperTrendFlipParams) -> Flips:
    """``{bar: (buy, strong, D5 stop)}`` for every flip (``ta.change(dir) != 0``)."""
    supertrend = SuperTrend(p.mult, p.atr_len)
    wavetrend = WaveTrend(p.n1, p.n2, p.sig_len)
    out: dict[int, tuple[bool, bool, float]] = {}
    previous: int | None = None
    for i, bar in enumerate(bars):
        h, lo, c = float(bar.high), float(bar.low), float(bar.close)
        line, direction = supertrend.update(h, lo, c)
        wt1 = wavetrend.update((h + lo + c) / 3).wt1
        if previous is not None and direction != previous:
            buy = direction == -1
            strong = wt1 < -1e-10 if buy else wt1 > 1e-10
            offset = p.stop_atr_mult * supertrend.atr
            out[i] = (buy, strong, line - offset if buy else line + offset)
        previous = direction
    return out


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"signals": "strong"},
        {"trail_stop": True, "stop_atr_mult": 0.0},
        {"atr_len": 5, "mult": 2.0, "n1": 6, "n2": 12, "signals": "strong"},
    ],
    ids=["all", "strong", "trail", "short-lengths-strong"],
)
@pytest.mark.parametrize("seed", [4, 5])
def test_port_matches_the_flips(params: dict[str, Any], seed: int) -> None:
    bars = gold(seed)
    p = SuperTrendFlipParams.model_validate(params)
    result = run(SuperTrendFlip, bars, params=params, timeframe="15m")
    assert result.fault is None and result.rejected == []
    expected = reference_flips(bars, p)
    index: dict[datetime | None, int] = {bar.open_time: i for i, bar in enumerate(bars)}
    held = positions_at_decisions(bars, result.events)

    entries = {index[s.bar_time]: s for s in result.signals if s.signal.is_entry}
    traded = {i: f for i, f in expected.items() if p.signals == "all" or f[1]}
    assert sorted(entries) == sorted(traded)
    assert len(traded) >= 10
    for i, signal in entries.items():
        buy, _, stop = traded[i]
        assert signal.signal is (SignalAction.LONG if buy else SignalAction.SHORT)
        assert signal.stop_loss == XAUUSD.round_price(Decimal(repr(stop)))

    exits = [(index[s.bar_time], s.signal) for s in result.signals if s.signal.is_exit]
    expected_exits = [
        (i, SignalAction.EXIT_SHORT if buy else SignalAction.EXIT_LONG)
        for i, (buy, _, _) in sorted(expected.items())
        if held[i] is (Direction.SHORT if buy else Direction.LONG)
    ]
    assert exits == expected_exits
    moves = [s for s in result.signals if s.signal is SignalAction.MOVE_SL]
    assert bool(moves) == p.trail_stop
    assert {s.signal for s in result.signals} <= {
        SignalAction.LONG,
        SignalAction.SHORT,
        SignalAction.EXIT_LONG,
        SignalAction.EXIT_SHORT,
        SignalAction.MOVE_SL,
    }
