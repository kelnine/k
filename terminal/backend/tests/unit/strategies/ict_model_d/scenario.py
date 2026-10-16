"""Hand-built 1m tapes in New York time for the script 2 Model D tests.

A :class:`Tape` is a gap-free run of 1-minute bars with a volume each: quiet bars around a
level (bodies of 0.10 alternating up and down, highs and lows 0.15 from the level, volume
100: never aggressive, as 100 < 1.5 × a 20-bar average of at least 100), slow walks of
the level and scripted bars (``(open, high, low, close, volume)``) at New York clock
times.

The golden long setup (``long_tape``), on a tape that starts at 09:30 (no overnight
session and no previous day: the key levels are na):

* **zone** — the 15m bars 10:00 (flat at 110, high 110.15), 10:15 (a walk to 111) and
  10:30 (flat at 111, low 110.85) form a bullish 15m FVG 110.15-110.85, added on the
  10:45 1m bar (lookahead_on + [1]);
* **absorption** — at 11:00 an aggressive selling bar (volume 400, close in the lowest
  15 % of its range) overlaps the zone: the long candidate, body top 111.0, low 110.4;
* **trigger** — at 11:03 an aggressive buying bar closes at 111.25 above the body top:
  long at the next open, stop at the lowest low since the candidate (110.35, the
  trigger bar's), target 2R = 113.05.
"""

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from kterminal.domain.instruments import Instrument
from kterminal.domain.market import Bar
from kterminal.domain.timeframes import M1, M15, Timeframe
from kterminal.marketdata.aggregator import aggregate_stream
from kterminal.strategy_engine import Strategy
from kterminal.strategy_engine.testing import StrategyTestResult
from tests.fixtures.instruments import XAUUSD
from tests.unit.strategies.pine_port_support import make_bars, run

NY = ZoneInfo("America/New_York")
MINUTE = timedelta(minutes=1)
QUIET_VOLUME = 100.0
LOUD = 400.0  # an aggressive bar's volume

Row = tuple[float, float, float, float, float]


def ny(day: date, hhmm: str) -> datetime:
    """The UTC instant of a New York wall-clock time (first occurrence when ambiguous)."""
    hours, minutes = (int(part) for part in hhmm.split(":"))
    return datetime(day.year, day.month, day.day, hours, minutes, tzinfo=NY).astimezone(UTC)


def quiet_row(i: int, level: float, volume: float = QUIET_VOLUME) -> Row:
    """Alternating up/down bars around ``level``: no gap or FVG while it is flat."""
    if i % 2 == 0:
        return (level, level + 0.15, level - 0.15, level + 0.10, volume)
    return (level + 0.10, level + 0.15, level - 0.15, level, volume)


def mirrored(row: Row, axis: float) -> Row:
    """The bar reflected about ``axis`` (same volume): buyers become sellers."""
    o, h, low, c, v = row
    return (2 * axis - o, 2 * axis - low, 2 * axis - h, 2 * axis - c, v)


def shifted(rows: Sequence[Row], by: float) -> tuple[Row, ...]:
    return tuple((o + by, h + by, low + by, c + by, v) for o, h, low, c, v in rows)


