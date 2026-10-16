"""Pine-compatible technical indicators for strategy plug-ins (docs/14-indicators.md).

Every indicator is a small *streaming* object that reproduces one TradingView
``ta.*`` built-in: a strategy creates it in ``on_start`` and updates it once
per closed bar, in order::

    def on_start(self) -> None:
        self.ema_fast, self.ema_slow = Ema(8), Ema(21)
        self.atr = Atr(14)
        self.cross_up = Crossover()

    def on_bar(self, bar: Bar) -> SignalOutput:
        close = float(bar.close)
        fast = self.ema_fast.update(close)                  # math.nan while Pine returns na
        slow = self.ema_slow.update(close)
        atr = self.atr.update(float(bar.high), float(bar.low), close)
        if self.cross_up.update(fast, slow) and not na(atr): ...

Conventions shared by every class:

* **One object = one Pine call site.** Update it on *every* bar from the
  first one, also on bars where the result is not needed; Pine's built-ins
  keep their own history per call, and so do these objects.
* **Float64 maths** (Pine uses doubles). Convert ``Decimal`` prices with
  ``float()`` on the way in and back to ``Decimal`` at the ``Signal``.
* **na is ``math.nan``.** ``update`` returns ``nan`` wherever Pine returns
  ``na``; use :func:`na` / :func:`nz` / :class:`FixNan` as in Pine. The last
  result is also kept in ``.value``.
* Each class documents its seeding, warm-up, na handling and tie rules;
  docs/14 lists them side by side with the Pine function names.
"""

from kterminal.indicators.averages import Ema, Rma, Sma, Sum
from kterminal.indicators.cross import Cross, Crossover, Crossunder
from kterminal.indicators.extremes import Highest, HighestBars, Lowest, LowestBars
from kterminal.indicators.feed import feed
from kterminal.indicators.oscillators import Macd, MacdValue, Rsi, WaveTrend, WaveTrendValue
from kterminal.indicators.pine import (
    EPSILON,
    FixNan,
    div,
    eq,
    ge,
    gt,
    le,
    lt,
    na,
    ne,
    nz,
    pine_round,
    round_to_mintick,
)
from kterminal.indicators.pivots import PivotHigh, PivotLow
from kterminal.indicators.series import BarIndex, BarsSince, Change, Cum, History, ValueWhen
from kterminal.indicators.trend import Dmi, DmiValue, Sar, SuperTrend, SuperTrendValue
from kterminal.indicators.volatility import Atr, Stdev, TrueRange, Variance
from kterminal.indicators.vwap import Vwap, VwapValue

__all__ = [
    "EPSILON",
    "Atr",
    "BarIndex",
    "BarsSince",
    "Change",
    "Cross",
    "Crossover",
    "Crossunder",
    "Cum",
    "Dmi",
    "DmiValue",
    "Ema",
    "FixNan",
    "Highest",
    "HighestBars",
    "History",
    "Lowest",
    "LowestBars",
    "Macd",
    "MacdValue",
    "PivotHigh",
    "PivotLow",
    "Rma",
    "Rsi",
    "Sar",
    "Sma",
    "Stdev",
    "Sum",
    "SuperTrend",
    "SuperTrendValue",
    "TrueRange",
    "ValueWhen",
    "Variance",
    "Vwap",
    "VwapValue",
    "WaveTrend",
    "WaveTrendValue",
    "div",
    "eq",
    "feed",
    "ge",
    "gt",
    "le",
    "lt",
    "na",
    "ne",
    "nz",
    "pine_round",
    "round_to_mintick",
]
