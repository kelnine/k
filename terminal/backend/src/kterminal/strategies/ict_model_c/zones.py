"""Model C's setup zones: higher-timeframe fair value gaps and their tracking.

A line-by-line port of these parts of
``terminal/pine/received/02_ict_sweep_order_flow_models.pine``:

* :class:`HtfFvgFeed` — ``f_htfFvg()`` (L301-304) through ``request.security(syminfo
  .tickerid, cFvgTF, f_htfFvg(), lookahead = barmerge.lookahead_on)`` (L618) and the
  freshness test ``cFresh = not na(cT) and cT != nz(cT[1])`` (L623). With
  ``lookahead_on`` and the ``[1]``/``[3]`` offsets, a 1m bar inside HTF bar *k* reads
  the gap formed by bars *k − 3* … *k − 1*; it is fresh on the first 1m bar inside
  *k*. The strategy hands the feed ``ctx.series(tf, tradingview_lag=True)``, whose
  newest bar is *k − 1* on exactly those 1m bars (docs/05 §5.2.1);
* :class:`Zone` / :class:`ZoneBook` — the ``Zone`` type (L121-131), ``f_addZone``
  (L358-368: push, at most 6 zones bull and bear together, the oldest dropped) and
  ``f_updateZones`` (L372-401: a 1m close beyond the far edge kills the zone; the first
  touch, the most extreme price inside the zone and the CISD level — the open of the
  run of opposite candles at the moment that extreme was made — are tracked on every
  bar, around the clock).

Comparisons are Pine's (``gt``/``lt``/``le``/``ge``: 1e-10 tolerance, false with na).
"""

import math
from dataclasses import dataclass
from datetime import datetime

from kterminal.indicators import ge, gt, le, lt, na
from kterminal.strategy_engine import SeriesView

ZONE_CAP = 6  # f_addZone: zs.size() > 6 → shift (L364)

NAN = math.nan


@dataclass(frozen=True, slots=True)
class HtfFvg:
    """``[cNB, cBT, cBB, cNS, cST, cSB, cT]`` on a bar where they are fresh (L618, L623)."""

    bull: bool  # bull[1]: low[1] > high[3]
    bull_top: float  # low[1]
    bull_bot: float  # high[3]
    bear: bool  # bear[1]: high[1] < low[3]
    bear_top: float  # low[3]
    bear_bot: float  # high[1]
    start: datetime  # time[3]: open time of the gap's first candle
    third: datetime  # open time of the gap's third candle (bar k - 1)


class HtfFvgFeed:
    """``f_htfFvg`` read through the TradingView-lagged view of one higher timeframe."""

    __slots__ = ("_last",)

    def __init__(self) -> None:
        self._last: datetime | None = None  # open time of the newest HTF bar seen

    def update(self, view: SeriesView) -> HtfFvg | None:
        """The gap values when they are fresh on this 1m bar (``cFresh``), else None.

        Only the newest visible HTF bar counts — Pine reads ``[1]`` of the HTF bar the
        chart bar is in, so a gap whose third candle is not the newest closed HTF bar
        on some chart bar is never seen."""
        count = len(view)
        if count == 0:
            return None
        newest = view.bar(-1)
        if self._last is not None and newest.open_time <= self._last:
            return None  # cT unchanged: not fresh
        self._last = newest.open_time
        if count < 3:
            return None  # cT = time[3] is na
        first = view.bar(-3)
        high1, low1 = float(newest.high), float(newest.low)
        high3, low3 = float(first.high), float(first.low)
        return HtfFvg(
            bull=gt(low1, high3),
            bull_top=low1,
            bull_bot=high3,
            bear=lt(high1, low3),
            bear_top=low3,
            bear_bot=high1,
            start=first.open_time,
            third=newest.open_time,
        )


@dataclass(slots=True)
class Zone:
    """The script's ``Zone`` (L121-131). Bar indices are ``None`` where Pine holds na;
    ``start``, ``added`` and ``added_index`` describe the zone in signal metadata."""

    dir: int  # +1 bullish FVG (support), -1 bearish FVG (resistance)
    top: float
    bot: float
    start: datetime  # the gap's first candle (box left edge, time[3])
    added: datetime  # open time of the 1m bar that added it
    added_index: int
    tapped: bool = False
    tap_bar: int | None = None
    ext: float = NAN
    ext_bar: int | None = None
    cisd: float = NAN
    used: bool = False


class ZoneBook:
    """``cZones`` with ``f_addZone`` and ``f_updateZones``."""

    __slots__ = ("cap", "zones")

    def __init__(self, cap: int = ZONE_CAP) -> None:
        self.cap = cap
        self.zones: list[Zone] = []  # oldest first, as the Pine array

    def add(self, zone: Zone) -> None:
        """``f_addZone`` (L358-368)."""
        self.zones.append(zone)
        if len(self.zones) > self.cap:
            del self.zones[0]

    def update(
        self,
        index: int,
        high: float,
        low: float,
        close: float,
        bear_run: float,
        bull_run: float,
    ) -> None:
        """``f_updateZones(zs, bearRunOpen, bullRunOpen)`` (L372-401), newest zone first."""
        zones = self.zones
        for i in range(len(zones) - 1, -1, -1):
            z = zones[i]
            dead = lt(close, z.bot) if z.dir > 0 else gt(close, z.top)  # L377
            if dead:
                del zones[i]
                continue
            if z.dir > 0 and le(low, z.top):  # L385-392
                if not z.tapped:
                    z.tapped, z.tap_bar = True, index
                if na(z.ext) or lt(low, z.ext):
                    z.ext, z.ext_bar, z.cisd = low, index, bear_run
            if z.dir < 0 and ge(high, z.bot):  # L393-400
                if not z.tapped:
                    z.tapped, z.tap_bar = True, index
                if na(z.ext) or gt(high, z.ext):
                    z.ext, z.ext_bar, z.cisd = high, index, bull_run
