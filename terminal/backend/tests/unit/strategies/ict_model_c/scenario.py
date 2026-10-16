"""Hand-built 1m tapes in New York time for the script 2 Model C tests.

A :class:`Tape` is a gap-free run of 1-minute bars: quiet bars around a level (bodies of
0.10 alternating up and down, highs and lows 0.15 from the level, so a flat stretch forms
no pivot, no gap and no fair value gap), slow walks of the level (at most 0.05 a bar:
no 1m gap and no 5m gap either) and scripted bars at New York clock times.

The golden long setup (``long_tape``):

* **bias** — 03:00 bar flat at 100 (1h high 100.15), the 04:00 hour walks to 102.5, the
  05:00 hour stays there (1h low 102.35): a bullish 1H FVG 100.15-102.35, stored when the
  05:00 bar is processed. The 06:00 hour wicks to its top and closes above its midpoint
  (a bullish event): the bias is +1 from the 07:00 1m bar on (lookahead_on + [1]);
* **draw on liquidity** — a 1m spike to 105 at 05:30 makes the 05:00 1h bar a 3/3 pivot
  high, confirmed by the 08:00 bar: buy-side liquidity 105 from the 09:00 1m bar on;
* **zone** — the 5m bars 09:00 (high 102.65), 09:05 (climb) and 09:10 (low 103.35) form a
  bullish 5m FVG 102.65-103.35, added on the 09:15 1m bar;
* **tap** — a run of down candles opening at 103.6 (the 09:19 bar) reaches into the zone
  from 09:20 and makes its extreme 102.9 at 09:23: CISD level 103.6;
* **trigger** — the 09:30 bar closes at 103.65 > 103.6 (CISD): long, stop 102.9 (risk
  0.75), target the draw on liquidity 105 (1.35 away ≥ 1R).
"""

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from kterminal.domain.instruments import Instrument
from kterminal.domain.market import Bar
from kterminal.domain.timeframes import H1, M1, M5, Timeframe
from kterminal.marketdata.aggregator import aggregate_stream
from kterminal.strategy_engine import Strategy
from kterminal.strategy_engine.testing import StrategyTestResult
from tests.fixtures.instruments import XAUUSD
from tests.unit.strategies.pine_port_support import make_bars, run

NY = ZoneInfo("America/New_York")
MINUTE = timedelta(minutes=1)

Row = tuple[float, float, float, float]


def ny(day: date, hhmm: str) -> datetime:
    """The UTC instant of a New York wall-clock time (first occurrence when ambiguous)."""
    hours, minutes = (int(part) for part in hhmm.split(":"))
    return datetime(day.year, day.month, day.day, hours, minutes, tzinfo=NY).astimezone(UTC)


def quiet_row(i: int, level: float) -> Row:
    """Alternating up/down bars around ``level``: no pivot, gap or FVG while it is flat."""
    if i % 2 == 0:
        return (level, level + 0.15, level - 0.15, level + 0.10)
    return (level + 0.10, level + 0.15, level - 0.15, level)


def mirrored(row: Row, axis: float = 100.0) -> Row:
    """The bar reflected about ``axis``: a long scenario becomes the short one."""
    o, h, low, c = row
    return (2 * axis - o, 2 * axis - low, 2 * axis - h, 2 * axis - c)


class Tape:
    """Consecutive 1m bars from ``start``: quiet bars, walks and scripted bars."""

    def __init__(self, start: datetime, *, symbol: str = "XAUUSD", level: float = 100.0):
        self.start = start
        self.symbol = symbol
        self.level = level
        self.rows: list[Row] = []

    @property
    def end(self) -> datetime:
        return self.start + len(self.rows) * MINUTE

    def quiet_until(self, until: datetime, level: float | None = None) -> "Tape":
        if level is not None:
            self.level = level
        while self.end < until:
            self.rows.append(quiet_row(len(self.rows), self.level))
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

    def bars(self, *, mirror: float | None = None, volume: float = 100) -> list[Bar]:
        rows = self.rows if mirror is None else [mirrored(r, mirror) for r in self.rows]
        return make_bars(
            rows, start=self.start, timeframe="1m", instrument=self.symbol, volume=volume
        )


def with_htf(minutes: Sequence[Bar], *timeframes: Timeframe) -> list[Bar]:
    """The 1m bars plus their aggregates, as the lab's aggregator closes them."""
    targets = list(timeframes) or [M5, H1]
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
SPIKE: Row = (102.5, 105.0, 102.35, 102.6)  # 05:30: the 1H pivot high (draw on liquidity)

