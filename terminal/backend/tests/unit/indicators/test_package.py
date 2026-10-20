"""Package-level guarantees: determinism, isolation, the public API, use inside a strategy."""

import math
from decimal import Decimal
from typing import Any

import numpy as np
import pytest

import kterminal.indicators as ind
from kterminal.core.enums import SignalAction
from kterminal.domain.market import Bar
from kterminal.strategy_engine import SignalOutput, Strategy, StrategyMeta, StrategyParams
from kterminal.strategy_engine.testing import run_strategy
from tests.fixtures.instruments import XAUUSD, bars


def _walk(n: int, seed: int) -> tuple[list[float], list[float], list[float], list[float]]:
    rng = np.random.default_rng(seed)
    price = 2650.0
    highs, lows, closes, volumes = [], [], [], []
    for _ in range(n):
        price += float(rng.choice([-1.5, -0.5, -0.25, 0.0, 0.25, 0.5, 1.5]))
        high = price + float(rng.choice([0.0, 0.25, 1.0]))
        low = price - float(rng.choice([0.0, 0.25, 1.0]))
        highs.append(high)
        lows.append(low)
        closes.append(float(rng.uniform(low, high)))
        volumes.append(float(rng.integers(0, 501)))
    return highs, lows, closes, volumes


def _run_everything(seed: int) -> list[Any]:
    """Every indicator over the same 1,500 bars; returns all outputs."""
    highs, lows, closes, volumes = _walk(1_500, seed)
    anchors = [i % 288 == 0 for i in range(len(closes))]
    hlc3 = [(h + lo + c) / 3 for h, lo, c in zip(highs, lows, closes, strict=True)]
    outputs: list[Any] = []
    for factory in (ind.Sma, ind.Ema, ind.Rma, ind.Sum, ind.Stdev, ind.Rsi, ind.Highest):
        outputs.append(ind.feed(factory(14).update, closes))
    for factory2 in (ind.HighestBars, ind.Lowest, ind.LowestBars):
        outputs.append(ind.feed(factory2(26).update, lows))
    outputs.append(ind.feed(ind.PivotHigh(5, 5).update, highs))
    outputs.append(ind.feed(ind.PivotLow(10, 3).update, lows))
    outputs.append(ind.feed(ind.Atr(14).update, highs, lows, closes))
    outputs.append(ind.feed(ind.Dmi(14, 14).update, highs, lows, closes))
    outputs.append(ind.feed(ind.Sar().update, highs, lows, closes))
    outputs.append(ind.feed(ind.SuperTrend(3.0, 10).update, highs, lows, closes))
    outputs.append(ind.feed(ind.Macd().update, closes))
    outputs.append(ind.feed(ind.WaveTrend().update, hlc3))
    outputs.append(ind.feed(ind.Vwap().update, hlc3, volumes, anchors))
    outputs.append(ind.feed(ind.Crossover().update, closes, outputs[1]))
    outputs.append(ind.feed(ind.Cross().update, closes, outputs[1]))
    return outputs


def _canonical(value: Any) -> Any:
    if isinstance(value, float) and math.isnan(value):
        return "na"
    if isinstance(value, tuple):
        return tuple(_canonical(v) for v in value)
    return value


def test_identical_input_gives_identical_output() -> None:
    first = [[_canonical(v) for v in series] for series in _run_everything(seed=3)]
    second = [[_canonical(v) for v in series] for series in _run_everything(seed=3)]
    assert first == second
    other = [[_canonical(v) for v in series] for series in _run_everything(seed=4)]
    assert first != other


def test_instances_share_no_state() -> None:
    a, b = ind.Ema(3), ind.Ema(3)
    ind.feed(a.update, [1.0, 2.0, 3.0, 4.0])
    assert math.isnan(b.value)
    assert math.isnan(b.update(10.0))  # b is still warming up on its own first value
    assert a.update(10.0) == 6.5  # a continues from its own state: 3 + 0.5 * (10 - 3)


def test_feeding_in_batches_equals_feeding_at_once() -> None:
    _, _, closes, _ = _walk(200, seed=9)
    whole = ind.feed(ind.Rsi(14).update, closes)
    rsi = ind.Rsi(14)
    parts = ind.feed(rsi.update, closes[:77]) + ind.feed(rsi.update, closes[77:])
    assert [_canonical(v) for v in parts] == [_canonical(v) for v in whole]


def test_feed_needs_columns_of_equal_length() -> None:
    with pytest.raises(ValueError, match="at least one column"):
        ind.feed(ind.BarIndex().update)
    with pytest.raises(ValueError, match="shorter"):
        ind.feed(ind.Atr(2).update, [1.0, 2.0], [0.5], [1.0, 1.5])


def test_objects_use_slots() -> None:
    # no per-instance __dict__: a typo such as `ema.vale = 1` fails instead of hiding a bug
    for obj in (ind.Ema(2), ind.Highest(2), ind.PivotHigh(1, 1), ind.Sar(), ind.Vwap()):
        assert not hasattr(obj, "__dict__")
        with pytest.raises(AttributeError):
            obj.unknown_attribute = 1  # type: ignore[union-attr]


def test_public_api() -> None:
    assert sorted(ind.__all__) == sorted(set(ind.__all__))
    for name in ind.__all__:
        assert hasattr(ind, name), name


# ── inside a real strategy ───────────────────────────────────────────────────────────


class EmaCrossParams(StrategyParams):
    fast: int = 3
    slow: int = 6


class EmaCrossProbe(Strategy[EmaCrossParams]):
    """Indicators as per-instance state: created in on_start, updated once per closed bar."""

    meta = StrategyMeta(id="ema_cross_probe", name="EMA cross probe", version="1.0.0")
    Params = EmaCrossParams

    def on_start(self) -> None:
        self.fast = ind.Ema(self.params.fast)
        self.slow = ind.Ema(self.params.slow)
        self.atr = ind.Atr(3)
        self.cross_up = ind.Crossover()

    def on_bar(self, bar: Bar) -> SignalOutput:
        close = float(bar.close)
        fast = self.fast.update(close)
        slow = self.slow.update(close)
        atr = self.atr.update(float(bar.high), float(bar.low), close)
        if self.cross_up.update(fast, slow) and not ind.na(atr):
            stop = Decimal(repr(atr))
            return self.ctx.long(stop_loss=bar.close - stop, take_profit=bar.close + 2 * stop)
        return None


def test_indicators_work_as_strategy_state() -> None:
    rows = [(100.0 - i, 101.0 - i, 99.0 - i, 100.0 - i) for i in range(10)]
    rows += [(90.0 + 2 * i, 91.0 + 2 * i, 89.0 + 2 * i, 90.5 + 2 * i) for i in range(10)]
    result = run_strategy(
        EmaCrossProbe, instrument=XAUUSD, bars=bars("XAUUSD", "5m", rows), timeframe="5m"
    )
    assert result.fault is None
    assert [s.signal for s in result.signals] == [SignalAction.LONG]
    (signal,) = result.signals
    assert signal.stop_loss is not None and signal.stop_loss < signal.entry  # type: ignore[operator]
