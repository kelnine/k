"""The sliding-extreme engine behind ``extremes.py`` and ``pivots.py``."""

import math
from bisect import bisect_left

_COMPACT_AFTER = 256


class Extreme:
    """Running extreme over any suffix window of the bars since the last na.

    Keeps the classic monotonic list of candidates: a value is dropped once a
    newer value beats it (or, with ``newest_wins``, ties it). The extreme of
    the last ``n`` bars is then the first candidate inside the window, found by
    bisection, so fixed and per-bar window lengths share one O(log n) query.
    """

    __slots__ = ("_bars", "_capacity", "_is_max", "_newest_wins", "_start", "_values", "bar")

    def __init__(self, capacity: int, is_max: bool, newest_wins: bool) -> None:
        self._capacity = capacity
        self._is_max = is_max
        self._newest_wins = newest_wins
        self._bars: list[int] = []
        self._values: list[float] = []
        self._start = 0  # candidates before this index have left the longest window
        self.bar = -1  # index of the current bar

    def push(self, value: float) -> None:
        """Advance one bar; a na value empties the window."""
        self.bar += 1
        if not math.isfinite(value):
            self._bars.clear()
            self._values.clear()
            self._start = 0
            return
        bars, values = self._bars, self._values
        while len(values) > self._start and self._dominated(values[-1], value):
            bars.pop()
            values.pop()
        bars.append(self.bar)
        values.append(value)
        oldest = self.bar - self._capacity + 1
        while bars[self._start] < oldest:
            self._start += 1
        if self._start >= _COMPACT_AFTER and self._start * 2 >= len(bars):
            del bars[: self._start]
            del values[: self._start]
            self._start = 0

    def _dominated(self, older: float, newer: float) -> bool:
        if self._is_max:
            return older <= newer if self._newest_wins else older < newer
        return older >= newer if self._newest_wins else older > newer

    def query(self, length: int) -> tuple[float, int]:
        """``(extreme, offset)`` over the last ``length`` bars; the current bar must be non-na."""
        index = bisect_left(self._bars, self.bar - length + 1, self._start)
        return self._values[index], self.bar - self._bars[index]