class Tape:
    """Consecutive 1m bars from ``start``: quiet bars, walks and scripted bars."""

    def __init__(self, start: datetime, *, symbol: str = "XAUUSD", level: float = 110.0):
        self.start = start
        self.symbol = symbol
        self.level = level
        self.rows: list[Row] = []

    @property
    def end(self) -> datetime:
        return self.start + len(self.rows) * MINUTE

    def quiet_until(
        self, until: datetime, level: float | None = None, volume: float = QUIET_VOLUME
    ) -> "Tape":
        if level is not None:
            self.level = level
        while self.end < until:
            self.rows.append(quiet_row(len(self.rows), self.level, volume))
        return self

    def walk_until(self, until: datetime, to: float) -> "Tape":
        """Quiet bars whose level moves in equal steps from the current level to ``to``."""
        count = int((until - self.end) / MINUTE)
        start = self.level
        for k in range(1, count + 1):
            self.rows.append(quiet_row(len(self.rows), start + (to - start) * k / count))
        self.level = to
        return self

    def at(self, t: datetime, *rows: Row) -> "Tape":
        """Quiet bars up to ``t``, then ``rows`` from ``t`` on (the level follows them)."""
        self.quiet_until(t)
        if self.end != t:
            raise ValueError(f"{t.isoformat()} is already scripted")
        self.rows.extend(rows)
        if rows:
            self.level = rows[-1][3]
        return self

    def index(self, t: datetime) -> int:
        return int((t - self.start) / MINUTE)

    def cut(self, until: datetime) -> "Tape":
        """A copy holding the bars that open before ``until``."""
        out = Tape(self.start, symbol=self.symbol, level=self.level)
        out.rows = self.rows[: self.index(until)]
        return out

    def bars(self, *, mirror: float | None = None) -> list[Bar]:
        rows = self.rows if mirror is None else [mirrored(r, mirror) for r in self.rows]
        return make_bars(rows, start=self.start, timeframe="1m", instrument=self.symbol)


def with_htf(minutes: Sequence[Bar], *timeframes: Timeframe) -> list[Bar]:
    """The 1m bars plus their aggregates, as the lab's aggregator closes them."""
    targets = list(timeframes) or [M15]
    return [bar for batch in aggregate_stream(minutes, M1, targets) for bar in batch]


def run_1m(
    strategy: type[Strategy[Any]],
    bars: Sequence[Bar],
    *,
    params: dict[str, Any] | None = None,
    instrument: Instrument = XAUUSD,
    **kwargs: Any,
) -> StrategyTestResult:
    return run(strategy, bars, params=params, instrument=instrument, timeframe="1m", **kwargs)


# ── the golden long setup ──────────────────────────────────────────────────────────
SELLERS: Row = (111.0, 111.05, 110.4, 110.5, LOUD)  # 11:00: aggressive selling at the zone
WAIT: tuple[Row, ...] = (  # 11:01-11:02: above the candidate's low, quiet volume
    (110.5, 110.75, 110.45, 110.7, QUIET_VOLUME),
    (110.7, 110.75, 110.45, 110.6, QUIET_VOLUME),
)
BUYERS: Row = (110.6, 111.3, 110.35, 111.25, LOUD)  # 11:03: aggressive buying, close > 111.0
RALLY: tuple[Row, ...] = (
    (111.25, 111.6, 111.2, 111.55, QUIET_VOLUME),  # fills at 111.25
    (111.55, 112.4, 111.5, 112.35, QUIET_VOLUME),
    (112.35, 113.1, 112.3, 113.0, QUIET_VOLUME),  # target 113.05
)
HOLD: tuple[Row, ...] = (  # filled, then between the stop and the target
    (111.25, 111.6, 111.2, 111.55, QUIET_VOLUME),
    (111.55, 111.65, 111.45, 111.5, QUIET_VOLUME),
)
SETUP: tuple[Row, ...] = (SELLERS, *WAIT, BUYERS)


def zone_part(tape: Tape, day: date) -> Tape:
    """09:30-11:00 New York: flat at 110, a walk to 111 in the 10:15 15m bar, flat at 111:
    the bullish 15m FVG 110.15-110.85, a zone from the 10:45 1m bar."""
    tape.quiet_until(ny(day, "10:15"), 110.0)
    tape.walk_until(ny(day, "10:30"), 111.0)
    tape.quiet_until(ny(day, "11:00"), 111.0)
    return tape


def long_tape(
    day: date,
    window: Sequence[Row] = (*SETUP, *RALLY),
    *,
    at: str = "11:00",
    until: str = "12:00",
    days: int = 0,
    symbol: str = "XAUUSD",
) -> Tape:
    """The golden long setup from 09:30: the zone, then ``window`` from ``at`` (quiet at
    111 until then), then quiet bars until ``until`` ``days`` later."""
    tape = zone_part(Tape(ny(day, "09:30"), symbol=symbol), day)
    tape.at(ny(day, at), *window)
    tape.quiet_until(ny(day + timedelta(days=days), until))
    return tape
