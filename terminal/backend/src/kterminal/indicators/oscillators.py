"""Oscillators: ``ta.rsi``, ``ta.macd`` and the LazyBear WaveTrend used by Jetstream v2."""

import math
from typing import NamedTuple

from kterminal.indicators._validate import check_int
from kterminal.indicators.averages import Ema, Rma, Sma
from kterminal.indicators.pine import ne

__all__ = ["Macd", "MacdValue", "Rsi", "WaveTrend", "WaveTrendValue"]

# Pine's comparison tolerance; RSI treats a smoothed side at or below it as zero.
_ZERO = 1e-10


class Rsi:
    """Pine ``ta.rsi(source, length)``: Wilder's relative strength index, 0 … 100.

    ``up = rma(max(change, 0), length)``, ``down = rma(max(-change, 0), length)``
    where ``change`` is ``source`` minus the previous non-na source. The first
    bar has no change, so the first value is on bar index ``length`` (the
    seed is the simple average of the first ``length`` changes).

    Result: 100 when ``down <= 1e-10`` (no losses — tested first, so a
    constant series is 100), 0 when ``up <= 1e-10``, else
    ``100 - 100 / (1 + up / down)``. The zero test uses Pine's 1e-10 tolerance
    (as reported measured by PyneCore), not exact zero. A na source returns
    na and is skipped.
    """

    __slots__ = ("_down", "_previous", "_up", "length", "value")

    def __init__(self, length: int) -> None:
        self.length = check_int("length", length, 1)
        self._up = Rma(length)
        self._down = Rma(length)
        self._previous = math.nan
        self.value = math.nan

    def update(self, source: float) -> float:
        self.value = math.nan
        if not math.isfinite(source):
            return self.value
        previous, self._previous = self._previous, source
        if math.isnan(previous):
            return self.value
        up = self._up.update(max(source - previous, 0.0))
        down = self._down.update(max(previous - source, 0.0))
        if math.isnan(up) or math.isnan(down):
            return self.value
        if down <= _ZERO:
            self.value = 100.0
        elif up <= _ZERO:
            self.value = 0.0
        else:
            self.value = 100.0 - 100.0 / (1.0 + up / down)
        return self.value


class MacdValue(NamedTuple):
    macd: float
    signal: float
    hist: float


class Macd:
    """Pine ``ta.macd(source, fast, slow, signal)`` → ``(macd, signal, hist)``.

    ``macd = ema(source, fast) - ema(source, slow)``; ``signal = ema(macd,
    signal)``; ``hist = macd - signal``. All three are na until the slow EMA
    exists; ``signal`` and ``hist`` until ``signal`` further MACD values.
    Script 9's "pulse" (EMA5 − EMA60, signal EMA20) is ``Macd(5, 60, 20)``.
    """

    __slots__ = ("_fast", "_signal", "_slow", "value")

    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9) -> None:
        self._fast = Ema(fast)
        self._slow = Ema(slow)
        self._signal = Ema(signal)
        self.value = MacdValue(math.nan, math.nan, math.nan)

    def update(self, source: float) -> MacdValue:
        fast = self._fast.update(source)
        slow = self._slow.update(source)
        if math.isnan(fast) or math.isnan(slow):
            self.value = MacdValue(math.nan, math.nan, math.nan)
            return self.value
        macd = fast - slow
        signal = self._signal.update(macd)
        self.value = MacdValue(macd, signal, macd - signal)
        return self.value


class WaveTrendValue(NamedTuple):
    wt1: float
    wt2: float


class WaveTrend:
    """WaveTrend (LazyBear), exactly as Jetstream v2 computes it (script 10, L147-151)::

        esa = ta.ema(src, n1)
        de  = ta.ema(math.abs(src - esa), n1)
        ci  = de != 0 ? (src - esa) / (0.015 * de) : 0
        wt1 = ta.ema(ci, n2)
        wt2 = ta.sma(wt1, sigLen)

    The script passes ``hlc3`` as ``src`` (defaults n1 = 10, n2 = 21,
    sigLen = 4). ``de != 0`` is a Pine comparison: false while ``de`` is na
    (warm-up) and when ``|de| <= 1e-10``, so ``ci`` is **0, not na**, from the
    first bar on and ``wt1``'s EMA is seeded with those zeros — a NumPy port
    that propagates NaN starts later and differs.
    """

    __slots__ = ("_ci_ema", "_de_ema", "_esa_ema", "_signal", "value")

    def __init__(
        self, channel_length: int = 10, average_length: int = 21, signal_length: int = 4
    ) -> None:
        self._esa_ema = Ema(channel_length)
        self._de_ema = Ema(channel_length)
        self._ci_ema = Ema(average_length)
        self._signal = Sma(signal_length)
        self.value = WaveTrendValue(math.nan, math.nan)

    def update(self, source: float) -> WaveTrendValue:
        esa = self._esa_ema.update(source)
        de = self._de_ema.update(abs(source - esa))
        ci = (source - esa) / (0.015 * de) if ne(de, 0.0) else 0.0
        wt1 = self._ci_ema.update(ci)
        self.value = WaveTrendValue(wt1, self._signal.update(wt1))
        return self.value
