"""Hand-built tapes in New York time for the script 1 CISD tests (``cisd_sweep``, ``cisd_scanner``).

A :class:`Tape` is a gap-free run of bars of one timeframe: quiet bars around a level
(bodies of 0.10 alternating up and down with equal closes, equal highs and equal lows,
so they form no pivot, no sweep and no CISD — or, with ``doji=True``, dojis that start
no run at all), scripted rows placed at New York clock times, and — when ``wide`` is
given — one wide quiet bar (±10) at each of those clock times, so that the session
highs and lows and the pivots they make sit far away from the scenarios. Rows are
``(open, high, low, close)``.

The golden setups below are written for a level of 100; ``mirrored`` reflects a row
about 100, and ``Tape.bars(mirror=True)`` the whole tape, so each long scenario is
also the short one.
"""

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from kterminal.domain.instruments import Instrument
from kterminal.domain.market import Bar
from kterminal.domain.timeframes import Timeframe
from kterminal.strategy_engine import Strategy
from kterminal.strategy_engine.testing import StrategyTestResult
from tests.fixtures.instruments import XAUUSD
from tests.unit.strategies.pine_port_support import make_bars, run

NY = ZoneInfo("America/New_York")

Row = tuple[float, float, float, float]

SESSION_STARTS = ("20:00", "02:00", "09:30")  # Asia, London, NY AM (L67-71)


def ny(day: date, hhmm: str) -> datetime:
    """The UTC instant of a New York wall-clock time (first occurrence when ambiguous)."""
    hours, minutes = (int(part) for part in hhmm.split(":"))
    return datetime(day.year, day.month, day.day, hours, minutes, tzinfo=NY).astimezone(UTC)


def quiet_row(i: int, level: float = 100.0, half_range: float = 0.15) -> Row:
    """Alternating up/down bars with equal closes, highs and lows."""
    if i % 2 == 0:
        return (level, level + half_range, level - half_range, level + 0.10)
    return (level + 0.10, level + half_range, level - half_range, level)


def mirrored(row: Row, axis: float = 100.0) -> Row:
    """The bar reflected about ``axis``: a short scenario becomes the long one."""
    o, h, low, c = row
    return (
        round(2 * axis - o, 6),
        round(2 * axis - low, 6),
        round(2 * axis - h, 6),
        round(2 * axis - c, 6),
    )


class Tape:
    """Consecutive bars from ``start``; quiet bars unless a time is scripted."""

    def __init__(
        self,
        start: datetime,
        *,
        timeframe: str = "5m",
        symbol: str = "XAUUSD",
        wide: Sequence[str] = (),
        level: float = 100.0,
        doji: bool = False,
    ) -> None:
        self.start = start
        self.timeframe = Timeframe.parse(timeframe)
        self.symbol = symbol
        self.wide = frozenset(wide)
        self.level = level
        self.doji = doji
        self.rows: list[Row] = []

    @property
    def end(self) -> datetime:
        return self.start + len(self.rows) * self.timeframe.duration

    def time_of(self, index: int) -> datetime:
        return self.start + index * self.timeframe.duration

    def index(self, t: datetime) -> int:
        return int((t - self.start) / self.timeframe.duration)

    def quiet_until(self, until: datetime, level: float | None = None) -> "Tape":
        if level is not None:
            self.level = level
        while self.end < until:
            i = len(self.rows)
            local = self.end.astimezone(NY).strftime("%H:%M")
            half = 10.0 if local in self.wide else 0.15
            if self.doji:
                level = self.level
                self.rows.append((level, level + half, level - half, level))
            else:
                self.rows.append(quiet_row(i, self.level, half))
        return self

    def quiet(self, count: int, level: float | None = None) -> "Tape":
        return self.quiet_until(self.end + count * self.timeframe.duration, level)

    def at(self, t: datetime, *rows: Row, level: float | None = None) -> "Tape":
        """Quiet bars up to ``t``, then ``rows`` from ``t`` on."""
        self.quiet_until(t, level)
        if self.end != t:
            raise ValueError(f"{t.isoformat()} is already scripted")
        self.rows.extend(rows)
        return self

    def then(self, *rows: Row) -> "Tape":
        self.rows.extend(rows)
        return self

    def bars(self, *, mirror: bool = False) -> list[Bar]:
        rows = [mirrored(r) for r in self.rows] if mirror else self.rows
        return make_bars(
            rows, start=self.start, timeframe=self.timeframe.code, instrument=self.symbol
        )