ZONE: tuple[Row, ...] = (  # from 09:00
    (102.5, 102.65, 102.35, 102.6),  # 09:00 5m bar A: high 102.65
    (102.6, 102.65, 102.35, 102.5),
    (102.5, 102.65, 102.35, 102.6),
    (102.6, 102.65, 102.35, 102.5),
    (102.5, 102.65, 102.35, 102.6),
    (102.6, 102.75, 102.45, 102.7),  # 09:05 5m bar B: the climb
    (102.7, 102.95, 102.65, 102.9),
    (102.9, 103.15, 102.85, 103.1),
    (103.1, 103.35, 103.05, 103.3),
    (103.3, 103.55, 103.25, 103.5),
    (103.5, 103.65, 103.35, 103.6),  # 09:10 5m bar C: low 103.35 → FVG 102.65-103.35
    (103.6, 103.65, 103.35, 103.5),
    (103.5, 103.65, 103.35, 103.6),
    (103.6, 103.65, 103.35, 103.5),
    (103.5, 103.65, 103.35, 103.6),
    (103.6, 103.65, 103.4, 103.5),  # 09:15 the zone is added (5m bar 09:10 visible)
    (103.5, 103.65, 103.4, 103.6),
    (103.6, 103.65, 103.4, 103.5),
    (103.5, 103.65, 103.4, 103.6),
    (103.6, 103.65, 103.4, 103.5),  # 09:19 down: the bear run opens at 103.6
    (103.5, 103.62, 103.3, 103.4),  # 09:20 tap (low 103.3 <= 103.35)
    (103.4, 103.45, 103.15, 103.2),  # 09:21
    (103.2, 103.32, 103.0, 103.05),  # 09:22
    (103.05, 103.18, 102.9, 103.0),  # 09:23 extreme 102.9 (CISD 103.6)
    (103.0, 103.1, 102.95, 103.08),  # 09:24 up: the run ends
    (103.08, 103.15, 103.0, 103.1),  # 09:25
    (103.1, 103.36, 103.0, 103.15),  # 09:26
    (103.15, 103.2, 103.05, 103.1),  # 09:27
    (103.1, 103.2, 103.0, 103.15),  # 09:28
    (103.15, 103.2, 103.05, 103.1),  # 09:29
)
TAP_AT = 20  # minutes after the zone rows start
EXTREME_AT = 23
TRIGGER: Row = (103.15, 103.7, 103.05, 103.65)  # close > 103.6: CISD
RALLY: tuple[Row, ...] = (
    (103.65, 103.9, 103.6, 103.85),  # fills at 103.65
    (103.85, 104.4, 103.8, 104.35),
    (104.35, 105.05, 104.3, 105.0),  # target 105
)
HOLD: tuple[Row, ...] = (  # filled, then between the stop and the target
    (103.65, 103.9, 103.6, 103.85),
    (103.85, 104.0, 103.7, 103.9),
)
IFVG: tuple[Row, ...] = (  # a bearish 1m gap inverted, below the CISD level
    (103.15, 103.2, 103.05, 103.1),  # X0 low 103.05
    (103.1, 103.12, 103.0, 103.02),  # X1 the gap's middle candle
    (103.02, 103.03, 102.95, 102.97),  # X2 high 103.03 < 103.05: bearish gap, top 103.05
    (102.97, 103.12, 102.96, 103.1),  # X3 close 103.1 > 103.05: bullish IFVG
)


def bias_part(tape: Tape, day: date) -> Tape:
    """00:00-09:00 New York: the bullish 1H bias and the buy-side liquidity at 105."""
    tape.quiet_until(ny(day, "04:00"), 100.0)
    tape.walk_until(ny(day, "05:00"), 102.5)
    tape.at(ny(day, "05:30"), SPIKE)
    tape.quiet_until(ny(day, "09:00"), 102.5)
    return tape


def long_tape(
    day: date,
    window: Sequence[Row] = (TRIGGER, *RALLY),
    *,
    zone_at: str = "09:00",
    until: str = "12:30",
    days: int = 0,
    symbol: str = "XAUUSD",
) -> Tape:
    """The golden long setup: bias and liquidity, the zone rows from ``zone_at``, then
    ``window`` right after them (09:30 by default), quiet until ``until`` ``days`` later."""
    tape = bias_part(Tape(ny(day, "00:00"), symbol=symbol), day)
    tape.quiet_until(ny(day, zone_at), 102.5)
    tape.at(ny(day, zone_at), *ZONE, *window)
    tape.quiet_until(ny(day + timedelta(days=days), until))
    return tape
