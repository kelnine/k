"""Previous and current trading day / week / month levels, built from intraday bars.

Pine scripts read previous-period levels with
``request.security(syminfo.tickerid, "D", high[1], lookahead=barmerge.lookahead_on)``
(PDH), and the same for ``"W"`` and ``"M"``. The lab has no daily, weekly or monthly
bars (``1D``/``1W``/``1M`` timeframes are rejected), so :class:`PeriodLevels`
builds them incrementally from the instance's **primary** bars, on the
instrument's trading-day rule from the catalog — ``ny_1700`` (17:00 New York)
for CFDs, FX, metals and CME futures, ``utc_midnight`` for crypto:

* **day** — the trading day a bar *opens* in (``TradingDayRule.trading_day``):
  with ``ny_1700`` the 18:00 New York bar on Sunday already belongs to Monday;
* **week** — the trading days Monday … Sunday of one ISO week: with ``ny_1700``
  the week starts Sunday 17:00 New York, with ``utc_midnight`` Monday 00:00 UTC;
* **month** — the trading days of one calendar month: with ``ny_1700`` October
  starts on 30 September at 17:00 New York (the first trading day's start).

A period exists only if it has bars: there is no daily bar for a weekend or a
holiday, so on Monday the previous day is Friday (as on TradingView), and after a
closed day the previous day is the last day that traded.

``previous(period)`` is the last **complete** period that has ended — the value
TradingView's ``[1]`` + ``lookahead_on`` idiom gives from the first bar of the new
period on. The first period an instance sees is complete only if its first bar
opens exactly at the period's start; otherwise it started mid-period, its
high/low are unknown and it never becomes ``previous`` (``None`` instead, like
Pine's ``na``). Warm-up therefore needs to start before the previous period
begins: see :func:`period_warmup_bars`.

Levels are exact when every primary bar lies inside one trading day, i.e. when
the primary timeframe divides the rollover (any timeframe up to 1h for the
on-the-hour rollovers in the catalog). A 4h bar aligned to UTC can straddle
17:00 New York; it counts for the day it opens in.
"""

import math
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from kterminal.domain.market import Bar
from kterminal.domain.sessions import TradingDayRule
from kterminal.domain.timeframes import Timeframe


class Period(StrEnum):
    DAY = "D"
    WEEK = "W"
    MONTH = "M"

    @classmethod
    def parse(cls, raw: "Period | str") -> "Period":
        """``"D"`` / ``"W"`` / ``"M"`` (Pine's spellings) or ``"day"`` / ``"week"`` /
        ``"month"``. A lower-case ``"m"`` is refused: it reads as minutes."""
        if isinstance(raw, Period):
            return raw
        if isinstance(raw, str):
            text = raw.strip()
            if text in ("D", "W", "M", "d", "w"):
                return cls(text.upper())
            words = {"day": cls.DAY, "week": cls.WEEK, "month": cls.MONTH}
            if text.lower() in words:
                return words[text.lower()]
        raise ValueError(f"unknown period {raw!r}; use 'D', 'W' or 'M' (or day/week/month)")


@dataclass(frozen=True, slots=True)
class PeriodBar:
    """OHLCV of one trading day / week / month, from the primary bars seen in it."""

    period: Period
    start: date  # the trading day; the Monday of a week; the first of a month
    open_time: datetime  # open time of the first bar seen in the period
    close_time: datetime  # close time of the latest bar seen in it
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    bars: int
    complete: bool  # the bars cover the period from its start (see the module notes)

    def _add(self, bar: Bar) -> "PeriodBar":
        return replace(
            self,
            close_time=bar.close_time,
            high=max(self.high, bar.high),
            low=min(self.low, bar.low),
            close=bar.close,
            volume=self.volume + bar.volume,
            bars=self.bars + 1,
        )


class PeriodLevels:
    """Previous and current trading day, week and month of one instrument.

    The runner feeds every primary bar (warm-up included) through :meth:`update`
    before the strategy sees it, so ``current`` includes the bar being evaluated.
    """

    def __init__(self, rule: TradingDayRule) -> None:
        self.rule = rule
        self._current: dict[Period, PeriodBar] = {}
        self._previous: dict[Period, PeriodBar] = {}
        self._last_open: datetime | None = None
        self._day: date | None = None
        self._day_bounds: tuple[datetime, datetime] | None = None

    def current(self, period: Period | str = Period.DAY) -> PeriodBar | None:
        """The period the latest bar belongs to (it may still be in progress)."""
        return self._current.get(Period.parse(period))

    def previous(self, period: Period | str = Period.DAY) -> PeriodBar | None:
        """The last complete period before the current one, or None (Pine's ``na``)."""
        return self._previous.get(Period.parse(period))

    def update(self, bar: Bar) -> None:
        if self._last_open is not None and bar.open_time <= self._last_open:
            raise ValueError(
                f"bars must arrive in order: {bar.open_time.isoformat()} after "
                f"{self._last_open.isoformat()}"
            )
        first = self._last_open is None
        self._last_open = bar.open_time
        day = self._trading_day(bar.open_time)
        for period, start in (
            (Period.DAY, day),
            (Period.WEEK, day - timedelta(days=day.weekday())),
            (Period.MONTH, day.replace(day=1)),
        ):
            running = self._current.get(period)
            if running is not None and running.start == start:
                self._current[period] = running._add(bar)
                continue
            if running is not None and running.complete:
                self._previous[period] = running
            self._current[period] = PeriodBar(
                period=period,
                start=start,
                open_time=bar.open_time,
                close_time=bar.close_time,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                bars=1,
                # every later period is entered across a boundary seen in the data
                complete=not first or bar.open_time == self.rule.day_bounds(start)[0],
            )

    def _trading_day(self, ts: datetime) -> date:
        bounds = self._day_bounds
        if self._day is not None and bounds is not None and bounds[0] <= ts < bounds[1]:
            return self._day
        day = self.rule.trading_day(ts)
        self._day, self._day_bounds = day, self.rule.day_bounds(day)
        return day


_DST_SLACK = timedelta(hours=2)  # a trading day lasts 25 hours when the clocks go back
_SPAN = {
    Period.DAY: timedelta(days=2) + _DST_SLACK,
    Period.WEEK: timedelta(days=14) + _DST_SLACK,
    Period.MONTH: timedelta(days=62) + _DST_SLACK,
}


def period_warmup_bars(period: Period | str, timeframe: Timeframe | str) -> int:
    """Primary bars of warm-up after which ``previous(period)`` is known (conservative).

    Two whole periods of round-the-clock bars (2 days, 14 days, 62 days, plus two
    hours for 25-hour days when the clocks go back): the warm-up then starts inside
    the period before the previous one, so the previous period is seen from its
    start. Markets that close (weekends, nights) reach further back with the same
    number of bars. Use it for ``meta.warmup_bars``.
    """
    tf = Timeframe.parse(timeframe)
    if not tf.is_intraday:
        raise ValueError(f"{tf}: previous-period levels are built from intraday bars")
    return math.ceil(_SPAN[Period.parse(period)] / tf.duration) + 1
