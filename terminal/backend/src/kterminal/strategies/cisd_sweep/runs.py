"""The CISD run tracker of script 1, shared by the main-chart model and the scanner.

Both models of ``01_breakout_targets_ict_cisd.pine`` follow the latest run of
opposing closes and signal a close through its first candle's open:

* main model (L629-672): ``bullRunOpen`` / ``bullRunX`` / ``bullRunHigh`` and the
  bearish mirror;
* scanner (``scanCisd``, L808-840): ``uOpen`` / ``uHigh`` and ``dOpn`` / ``dLow``.

The rules are the same in both:

* a run starts on an up-close bar (``close > open``) whose previous bar was not one
  (``bullBar and not bullBar[1]``): its open is the CISD level, its high the start of
  the extreme; a doji (``close == open``) ends a run, so the next up-close bar starts
  a new one;
* while the level is live (not na) the extreme is extended with every bar's high,
  the CISD bar included — the update runs before the close-through check;
* a close below the level (``close < bullRunOpen``) **consumes** it (set to na)
  whatever the model's filters decide; the caller applies the filters.

The main model also requires ``bar_index > bullRunX`` (L660); the scanner does not.
The condition is always true: the run's first bar closes above its own open, so it
cannot close below it. :meth:`CisdRuns.bear_cross` checks it anyway, as L660 does.

Comparisons are Pine's (``gt``/``lt``: 1e-10 tolerance), so a body of 1e-11 is a doji.
"""

import math

from kterminal.indicators import gt, lt, na

NAN = math.nan


class Cross:
    """A close through a run's level: the level, the run's extreme so far (this bar
    included) and the bar index of the run's first candle."""

    __slots__ = ("extreme", "level", "start")

    def __init__(self, level: float, extreme: float, start: int) -> None:
        self.level = level
        self.extreme = extreme
        self.start = start


class CisdRuns:
    """The latest up-close and down-close runs of one series of bars."""

    __slots__ = (
        "_previous_bear",
        "_previous_bull",
        "bear_low",
        "bear_open",
        "bear_start",
        "bull_high",
        "bull_open",
        "bull_start",
    )

    def __init__(self) -> None:
        self.bull_open = NAN  # bullRunOpen / uOpen
        self.bull_start = -1  # bullRunX (bar index of the run's first candle)
        self.bull_high = NAN  # bullRunHigh / uHigh
        self.bear_open = NAN  # bearRunOpen / dOpn
        self.bear_start = -1  # bearRunX
        self.bear_low = NAN  # bearRunLow / dLow
        self._previous_bull = False  # bullBar[1] (false before the first bar, as in Pine)
        self._previous_bear = False

    def update(self, bar_index: int, open_: float, high: float, low: float, close: float) -> None:
        """L629-652 / L808-823: start or extend the runs with this bar."""
        bull = gt(close, open_)  # bullBar = close > open
        bear = lt(close, open_)  # bearBar = close < open
        if bull and not self._previous_bull:
            self.bull_open, self.bull_start, self.bull_high = open_, bar_index, high
        elif not na(self.bull_open):
            self.bull_high = max(self.bull_high, high)
        if bear and not self._previous_bear:
            self.bear_open, self.bear_start, self.bear_low = open_, bar_index, low
        elif not na(self.bear_open):
            self.bear_low = min(self.bear_low, low)
        self._previous_bull, self._previous_bear = bull, bear

    def bear_cross(self, bar_index: int, close: float) -> Cross | None:
        """L660 / L829: a close below the open of the live up-close run consumes it
        (L665 / L834) and is returned; None when there is no such close."""
        if na(self.bull_open) or bar_index <= self.bull_start or not lt(close, self.bull_open):
            return None
        cross = Cross(self.bull_open, self.bull_high, self.bull_start)
        self.bull_open = NAN
        return cross

    def bull_cross(self, bar_index: int, close: float) -> Cross | None:
        """L667 / L835 (mirror): a close above the open of the live down-close run."""
        if na(self.bear_open) or bar_index <= self.bear_start or not gt(close, self.bear_open):
            return None
        cross = Cross(self.bear_open, self.bear_low, self.bear_start)
        self.bear_open = NAN
        return cross