def run_tape(
    strategy: type[Strategy[Any]],
    tape: Tape,
    *,
    params: dict[str, Any] | None = None,
    instrument: Instrument = XAUUSD,
    mirror: bool = False,
    **kwargs: Any,
) -> StrategyTestResult:
    result = run(
        strategy,
        tape.bars(mirror=mirror),
        params=params,
        instrument=instrument,
        timeframe=tape.timeframe.code,
        **kwargs,
    )
    assert result.fault is None and result.rejected == [], (result.fault, result.rejected)
    return result


def bar_offset(tape: Tape, signal: Any, anchor: datetime) -> int:
    """Bars between ``anchor`` and the signal's bar."""
    return tape.index(signal.bar_time) - tape.index(anchor)


# ── the golden bearish setup (a buy-side sweep of a 5/5 pivot high, then a CISD) ──────
# Offsets are bars after the anchor; the bars before it are quiet around 100.
#   +0  spike to 101.0: the 5/5 pivot high, confirmed at +5 (lastPH = 101.0)
#   +7  sweep: high 101.5 > 101.0 (lastBslBar = +7, lastPH cleared)
#   +8  the up-close run starts: open 100.0 (the CISD level)
#   +9  run high 100.8 (the stop: inside the sweep wick, not at 101.5)
#   +10 close 99.6 < 100.0 with a body of 1.1: bearish CISD, R = 0.8,
#       TP1 = 99.2, TP2 = 98.4
BEAR_SETUP: tuple[Row, ...] = (
    (100.0, 101.0, 99.85, 100.1),  # +0 pivot high 101.0
    (100.1, 100.15, 99.85, 100.0),  # +1
    (100.0, 100.15, 99.85, 100.1),  # +2
    (100.1, 100.15, 99.85, 100.0),  # +3
    (100.0, 100.15, 99.85, 100.1),  # +4
    (100.1, 100.15, 99.85, 100.0),  # +5 pivot confirmed
    (100.0, 100.15, 99.85, 100.1),  # +6
    (100.1, 101.5, 99.85, 100.0),  # +7 sweep of the pivot high
    (100.0, 100.6, 99.95, 100.5),  # +8 up-close run: open 100.0
    (100.5, 100.8, 100.4, 100.7),  # +9 run high 100.8
    (100.7, 100.75, 99.5, 99.6),  # +10 bearish CISD
)
SIGNAL_AT = 10
SWEEP_AT = 7
RUN_AT = 8
# after the signal: the limit fills on +11, TP1 trades on +12, TP2 on +13
FILL_AND_TARGET: tuple[Row, ...] = (
    (99.6, 100.05, 99.5, 99.55),  # +11 high 100.05 >= 100.0: the short limit fills
    (99.55, 99.6, 98.9, 99.0),  # +12 TP1 99.2
    (99.0, 99.05, 98.3, 98.4),  # +13 TP2 98.4
)
# after the signal: TP1 trades on +11 before any fill; +12 would have filled
TP1_FIRST: tuple[Row, ...] = (
    (99.6, 99.65, 99.1, 99.2),  # +11 low 99.1 <= TP1 99.2, high below 100.0
    (99.2, 99.25, 99.15, 99.2),  # +12 a doji
    (99.2, 100.2, 99.15, 99.25),  # +13 would reach the level
)
