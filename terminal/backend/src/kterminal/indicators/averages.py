"""Moving sums and averages: ``math.sum``, ``ta.sma``, ``ta.ema``, ``ta.rma``.

na handling (all four): the window is *na-compacted*. A bar whose source is
na returns na and does not advance the state, so the result always covers
the last ``length`` non-na values. This matches Pine's remark "na values in
the source series are ignored; the function calculates on the length
quantity of non-na values". A leading run of na (an input that is itself
still warming up) therefore only delays the first value.

Sums are computed with ``math.fsum`` (exactly rounded), so the result does
not drift over long runs and is identical on every machine.
"""

import math
from collections import deque

from kterminal.indicators._validate import check_int

__all__ = ["Ema", "Rma", "Sma", "Sum"]


class _Window:
    """The last ``length`` non-na values."""

    __slots__ = ("_values", "length")

    def __init__(self, length: int) -> None:
        self.length = length
        self._values: deque[float] = deque(maxlen=length)

    def push(self, value: float) -> bool:
        """Add a non-na value; true once the window is full."""
        self._values.append(value)
        return len(self._values) == self.length

    def total(self) -> float:
        return math.fsum(self._values)


class Sum:
    """Pine ``math.sum(source, length)``: the sum of the last ``length`` values.

    Warm-up: na until ``length`` non-na values have been seen. A na source
    returns na and is not stored.
    """

    __slots__ = ("_window", "length", "value")

    def __init__(self, length: int) -> None:
        self.length = check_int("length", length, 1)
        self._window = _Window(length)
        self.value = math.nan

    def update(self, source: float) -> float:
        if not math.isfinite(source):
            self.value = math.nan
        elif self._window.push(source):
            self.value = self._window.total()
        else:
            self.value = math.nan
        return self.value


class Sma:
    """Pine ``ta.sma(source, length)``: arithmetic mean of the last ``length`` values.

    ``math.sum(source, length) / length``. Warm-up: the first value is on the
    ``length``-th non-na bar (bar index ``length - 1`` for a source that is
    never na). A na source returns na and is skipped. ``Sma(1)`` returns the
    source.
    """

    __slots__ = ("_window", "length", "value")

    def __init__(self, length: int) -> None:
        self.length = check_int("length", length, 1)
        self._window = _Window(length)
        self.value = math.nan

    def update(self, source: float) -> float:
        if not math.isfinite(source):
            self.value = math.nan
        elif self._window.push(source):
            self.value = self._window.total() / self.length
        else:
            self.value = math.nan
        return self.value


class Ema:
    """Pine ``ta.ema(source, length)``: exponential moving average, ``alpha = 2 / (length + 1)``.

    Seeding: na until ``length`` non-na values have been seen; the first value
    is their simple average (the SMA), then ``ema = prev + alpha * (source -
    prev)`` on every bar. (That step form is the one TradingView's output
    matches to the last bit; ``alpha * src + (1 - alpha) * prev`` is
    algebraically equal but rounds differently.) A na source returns na and
    leaves the average untouched. ``Ema(1)`` returns the source.

    The average converges from its seed: compare it with TradingView only
    after a warm-up of several times ``length`` bars.
    """

    __slots__ = ("_alpha", "_seed", "_state", "length", "value")

    def __init__(self, length: int) -> None:
        self.length = check_int("length", length, 1)
        self._alpha = 2.0 / (length + 1)
        self._seed = Sma(length)
        self._state = math.nan
        self.value = math.nan

    def update(self, source: float) -> float:
        if not math.isfinite(source):
            self.value = math.nan
            return self.value
        if self.length == 1:
            self._state = source  # exact; the step form could differ in the last bit
        elif math.isnan(self._state):
            self._state = self._seed.update(source)
        else:
            self._state = self._state + self._alpha * (source - self._state)
        self.value = self._state
        return self.value


class Rma:
    """Pine ``ta.rma(source, length)``: Wilder's moving average, ``alpha = 1 / length``.

    Seeding as :class:`Ema` (SMA of the first ``length`` non-na values), then
    ``rma = (prev * (length - 1) + source) / length``. Used by ``ta.atr``,
    ``ta.rsi`` and ``ta.dmi``. A na source returns na and leaves the average
    untouched. ``Rma(1)`` returns the source.
    """

    __slots__ = ("_seed", "_state", "length", "value")

    def __init__(self, length: int) -> None:
        self.length = check_int("length", length, 1)
        self._seed = Sma(length)
        self._state = math.nan
        self.value = math.nan

    def update(self, source: float) -> float:
        if not math.isfinite(source):
            self.value = math.nan
            return self.value
        if math.isnan(self._state):
            self._state = self._seed.update(source)
        else:
            self._state = (self._state * (self.length - 1) + source) / self.length
        self.value = self._state
        return self.value
