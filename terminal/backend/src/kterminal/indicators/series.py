"""Series bookkeeping: ``x[i]``, ``bar_index``, ``ta.change``, ``ta.barssince``,
``ta.valuewhen`` and ``ta.cum``.

Each object is the state of one Pine call site and must be updated exactly
once per bar, from the first bar on (call it even on bars where the result
is not needed — a Pine built-in inside an ``if`` sees only the bars it runs
on, and so does this object).
"""

import math
from collections import deque

from kterminal.indicators._validate import check_int

__all__ = ["BarIndex", "BarsSince", "Change", "Cum", "History", "ValueWhen"]


class History:
    """Pine's history-referencing operator ``x[i]`` for one series.

    ``h.update(x)`` records this bar's value; ``h[0]`` is it, ``h[1]`` the
    previous bar's, and so on. An offset beyond the recorded history (or
    beyond ``maxlen - 1``) is na, as in Pine. ``maxlen`` is the deepest
    offset the strategy reads plus one.
    """

    __slots__ = ("_values", "maxlen")

    def __init__(self, maxlen: int) -> None:
        self.maxlen = check_int("maxlen", maxlen, 1)
        self._values: deque[float] = deque(maxlen=maxlen)

    def update(self, value: float) -> float:
        self._values.append(value)
        return value

    def __getitem__(self, offset: int) -> float:
        if offset < 0:
            raise IndexError("Pine history offsets are >= 0 (x[0] is the current bar)")
        if offset >= len(self._values):
            return math.nan
        return self._values[-1 - offset]

    def __len__(self) -> int:
        return len(self._values)

    @property
    def value(self) -> float:
        """The current bar's value (``x[0]``), na before the first update."""
        return self[0]


class BarIndex:
    """Pine ``bar_index``: 0 on the first bar, +1 per update. ``value`` is -1 before."""

    __slots__ = ("value",)

    def __init__(self) -> None:
        self.value = -1

    def update(self) -> int:
        self.value += 1
        return self.value


class Change:
    """Pine ``ta.change(source, length)``: ``source - source[length]``.

    na while fewer than ``length`` earlier bars exist and whenever either
    value is na. The history is the raw bar-by-bar history, na bars included
    (unlike the moving averages, which skip na). Use it on numeric series;
    Pine's ``ta.change(direction)`` of an int ``±1`` series gives ``±2`` on a
    flip and 0 otherwise.
    """

    __slots__ = ("_history", "length", "value")

    def __init__(self, length: int = 1) -> None:
        self.length = check_int("length", length, 1)
        self._history = History(length + 1)
        self.value = math.nan

    def update(self, source: float) -> float:
        self._history.update(source)
        previous = self._history[self.length]
        if math.isfinite(source) and math.isfinite(previous):
            self.value = source - previous
        else:
            self.value = math.nan
        return self.value


class BarsSince:
    """Pine ``ta.barssince(condition)``: bars since the condition was last true.

    0 on a bar where it is true, then 1, 2, …; na until it has been true
    once. Returned as a float (na = ``nan``) like every value in this package.
    """

    __slots__ = ("_count", "value")

    def __init__(self) -> None:
        self._count = -1
        self.value = math.nan

    def update(self, condition: bool) -> float:
        if condition:
            self._count = 0
        elif self._count >= 0:
            self._count += 1
        self.value = float(self._count) if self._count >= 0 else math.nan
        return self.value


class ValueWhen:
    """Pine ``ta.valuewhen(condition, source, occurrence)``.

    The value ``source`` had on the ``occurrence``-th most recent bar where
    ``condition`` was true (0 = the latest, which may be the current bar);
    na until that many occurrences have happened. A na ``source`` on a true
    bar is recorded as na and still counts as an occurrence. The value is
    held across the bars where the condition is false.
    """

    __slots__ = ("_values", "occurrence", "value")

    def __init__(self, occurrence: int = 0) -> None:
        self.occurrence = check_int("occurrence", occurrence, 0)
        self._values: deque[float] = deque(maxlen=occurrence + 1)
        self.value = math.nan

    def update(self, condition: bool, source: float) -> float:
        if condition:
            self._values.append(source)
        self.value = self._values[0] if len(self._values) > self.occurrence else math.nan
        return self.value


class Cum:
    """Pine ``ta.cum(source)``: the running total of ``source`` since the first bar.

    A na ``source`` returns na on that bar and adds nothing; the total carries
    on afterwards. Plain double accumulation, as Pine's ``var x += source``.
    """

    __slots__ = ("_total", "value")

    def __init__(self) -> None:
        self._total = 0.0
        self.value = math.nan

    def update(self, source: float) -> float:
        if math.isfinite(source):
            self._total += source
            self.value = self._total
        else:
            self.value = math.nan
        return self.value
