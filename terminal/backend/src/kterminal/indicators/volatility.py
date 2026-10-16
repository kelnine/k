"""Volatility: ``ta.variance``, ``ta.stdev``, ``ta.tr`` and ``ta.atr``."""

import math
from collections import deque

from kterminal.indicators._validate import check_int
from kterminal.indicators.averages import Rma

__all__ = ["Atr", "Stdev", "TrueRange", "Variance"]


class Variance:
    """Pine ``ta.variance(source, length, biased)``.

    With ``p`` = the sum and ``q`` = the sum of squares of the last ``length``
    non-na values and ``m = p / length``::

        biased   (default): max(0, q / length - m * m)            population variance
        unbiased          : max(0, q / (length - 1) - p * m / (length - 1))

    This is the one-pass form TradingView evaluates (not a two-pass sum of
    squared deviations), clamped at 0 so cancellation never yields a negative
    variance. Like TradingView's, it loses precision when the values are large
    and their spread tiny: around 1e8 a spread of 0.1 is below the rounding
    of the squares, and the result can be 0 or a few units instead of the
    true variance. Normalise such inputs first (script 4 takes the stdev of a
    0…1 normalised price). Window, warm-up and na handling as
    :class:`~kterminal.indicators.Sma` (na-compacted). An unbiased variance of
    length 1 is always na.
    """

    __slots__ = ("_squares", "_values", "biased", "length", "value")

    def __init__(self, length: int, biased: bool = True) -> None:
        self.length = check_int("length", length, 1)
        self.biased = biased
        self._values: deque[float] = deque(maxlen=length)
        self._squares: deque[float] = deque(maxlen=length)
        self.value = math.nan

    def update(self, source: float) -> float:
        self.value = math.nan
        if not math.isfinite(source):
            return self.value
        self._values.append(source)
        self._squares.append(source * source)
        if len(self._values) < self.length or (not self.biased and self.length == 1):
            return self.value
        n = self.length
        total = math.fsum(self._values)
        squares = math.fsum(self._squares)
        mean = total / n
        if self.biased:
            variance = squares / n - mean * mean
        else:
            variance = squares / (n - 1) - total * mean / (n - 1)
        self.value = max(0.0, variance)
        return self.value


class Stdev:
    """Pine ``ta.stdev(source, length, biased=true)``: the square root of :class:`Variance`.

    The default is the **population** (biased) standard deviation, unlike
    pandas' default ``ddof=1``. A constant series of moderate magnitude gives
    exactly 0 (see :class:`Variance` for the precision limit).
    """

    __slots__ = ("_variance", "length", "value")

    def __init__(self, length: int, biased: bool = True) -> None:
        self._variance = Variance(length, biased)
        self.length = length
        self.value = math.nan

    def update(self, source: float) -> float:
        variance = self._variance.update(source)
        self.value = math.sqrt(variance) if math.isfinite(variance) else math.nan
        return self.value


class TrueRange:
    """Pine ``ta.tr`` / ``ta.tr(handle_na)``: the true range of a bar.

    ``max(high - low, |high - close[1]|, |low - close[1]|)``.

    ``close[1]`` is the close passed on the previous update. On the first bar
    (or after a na close) it is na: ``ta.tr`` — i.e. ``handle_na=False``, the
    form ``ta.dmi`` uses — then returns na, while ``handle_na=True`` — the form
    ``ta.atr`` uses — returns ``high - low``. A na high or low gives na.
    """

    __slots__ = ("_previous_close", "handle_na", "value")

    def __init__(self, handle_na: bool = False) -> None:
        self.handle_na = handle_na
        self._previous_close = math.nan
        self.value = math.nan

    def update(self, high: float, low: float, close: float) -> float:
        previous = self._previous_close
        self._previous_close = close
        if not (math.isfinite(high) and math.isfinite(low)):
            self.value = math.nan
        elif not math.isfinite(previous):
            self.value = high - low if self.handle_na else math.nan
        else:
            self.value = max(high - low, abs(high - previous), abs(low - previous))
        return self.value


class Atr:
    """Pine ``ta.atr(length)``: :class:`Rma` of ``ta.tr(true)``.

    The first bar's true range is ``high - low``, so the first ATR value is on
    bar index ``length - 1``: the simple average of the first ``length`` true
    ranges. Afterwards Wilder smoothing. Ports that use ``nz(ta.atr(14))``
    see 0 during that warm-up.
    """

    __slots__ = ("_rma", "_true_range", "length", "value")

    def __init__(self, length: int) -> None:
        self._rma = Rma(length)
        self.length = length
        self._true_range = TrueRange(handle_na=True)
        self.value = math.nan

    def update(self, high: float, low: float, close: float) -> float:
        self.value = self._rma.update(self._true_range.update(high, low, close))
        return self.value
