"""The New York session clocks and session highs/lows of script 1 (L388-537).

* :class:`SessionClock` — ``inSess(s) => not na(time(timeframe.period, s, tz))``
  (L390) evaluated once per bar on its open time, with ``inSess[1]`` = the value this
  object computed on the previous primary bar (exactly Pine's history of the series).
* :class:`SessionRange` — the session high/low tracker: reset on the first bar inside
  (``inX and not inX[1]``), extended with every later bar inside, kept after the
  session until the next one starts (L486-494, L505-513, L529-537). The script uses it
  as a sweep level only while price is **outside** the session (L595-600), i.e. the
  last completed occurrence; the level is never retired once swept.
"""

import math
from datetime import datetime

from kterminal.strategy_engine import SessionSpec, parse_session

NAN = math.nan


class SessionClock:
    """One Pine session string, evaluated on each primary bar's open time."""

    __slots__ = ("_span", "inside", "previous", "spec")

    def __init__(self, session: str, timezone: str) -> None:
        self.spec: SessionSpec = parse_session(session, timezone)
        self._span: tuple[datetime, datetime] | None = None
        self.inside = False
        self.previous = False  # inSess[1]: false before the first bar, as in Pine

    def update(self, open_time: datetime) -> None:
        span = self._span
        if span is None or not span[0] <= open_time < span[1]:
            span = self.spec.window_at(open_time)
        self._span = span
        self.previous, self.inside = self.inside, span is not None

    @property
    def started(self) -> bool:
        """``inSess and not inSess[1]``."""
        return self.inside and not self.previous


class SessionRange:
    """High and low of the latest occurrence of a session (``asiaH``/``asiaL`` …)."""

    __slots__ = ("bars", "high", "low", "start")

    def __init__(self) -> None:
        self.high = NAN
        self.low = NAN
        self.start: datetime | None = None  # open time of the occurrence's first bar (asiaX)
        self.bars = 0

    def update(self, clock: SessionClock, open_time: datetime, high: float, low: float) -> None:
        if clock.started:
            self.high, self.low, self.start, self.bars = high, low, open_time, 1
        elif clock.inside:
            # never na here: the occurrence's first bar set both (math.max(na, x) is na)
            self.high = max(self.high, high)
            self.low = min(self.low, low)
            self.bars += 1

    def levels(self, clock: SessionClock, live: bool) -> tuple[float, float]:
        """``sXH``/``sXL`` (L595-600): the range while outside the session on a chart of
        60 minutes or less (``showSess``), na otherwise."""
        if live and not clock.inside:
            return self.high, self.low
        return NAN, NAN
