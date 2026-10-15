"""The levels each model sweeps: Model A's untaken 15m swings, Model B's 08:00 range.

* :class:`LiquiditySwings` — ``f_liqSwings(aSwing)`` (L197-222), evaluated on every
  closed 15m bar like ``request.security(syminfo.tickerid, "15", f_liqSwings(aSwing),
  lookahead = barmerge.lookahead_on)`` (L616). The function returns ``[lastH[1],
  lastL[1]]``, so a 1m bar inside 15m bar *k* reads the state after bar *k − 1*: the
  strategy feeds this object the bars of ``ctx.series("15m", tradingview_lag=True)``
  and reads :attr:`last_high` / :attr:`last_low` (docs/05 §5.2.1).
* :class:`RangeCandle` — Model B's high/low of the 1m bars opening in ``bRange``
  (08:00-09:00 New York), accumulated on chart bars (L786-794), with the 24-hour
  freshness rule of L796.
"""

import math
from collections import deque
from datetime import datetime, timedelta

from kterminal.indicators import PivotHigh, PivotLow, gt, lt, na

LIQUIDITY_CAP = 50  # hs/ls keep at most 50 levels (L203-210)
RANGE_FRESH = timedelta(milliseconds=86_400_000)  # bFresh: time - bT0 < 86400000 (L796)

NAN = math.nan


class LiquiditySwings:
    """``f_liqSwings(len)`` (L197-222) on the bars of one higher timeframe.

    Every bar: a confirmed ``ta.pivothigh(high, len, len)`` / ``ta.pivotlow`` is pushed
    (the oldest dropped beyond 50), then every stored high that this bar's high exceeds
    (``high > level``, strictly) is removed, lows mirror it. ``last_high`` / ``last_low``
    are the most recently pushed survivors (``hs.last()``), na when none is left. Each
    level is kept with the open time of its pivot bar, for signal metadata.
    """

    __slots__ = ("_opens", "_pivot_high", "_pivot_low", "highs", "length", "lows")

    def __init__(self, length: int) -> None:
        self.length = length
        self._pivot_high = PivotHigh(length, length)
        self._pivot_low = PivotLow(length, length)
        self._opens: deque[datetime] = deque(maxlen=length + 1)  # pivot bar = [length]
        self.highs: list[tuple[float, datetime]] = []  # oldest first
        self.lows: list[tuple[float, datetime]] = []

    def update(self, high: float, low: float, open_time: datetime) -> None:
        self._opens.append(open_time)
        ph = self._pivot_high.update(high)  # L200
        pl = self._pivot_low.update(low)  # L201
        pivot_time = self._opens[0]
        if not na(ph):  # L202-205
            self.highs.append((ph, pivot_time))
            if len(self.highs) > LIQUIDITY_CAP:
                del self.highs[0]
        if not na(pl):  # L206-209
            self.lows.append((pl, pivot_time))
            if len(self.lows) > LIQUIDITY_CAP:
                del self.lows[0]
        self.highs = [lv for lv in self.highs if not gt(high, lv[0])]  # L210-214
        self.lows = [lv for lv in self.lows if not lt(low, lv[0])]  # L215-219

    @property
    def last_high(self) -> float:
        """``lastH``: the most recent untaken swing high, na if none (L220)."""
        return self.highs[-1][0] if self.highs else NAN

    @property
    def last_low(self) -> float:
        """``lastL``: the most recent untaken swing low, na if none (L221)."""
        return self.lows[-1][0] if self.lows else NAN

    @property
    def last_high_time(self) -> datetime | None:
        return self.highs[-1][1] if self.highs else None

    @property
    def last_low_time(self) -> datetime | None:
        return self.lows[-1][1] if self.lows else None


class RangeCandle:
    """Model B's ``bHi``/``bLo``/``bT0`` (L786-794): reset on the first bar inside the
    range session (``inBR and not inBR[1]``), extended on the following ones."""

    __slots__ = ("bars", "high", "low", "start")

    def __init__(self) -> None:
        self.high = NAN
        self.low = NAN
        self.start: datetime | None = None  # bT0: open time of the range's first bar
        self.bars = 0

    def update(self, high: float, low: float, open_time: datetime, *, first: bool) -> None:
        """A bar inside the range session; ``first`` when the previous bar was outside."""
        if first:
            self.high, self.low, self.start, self.bars = high, low, open_time, 1
        else:
            self.high = _pine_max(self.high, high)
            self.low = _pine_min(self.low, low)
            self.bars += 1

    def fresh(self, at: datetime) -> bool:
        """``bFresh`` (L796): a range exists and its first bar opened < 24 h before ``at``."""
        return self.start is not None and at - self.start < RANGE_FRESH


def _pine_max(a: float, b: float) -> float:
    """``math.max``: na if either argument is na."""
    return NAN if na(a) or na(b) else max(a, b)


def _pine_min(a: float, b: float) -> float:
    """``math.min``: na if either argument is na."""
    return NAN if na(a) or na(b) else min(a, b)
