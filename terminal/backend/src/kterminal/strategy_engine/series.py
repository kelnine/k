"""Bar series handed to strategies.

Each strategy instance owns its own series buffers (built from the shared,
immutable :class:`~kterminal.domain.market.Bar` objects), so nothing a
strategy does to its data can reach another instance. The NumPy arrays it
reads are views flagged read-only, which turns accidental in-place
modification (a classic indicator bug) into an immediate error.
"""

from collections import deque
from collections.abc import Sequence
from datetime import datetime

import numpy as np
from numpy.typing import NDArray

from kterminal.domain.market import Bar
from kterminal.domain.timeframes import Timeframe

DEFAULT_MAX_BARS = 5_000

_FIELDS = ("open", "high", "low", "close", "volume")


class BarSeries:
    """Closed bars of one instrument and timeframe, oldest → newest (``[-1]`` is the latest)."""

    def __init__(self, instrument: str, timeframe: Timeframe, max_bars: int = DEFAULT_MAX_BARS):
        if max_bars < 1:
            raise ValueError("max_bars must be >= 1")
        self.instrument = instrument
        self.timeframe = timeframe
        self.max_bars = max_bars
        self._capacity = max_bars * 2
        self._data = {name: np.empty(self._capacity, dtype=np.float64) for name in _FIELDS}
        self._times = np.empty(self._capacity, dtype="datetime64[us]")
        self._start = 0
        self._end = 0
        self._bars: deque[Bar] = deque(maxlen=max_bars)

    # ── mutation (framework only) ───────────────────────────────────────────
    def _append(self, bar: Bar) -> None:
        if bar.instrument != self.instrument or bar.timeframe != self.timeframe:
            raise ValueError(
                f"bar {bar.instrument} {bar.timeframe} does not belong to series "
                f"{self.instrument} {self.timeframe}"
            )
        if self._bars and bar.open_time <= self._bars[-1].open_time:
            raise ValueError(
                f"bars must arrive in order: {bar.open_time.isoformat()} after "
                f"{self._bars[-1].open_time.isoformat()} ({self.instrument} {self.timeframe})"
            )
        if self._end == self._capacity:  # compact: keep the newest max_bars - 1, amortised O(1)
            keep = self.max_bars - 1
            for arr in (*self._data.values(), self._times):
                arr[:keep] = arr[self._end - keep : self._end]
            self._start, self._end = 0, keep
        for name in _FIELDS:
            self._data[name][self._end] = float(getattr(bar, name))
        self._times[self._end] = np.datetime64(bar.open_time.replace(tzinfo=None), "us")
        self._end += 1
        if self._end - self._start > self.max_bars:
            self._start += 1
        self._bars.append(bar)

    # ── read access ─────────────────────────────────────────────────────────
    def __len__(self) -> int:
        return self._end - self._start

    def _view(self, arr: NDArray[np.float64]) -> NDArray[np.float64]:
        view = arr[self._start : self._end]
        view.flags.writeable = False
        return view

    @property
    def open(self) -> NDArray[np.float64]:
        return self._view(self._data["open"])

    @property
    def high(self) -> NDArray[np.float64]:
        return self._view(self._data["high"])

    @property
    def low(self) -> NDArray[np.float64]:
        return self._view(self._data["low"])

    @property
    def close(self) -> NDArray[np.float64]:
        return self._view(self._data["close"])

    @property
    def volume(self) -> NDArray[np.float64]:
        return self._view(self._data["volume"])

    @property
    def open_times(self) -> NDArray[np.datetime64]:
        """Bar open times as naive ``datetime64[us]`` in UTC."""
        view = self._times[self._start : self._end]
        view.flags.writeable = False
        return view

    def bar(self, index: int = -1) -> Bar:
        """The ``Bar`` object at ``index`` (Python indexing; ``-1`` is the latest)."""
        return self._bars[index]

    def last(self, count: int) -> Sequence[Bar]:
        if count < 0:
            raise ValueError("count must be >= 0")
        if count == 0:
            return ()
        return tuple(self._bars)[-count:]

    @property
    def latest(self) -> Bar | None:
        return self._bars[-1] if self._bars else None

    def closed_by(self, ts: datetime) -> "SeriesView":
        """The bars that had closed at or before ``ts`` (a read-only view, no copy)."""
        hidden = 0
        for bar in reversed(self._bars):
            if bar.close_time <= ts:
                break
            hidden += 1
        return SeriesView(self, hidden)

    def __repr__(self) -> str:
        return f"BarSeries({self.instrument} {self.timeframe}, {len(self)} bars)"


class SeriesView:
    """A :class:`BarSeries` without its newest ``hidden`` bars, with the same read API.

    Returned by ``ctx.series(tf, tradingview_lag=True)``: the series as TradingView's
    ``request.security(…, expr[1], lookahead_on)`` sees it. It reads the live series'
    buffers, so it is valid for the bar being evaluated only — do not keep it.
    """

    __slots__ = ("_hidden", "_series")

    def __init__(self, series: BarSeries, hidden: int) -> None:
        if not 0 <= hidden <= len(series):
            raise ValueError(f"cannot hide {hidden} of {len(series)} bars")
        self._series = series
        self._hidden = hidden

    @property
    def instrument(self) -> str:
        return self._series.instrument

    @property
    def timeframe(self) -> Timeframe:
        return self._series.timeframe

    @property
    def hidden(self) -> int:
        """How many of the series' newest bars this view leaves out."""
        return self._hidden

    def __len__(self) -> int:
        return len(self._series) - self._hidden

    def _cut[A: np.generic](self, arr: NDArray[A]) -> NDArray[A]:
        return arr[: len(arr) - self._hidden]  # a view of a read-only view stays read-only

    @property
    def open(self) -> NDArray[np.float64]:
        return self._cut(self._series.open)

    @property
    def high(self) -> NDArray[np.float64]:
        return self._cut(self._series.high)

    @property
    def low(self) -> NDArray[np.float64]:
        return self._cut(self._series.low)

    @property
    def close(self) -> NDArray[np.float64]:
        return self._cut(self._series.close)

    @property
    def volume(self) -> NDArray[np.float64]:
        return self._cut(self._series.volume)

    @property
    def open_times(self) -> NDArray[np.datetime64]:
        return self._cut(self._series.open_times)

    def bar(self, index: int = -1) -> Bar:
        """The ``Bar`` at ``index`` of the visible bars (``-1`` is the latest visible)."""
        size = len(self)
        if not -size <= index < size:
            raise IndexError(f"bar index {index} out of range ({size} visible bars)")
        return self._series.bar(index - self._hidden if index < 0 else index)

    def last(self, count: int) -> Sequence[Bar]:
        if count < 0:
            raise ValueError("count must be >= 0")
        take = min(count, len(self))
        if take == 0:
            return ()
        return tuple(self._series.last(take + self._hidden))[:take]

    @property
    def latest(self) -> Bar | None:
        return self.bar(-1) if len(self) else None

    def __repr__(self) -> str:
        return (
            f"SeriesView({self.instrument} {self.timeframe}, {len(self)} bars, "
            f"{self._hidden} hidden)"
        )
