"""Hand-built 1m tapes in New York time for the script 2 Model A/B tests.

A :class:`Tape` is a gap-free run of 1-minute bars: quiet bars around a price (bodies
of 0.10 alternating up and down, highs and lows all equal, so they form no pivots,
no gaps and no sweeps) with scripted bars placed at New York clock times. The golden
scenarios below are the script's textbook setups, built so that every rule fires on
a known bar; tests mirror them (``mirrored``) for the other direction.
"""

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from kterminal.domain.instruments import Instrument
from kterminal.domain.market import Bar
from kterminal.domain.timeframes import M1, M15
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


def quiet_row(i: int, level: float = 100.0) -> Row:
    """Alternating up/down bars with equal highs and lows: no pivot, gap or sweep."""
    if i % 2 == 0:
        return (level, level + 0.15, level - 0.15, level + 0.10)
    return (level + 0.10, level + 0.15, level - 0.15, level)


def mirrored(row: Row, axis: float = 100.0) -> Row:
    """The bar reflected about ``axis``: a long scenario becomes the short one."""
    o, h, low, c = row
    return (2 * axis - o, 2 * axis - low, 2 * axis - h, 2 * axis - c)


class Tape:
    """Consecutive 1m bars from ``start``; quiet bars unless a time is scripted."""

    def __init__(self, start: datetime, *, symbol: str = "XAUUSD") -> None:
        self.start = start
        self.symbol = symbol
        self.rows: list[Row] = []

    @property
    def end(self) -> datetime:
        return self.start + len(self.rows) * MINUTE

    def quiet_until(self, until: datetime, level: float = 100.0) -> "Tape":
        while self.end < until:
            self.rows.append(quiet_row(len(self.rows), level))
        return self

    def at(self, t: datetime, *rows: Row, level: float = 100.0) -> "Tape":
        """Quiet bars up to ``t``, then ``rows`` from ``t`` on."""
        self.quiet_until(t, level)
        if self.end != t:
            raise ValueError(f"{t.isoformat()} is already scripted")
        self.rows.extend(rows)
        return self

    def index(self, t: datetime) -> int:
        return int((t - self.start) / MINUTE)

    def bars(self) -> list[Bar]:
        return make_bars(self.rows, start=self.start, timeframe="1m", instrument=self.symbol)


def with_15m(minutes: Sequence[Bar]) -> list[Bar]:
    """The 1m bars plus their 15m aggregates, as the lab's aggregator closes them."""
    return [bar for batch in aggregate_stream(minutes, M1, [M15]) for bar in batch]


def run_1m(
    strategy: type[Strategy[Any]],
    bars: Sequence[Bar],
    *,
    params: dict[str, Any] | None = None,
    instrument: Instrument = XAUUSD,
    **kwargs: Any,
) -> StrategyTestResult:
    return run(strategy, bars, params=params, instrument=instrument, timeframe="1m", **kwargs)


# ── the long golden setup, shared by both models ───────────────────────────────────
# Levels hi = 101, lo = 99 around a quiet 100. Minutes after the window start:
#   +2  pivot high 100.6 (the MSS level, confirmed at +4)
#   +5  sweep of the low to 98.5 (close back inside at 99.2)
#   +6  first candle of the gap (high 99.3)
#   +7  displacement candle (body 1.6), closes above 100.6: the MSS
#   +8  third candle (low 99.6): bullish FVG 99.3-99.6 → limit at 99.6, stop 98.5,
#       target 101 (1.4 away ≥ 1R of 1.1)
#   +10 retrace fills the limit at 99.6
#   +12 rally reaches the target 101
SETUP: tuple[Row, ...] = (
    (100.0, 100.15, 99.85, 100.1),  # +0
    (100.0, 100.3, 99.85, 100.2),  # +1
    (100.2, 100.6, 100.1, 100.4),  # +2 pivot high 100.6
    (100.4, 100.45, 99.9, 100.0),  # +3
    (100.0, 100.1, 99.4, 99.5),  # +4
    (99.5, 99.6, 98.5, 99.2),  # +5 sweep: low 98.5 < 99
    (99.2, 99.3, 99.1, 99.25),  # +6 gap candle 1
    (99.25, 100.9, 99.2, 100.85),  # +7 displacement, close > 100.6 (MSS)
    (100.8, 100.95, 99.6, 100.5),  # +8 gap candle 3: FVG 99.3-99.6, armed
)
RETRACE: tuple[Row, ...] = (
    (100.5, 100.6, 100.0, 100.2),  # +9 not yet
    (100.2, 100.3, 99.5, 99.8),  # +10 fills at 99.6
    (99.8, 100.5, 99.7, 100.4),  # +11
    (100.4, 101.1, 100.3, 101.0),  # +12 target 101
)
HOLD: tuple[Row, ...] = (
    (100.5, 100.6, 100.0, 100.2),  # +9
    (100.2, 100.3, 99.5, 99.8),  # +10 fills at 99.6, then stays between stop and target
)
ARMED_AT = 8  # minutes after the window start
FILLED_AT = 10
TARGET_AT = 12

# A sweep that keeps closing below the range low (99); the MSS level, a pivot high at
# 98.3 (+5), is below it too. Back inside only at +11. Times are minutes after the
# window start (09:00 for Model B, 20:00 for Model A).
BELOW_RANGE: tuple[Row, ...] = (
    (100.0, 100.15, 99.85, 99.9),  # +00
    (99.9, 99.9, 98.6, 98.7),  # +01 sweep: low 98.6, close 98.7 (not back in)
    (98.7, 98.75, 98.0, 98.1),  # +02 new extreme 98.0
    (98.1, 98.15, 97.9, 98.0),  # +03 new extreme 97.9
    (98.0, 98.1, 97.95, 98.05),  # +04
    (98.05, 98.3, 98.0, 98.25),  # +05 pivot high 98.3 (confirmed at +07)
    (98.25, 98.28, 97.6, 97.7),  # +06 new extreme 97.6
    (97.7, 97.75, 97.5, 97.6),  # +07 new extreme 97.5; gap candle 1 (high 97.75)
    (97.6, 98.6, 97.55, 98.55),  # +08 displacement, close > 98.3: MSS
    (98.55, 98.7, 97.9, 98.6),  # +09 low 97.9: FVG 97.75-97.9; still below 99
    (98.6, 98.75, 98.3, 98.7),  # +10 still below 99
    (98.7, 99.3, 98.6, 99.2),  # +11 close 99.2 > 99: back inside → armed
    (99.2, 99.3, 98.9, 99.0),  # +12
)
