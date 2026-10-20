"""Model D's higher-timeframe fair value gap zones (support and resistance).

A line-by-line port of these parts of
``terminal/pine/received/02_ict_sweep_order_flow_models.pine``:

* :class:`HtfFvgFeed` — ``f_htfFvg()`` (L301-304) through ``request.security(syminfo
  .tickerid, dFvgTF, f_htfFvg(), lookahead = barmerge.lookahead_on)`` (L619) and
  ``dFresh = not na(dT) and dT != nz(dT[1])`` (L624). With ``lookahead_on`` and the
  ``[1]``/``[3]`` offsets, a 1m bar inside HTF bar *k* reads the gap formed by bars
  *k − 3* … *k − 1*; it is fresh on the first 1m bar inside *k*. The strategy hands
  the feed ``ctx.series(tf, tradingview_lag=True)``, whose newest bar is *k − 1* on
  exactly those 1m bars (docs/05 §5.2.1);
* :class:`ZoneBook` — ``dZones`` with ``f_addZone`` (L358-368: at most 6 zones bull and
  bear together, the oldest dropped), the kill rule of ``f_updateZones`` (L372-381: a
  1m close beyond the far edge removes the zone) and ``f_zoneTouch`` (L403-414: a bar
  whose range overlaps a bullish zone is at support, a bearish zone at resistance).
  ``f_updateZones`` also tracks taps, extremes and CISD levels; model D never reads
  them, so they are not kept here.

Comparisons are Pine's (``gt``/``lt``/``le``/``ge``: 1e-10 tolerance, false with na).
"""

from dataclasses import dataclass
from datetime import datetime

from kterminal.indicators import ge, gt, le, lt
from kterminal.strategy_engine import SeriesView

ZONE_CAP = 6  # f_addZone: zs.size() > 6 → shift (L364)


@dataclass(frozen=True, slots=True)
class HtfFvg:
    """``[dNB, dBT, dBB, dNS, dST, dSB, dT]`` on a bar where they are fresh (L619, L624)."""

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
        """The gap values when they are fresh on this 1m bar (``dFresh``), else None.

        Only the newest visible HTF bar counts — Pine reads ``[1]`` of the HTF bar the
        chart bar is in, so a gap whose third candle is not the newest closed HTF bar
        on some chart bar is never seen."""
        count = len(view)
        if count == 0:
            return None
        newest = view.bar(-1)
        if self._last is not None and newest.open_time <= self._last:
            return None  # dT unchanged: not fresh
        self._last = newest.open_time
        if count < 3:
            return None  # dT = time[3] is na
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


@dataclass(frozen=True, slots=True)
class Zone:
    """A zone of ``dZones``: the parts of the script's ``Zone`` (L121-131) model D reads,
    plus where it came from (signal metadata)."""

    dir: int  # +1 bullish FVG (support), -1 bearish FVG (resistance)
    top: float
    bot: float
    start: datetime  # the gap's first candle (box left edge, time[3])
    added: datetime  # open time of the 1m bar that added it


class ZoneBook:
    """``dZones`` with ``f_addZone``, the kill rule of ``f_updateZones`` and
    ``f_zoneTouch``."""

    __slots__ = ("cap", "zones")

    def __init__(self, cap: int = ZONE_CAP) -> None:
        self.cap = cap
        self.zones: list[Zone] = []  # oldest first, as the Pine array

    def add(self, zone: Zone) -> None:
        """``f_addZone`` (L358-368)."""
        self.zones.append(zone)
        if len(self.zones) > self.cap:
            del self.zones[0]

    def update(self, close: float) -> None:
        """``f_updateZones`` (L372-381): drop every zone this bar closed through."""
        self.zones = [
            z for z in self.zones if not (lt(close, z.bot) if z.dir > 0 else gt(close, z.top))
        ]

    def touch(self, high: float, low: float) -> tuple[list[Zone], list[Zone]]:
        """``f_zoneTouch`` (L403-414): the bullish zones the bar's range overlaps (support)
        and the bearish ones (resistance); ``atSup``/``atRes`` are their non-emptiness."""
        support = [z for z in self.zones if z.dir > 0 and le(low, z.top) and ge(high, z.bot)]
        resistance = [z for z in self.zones if z.dir < 0 and ge(high, z.bot) and le(low, z.top)]
        return support, resistance
