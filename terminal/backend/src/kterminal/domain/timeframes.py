"""Canonical timeframes.

Canonical codes are ``<count><unit>`` with a **case-sensitive** unit:
``m`` minute, ``h`` hour, ``D`` day, ``W`` week, ``M`` month — so ``1m`` is one
minute and ``1M`` one month, exactly as TradingView distinguishes them.

:meth:`Timeframe.parse` also accepts the spellings other systems use:

* TradingView ``{{interval}}``: ``1`` ``5`` ``15`` ``60`` ``240`` ``D`` ``1D`` ``W`` ``1W`` ``M``
* MetaTrader: ``M1`` ``M5`` ``M15`` ``H1`` ``H4`` ``D1`` ``W1`` ``MN1``
* human: ``5min`` ``1hr`` ``4 hours`` ``1day``

Intraday timeframes must divide a day evenly so that bar boundaries are the
same whether they are anchored to the Unix epoch or to UTC midnight.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from kterminal.core.clock import ensure_utc


class TimeUnit(StrEnum):
    MINUTE = "m"
    HOUR = "h"
    DAY = "D"
    WEEK = "W"
    MONTH = "M"


_UNIT_SECONDS = {
    TimeUnit.MINUTE: 60,
    TimeUnit.HOUR: 3_600,
    TimeUnit.DAY: 86_400,
    TimeUnit.WEEK: 604_800,
    TimeUnit.MONTH: 2_592_000,  # 30 days — for ordering only, never for bar arithmetic
}

_CANONICAL = re.compile(r"^(\d+)(m|h|D|W|M)$")
_TRADINGVIEW_MINUTES = re.compile(r"^(\d+)$")
_TRADINGVIEW_LETTER = re.compile(r"^(\d*)(D|W|M)$")
_METATRADER = re.compile(r"^(M|H|D|W|MN)(\d+)$")
_HUMAN = re.compile(
    r"^(\d+)\s*(min|mins|minute|minutes|hr|hrs|hour|hours|d|day|days|w|wk|week|weeks)$",
    re.IGNORECASE,
)
_HUMAN_UNITS = {
    "min": TimeUnit.MINUTE,
    "mins": TimeUnit.MINUTE,
    "minute": TimeUnit.MINUTE,
    "minutes": TimeUnit.MINUTE,
    "hr": TimeUnit.HOUR,
    "hrs": TimeUnit.HOUR,
    "hour": TimeUnit.HOUR,
    "hours": TimeUnit.HOUR,
    "d": TimeUnit.DAY,
    "day": TimeUnit.DAY,
    "days": TimeUnit.DAY,
    "w": TimeUnit.WEEK,
    "wk": TimeUnit.WEEK,
    "week": TimeUnit.WEEK,
    "weeks": TimeUnit.WEEK,
}
_MT_UNITS = {
    "M": TimeUnit.MINUTE,
    "H": TimeUnit.HOUR,
    "D": TimeUnit.DAY,
    "W": TimeUnit.WEEK,
    "MN": TimeUnit.MONTH,
}


@dataclass(frozen=True, slots=True)
class Timeframe:
    count: int
    unit: TimeUnit

    def __post_init__(self) -> None:
        if self.count < 1:
            raise ValueError(f"timeframe count must be >= 1, got {self.count}")
        if self.is_intraday and 86_400 % self.seconds != 0:
            raise ValueError(f"intraday timeframe {self.code} does not divide a day evenly")
        if self.unit is TimeUnit.HOUR and self.count >= 24:
            raise ValueError(f"use days instead of {self.count}h")

    # ── construction ────────────────────────────────────────────────────────
    @classmethod
    def parse(cls, raw: "str | Timeframe") -> "Timeframe":
        """Parse any supported spelling into the canonical timeframe."""
        if isinstance(raw, Timeframe):
            return raw
        text = str(raw).strip()
        if match := _CANONICAL.fullmatch(text):
            return cls._normalized(int(match[1]), TimeUnit(match[2]))
        if match := _TRADINGVIEW_MINUTES.fullmatch(text):
            return cls._normalized(int(match[1]), TimeUnit.MINUTE)
        if match := _TRADINGVIEW_LETTER.fullmatch(text):
            return cls._normalized(int(match[1] or 1), TimeUnit(match[2]))
        if match := _METATRADER.fullmatch(text):
            return cls._normalized(int(match[2]), _MT_UNITS[match[1]])
        if match := _HUMAN.fullmatch(text):
            return cls._normalized(int(match[1]), _HUMAN_UNITS[match[2].lower()])
        raise ValueError(f"unrecognised timeframe {raw!r}")

    @classmethod
    def _normalized(cls, count: int, unit: TimeUnit) -> "Timeframe":
        """Express minutes as hours where exact (60 → 1h, 240 → 4h)."""
        if unit is TimeUnit.MINUTE and count >= 60 and count % 60 == 0 and count < 1_440:
            return cls(count // 60, TimeUnit.HOUR)
        if unit is TimeUnit.MINUTE and count == 1_440:
            return cls(1, TimeUnit.DAY)
        return cls(count, unit)

    # ── properties ──────────────────────────────────────────────────────────
    @property
    def code(self) -> str:
        return f"{self.count}{self.unit.value}"

    def __str__(self) -> str:
        return self.code

    def __repr__(self) -> str:
        return f"Timeframe({self.code!r})"

    @property
    def seconds(self) -> int:
        """Nominal length in seconds (months count as 30 days: ordering only)."""
        return self.count * _UNIT_SECONDS[self.unit]

    @property
    def is_intraday(self) -> bool:
        return self.unit in (TimeUnit.MINUTE, TimeUnit.HOUR)

    @property
    def duration(self) -> timedelta:
        """Exact bar length. Defined for minute, hour, day and week bars."""
        if self.unit is TimeUnit.MONTH:
            raise ValueError("monthly bars have no fixed duration")
        return timedelta(seconds=self.seconds)

    def __lt__(self, other: "Timeframe") -> bool:
        return self.seconds < other.seconds

    def __le__(self, other: "Timeframe") -> bool:
        return self.seconds <= other.seconds

    def __gt__(self, other: "Timeframe") -> bool:
        return self.seconds > other.seconds

    def __ge__(self, other: "Timeframe") -> bool:
        return self.seconds >= other.seconds

    # ── bar alignment ───────────────────────────────────────────────────────
    def floor(self, ts: datetime) -> datetime:
        """Open time of the intraday bar containing ``ts`` (UTC-epoch aligned).

        Daily and longer bars depend on the instrument's trading-day rollover
        (e.g. 17:00 New York); use the session calendar for those.
        """
        if not self.is_intraday:
            raise ValueError(f"{self.code} bars are session-anchored; use the trading-day rule")
        epoch = int(ensure_utc(ts).timestamp())
        return datetime.fromtimestamp(epoch - epoch % self.seconds, tz=UTC)

    def is_aligned(self, ts: datetime) -> bool:
        return self.floor(ts) == ensure_utc(ts)

    def divides(self, other: "Timeframe") -> bool:
        """True if bars of ``other`` are made of a whole number of bars of ``self``."""
        if not (self.is_intraday or self.unit is TimeUnit.DAY):
            return self == other
        if other.unit is TimeUnit.MONTH:
            return self.unit is TimeUnit.DAY and self.count == 1
        return other.seconds % self.seconds == 0


M1 = Timeframe(1, TimeUnit.MINUTE)
M5 = Timeframe(5, TimeUnit.MINUTE)
M15 = Timeframe(15, TimeUnit.MINUTE)
M30 = Timeframe(30, TimeUnit.MINUTE)
H1 = Timeframe(1, TimeUnit.HOUR)
H4 = Timeframe(4, TimeUnit.HOUR)
D1 = Timeframe(1, TimeUnit.DAY)
W1 = Timeframe(1, TimeUnit.WEEK)
