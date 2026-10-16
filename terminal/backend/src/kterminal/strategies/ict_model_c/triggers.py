"""Model C's 1m triggers: inversion fair value gaps (IFVG) and CISD run opens.

A line-by-line port of these parts of
``terminal/pine/received/02_ict_sweep_order_flow_models.pine``:

* :class:`ChartGaps` — the shared 1m gap series (L163-168): ``bullGap = low > high[2]
  and low − high[2] >= minGap`` (bottom ``high[2]``), ``bearGap = high < low[2] and
  low[2] − high >= minGap`` (top ``low[2]``); no displacement filter for model C;
* :class:`RunOpens` — ``bearRunOpen`` / ``bullRunOpen`` (L740-743): the open of the
  first candle of the latest run of down-close (up-close) candles; the zones snapshot
  it as their CISD level when they record a new extreme;
* :class:`InversionGaps` — the 1m gaps waiting to be inverted (L745-773): a bearish
  gap stores its top and its middle candle (``bar_index − 1``); on later bars it
  expires once ``bar_index − bar > cLook`` and is inverted (bullish IFVG) by a close
  above its top, then removed. Bullish gaps mirror it. A gap is never tested on the
  bar that forms it (the check runs before the push).

Comparisons are Pine's (``gt``/``lt``/``ge``: 1e-10 tolerance, false with na).
"""

import math
from dataclasses import dataclass, field

from kterminal.indicators import ge, gt, lt

NAN = math.nan


@dataclass(frozen=True, slots=True)
class GapState:
    """The gap the evaluated bar completes, if any (L163-168)."""

    bull: bool  # bullGap
    bull_bot: float  # bullBotNow = high[2]
    bear: bool  # bearGap
    bear_top: float  # bearTopNow = low[2]


class ChartGaps:
    """``bullGap`` / ``bearGap`` on the chart (1m) bars."""

    __slots__ = ("_bar1", "_bar2", "_min_gap")

    def __init__(self, min_gap: float) -> None:
        self._min_gap = min_gap  # minGap = minFvgTicks × mintick (L157)
        self._bar1: tuple[float, float] | None = None  # (high, low) of bar[1]
        self._bar2: tuple[float, float] | None = None

    def update(self, high: float, low: float) -> GapState:
        high2, low2 = self._bar2 if self._bar2 is not None else (NAN, NAN)
        bull = gt(low, high2) and ge(low - high2, self._min_gap)  # L163
        bear = lt(high, low2) and ge(low2 - high, self._min_gap)  # L164
        self._bar2, self._bar1 = self._bar1, (high, low)
        return GapState(bull=bull, bull_bot=high2, bear=bear, bear_top=low2)


class RunOpens:
    """``bearRunOpen`` / ``bullRunOpen`` (L740-743), with the bar each run started on."""

    __slots__ = (
        "_bear1",
        "_bull1",
        "bear_run_bar",
        "bear_run_open",
        "bull_run_bar",
        "bull_run_open",
    )

    def __init__(self) -> None:
        self.bear_run_open = NAN
        self.bull_run_open = NAN
        self.bear_run_bar: int | None = None
        self.bull_run_bar: int | None = None
        self._bear1 = False  # close[1] < open[1] (false on the first bar: na)
        self._bull1 = False

    def update(self, index: int, open_: float, close: float) -> None:
        bear = lt(close, open_)
        bull = gt(close, open_)
        if bear and not self._bear1:  # L740-741
            self.bear_run_open, self.bear_run_bar = open_, index
        if bull and not self._bull1:  # L742-743
            self.bull_run_open, self.bull_run_bar = open_, index
        self._bear1, self._bull1 = bear, bull


@dataclass(slots=True)
class Inversions:
    """``invBull``/``invBullBar``/``invBear``/``invBearBar`` of one bar (L716-719), with
    the gap levels closed through (for signal metadata)."""

    bull: bool = False
    bull_bar: int | None = None  # max middle-candle bar of the inverted bearish gaps
    bull_levels: list[float] = field(default_factory=list)
    bear: bool = False
    bear_bar: int | None = None
    bear_levels: list[float] = field(default_factory=list)


class InversionGaps:
    """``bgTop/bgBar`` (bearish gaps) and ``ugBot/ugBar`` (bullish gaps), L745-773."""

    __slots__ = ("bear_gaps", "bull_gaps", "look")

    def __init__(self, look: int) -> None:
        self.look = look  # cLook
        self.bear_gaps: list[tuple[float, int]] = []  # (top, middle bar), oldest first
        self.bull_gaps: list[tuple[float, int]] = []  # (bottom, middle bar)

    def update(self, index: int, close: float, gaps: GapState) -> Inversions:
        out = Inversions()
        bear_gaps = self.bear_gaps
        for i in range(len(bear_gaps) - 1, -1, -1):  # L746-756
            top, bar = bear_gaps[i]
            if index - bar > self.look:
                del bear_gaps[i]
            elif gt(close, top):
                out.bull = True
                out.bull_bar = max(out.bull_bar or 0, bar)  # math.max(nz(invBullBar), …)
                out.bull_levels.append(top)
                del bear_gaps[i]
        bull_gaps = self.bull_gaps
        for i in range(len(bull_gaps) - 1, -1, -1):  # L757-767
            bot, bar = bull_gaps[i]
            if index - bar > self.look:
                del bull_gaps[i]
            elif lt(close, bot):
                out.bear = True
                out.bear_bar = max(out.bear_bar or 0, bar)
                out.bear_levels.append(bot)
                del bull_gaps[i]
        if gaps.bear:  # L768-770
            bear_gaps.append((gaps.bear_top, index - 1))
        if gaps.bull:  # L771-773
            bull_gaps.append((gaps.bull_bot, index - 1))
        return out
