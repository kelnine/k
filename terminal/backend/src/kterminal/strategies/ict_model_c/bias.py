"""Model C's bias and draw on liquidity: ``f_pdBias(cLiqLen)`` on the bias timeframe.

``request.security(syminfo.tickerid, cBiasTF, f_pdBias(cLiqLen), lookahead =
barmerge.lookahead_on)`` (L617) evaluates the function on every bar of the bias
timeframe (60 by default) and returns ``[bias[1], bsl[1], ssl[1]]`` (L298): a 1m bar
inside HTF bar *k* reads the state after bar *k − 1*. The strategy feeds
:class:`PdBias` every bar of ``ctx.series(tf, tradingview_lag=True)``, whose newest bar
is *k − 1* on exactly those 1m bars, and reads :attr:`PdBias.bias`, :attr:`PdBias.bsl`
and :attr:`PdBias.ssl` (docs/05 §5.2.1).

Each HTF bar, in the script's order (L228-298):

1. every stored bullish FVG (newest first): a close below its bottom is a bearish
   event and removes it; otherwise a wick to its top with a close at or above its
   midpoint is a bullish event. Bearish FVGs mirror it;
2. only bullish events → bias +1, only bearish → −1, otherwise unchanged (it starts at
   0, the script's ``var int bias = 0``);
3. the FVG this bar completes (``low > high[2]`` / ``high < low[2]``, no size filter)
   is stored — at most 10 per side — after the event checks, so it is never tested on
   its own bar;
4. a confirmed ``ta.pivothigh/pivotlow(liqLen, liqLen)`` is stored (at most 50 per
   side), then every stored high this bar's high exceeds (``high > level``) and every
   low its low undercuts is removed: ``bsl`` is the lowest surviving high (buy-side
   liquidity), ``ssl`` the highest surviving low.
"""

import math
from collections import deque
from datetime import datetime

from kterminal.indicators import PivotHigh, PivotLow, ge, gt, le, lt, na

FVG_CAP = 10  # bT/sT keep at most 10 gaps per side (L267-275)
LIQUIDITY_CAP = 50  # liqH/liqL keep at most 50 levels (L280-285)

NAN = math.nan


class PdBias:
    """``f_pdBias(liqLen)`` on the bars of one higher timeframe.

    Gaps are ``(top, bottom)``; liquidity levels ``(price, pivot bar open time)``, oldest
    first. ``bias_time`` and ``bias_events`` describe the bar whose events last set the
    bias, for signal metadata.
    """

    __slots__ = (
        "_bar1",
        "_bar2",
        "_opens",
        "_pivot_high",
        "_pivot_low",
        "bear_gaps",
        "bias",
        "bias_events",
        "bias_time",
        "bull_gaps",
        "liq_highs",
        "liq_lows",
    )

    def __init__(self, liq_len: int) -> None:
        self._pivot_high = PivotHigh(liq_len, liq_len)  # L276
        self._pivot_low = PivotLow(liq_len, liq_len)  # L277
        self._opens: deque[datetime] = deque(maxlen=liq_len + 1)  # pivot bar = [liq_len]
        self._bar1: tuple[float, float] | None = None  # (high, low) of bar[1]
        self._bar2: tuple[float, float] | None = None  # … and bar[2]
        self.bull_gaps: list[tuple[float, float]] = []  # bT/bB
        self.bear_gaps: list[tuple[float, float]] = []  # sT/sB
        self.liq_highs: list[tuple[float, datetime]] = []  # liqH
        self.liq_lows: list[tuple[float, datetime]] = []  # liqL
        self.bias = 0
        self.bias_time: datetime | None = None
        self.bias_events: tuple[int, int] = (0, 0)  # (bullish, bearish) on that bar

    def update(self, high: float, low: float, close: float, open_time: datetime) -> None:
        """One closed bar of the bias timeframe."""
        bull_ev = 0
        bear_ev = 0
        gaps = self.bull_gaps
        for i in range(len(gaps) - 1, -1, -1):  # L238-248
            top, bot = gaps[i]
            if lt(close, bot):
                bear_ev += 1
                del gaps[i]
            elif le(low, top) and ge(close, (top + bot) / 2):
                bull_ev += 1
        gaps = self.bear_gaps
        for i in range(len(gaps) - 1, -1, -1):  # L249-259
            top, bot = gaps[i]
            if gt(close, top):
                bull_ev += 1
                del gaps[i]
            elif ge(high, bot) and le(close, (top + bot) / 2):
                bear_ev += 1
        if bull_ev > 0 and bear_ev == 0:  # L260-263
            self._set_bias(1, open_time, bull_ev, bear_ev)
        elif bear_ev > 0 and bull_ev == 0:
            self._set_bias(-1, open_time, bull_ev, bear_ev)

        high2, low2 = self._bar2 if self._bar2 is not None else (NAN, NAN)
        if gt(low, high2):  # L264-269
            self.bull_gaps.append((low, high2))
            if len(self.bull_gaps) > FVG_CAP:
                del self.bull_gaps[0]
        if lt(high, low2):  # L270-275
            self.bear_gaps.append((low2, high))
            if len(self.bear_gaps) > FVG_CAP:
                del self.bear_gaps[0]
        self._bar2, self._bar1 = self._bar1, (high, low)

        self._opens.append(open_time)
        ph = self._pivot_high.update(high)  # L276
        pl = self._pivot_low.update(low)  # L277
        pivot_time = self._opens[0]
        if not na(ph):  # L278-281
            self.liq_highs.append((ph, pivot_time))
            if len(self.liq_highs) > LIQUIDITY_CAP:
                del self.liq_highs[0]
        if not na(pl):  # L282-285
            self.liq_lows.append((pl, pivot_time))
            if len(self.liq_lows) > LIQUIDITY_CAP:
                del self.liq_lows[0]
        self.liq_highs = [lv for lv in self.liq_highs if not gt(high, lv[0])]  # L286-290
        self.liq_lows = [lv for lv in self.liq_lows if not lt(low, lv[0])]  # L291-295

    def _set_bias(self, bias: int, at: datetime, bull_ev: int, bear_ev: int) -> None:
        self.bias = bias
        self.bias_time = at
        self.bias_events = (bull_ev, bear_ev)

    @property
    def bsl(self) -> float:
        """``liqH.min()``: the lowest untaken pivot high, na when none is left (L296)."""
        return min(p for p, _ in self.liq_highs) if self.liq_highs else NAN

    @property
    def ssl(self) -> float:
        """``liqL.max()``: the highest untaken pivot low, na when none is left (L297)."""
        return max(p for p, _ in self.liq_lows) if self.liq_lows else NAN

    @property
    def bsl_time(self) -> datetime | None:
        """Pivot bar of :attr:`bsl` (the oldest of equal levels)."""
        return min(self.liq_highs, key=lambda lv: lv[0])[1] if self.liq_highs else None

    @property
    def ssl_time(self) -> datetime | None:
        return max(self.liq_lows, key=lambda lv: lv[0])[1] if self.liq_lows else None
