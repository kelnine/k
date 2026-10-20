"""Bar builders and run helpers for the ``orb_breakout`` tests.

Bars are written by *local* wall-clock time (New York or London), so a test
reads like the chart: ``{"09:30": (100, 101, 99.5, 100.5)}``. Every bar not
given is a flat bar at the previous close, so the opening range and the EMAs
are exactly what the rows say. The real catalog's instruments (NAS100, MNQ …)
and session book come from the shared Pine-port helpers.
"""

from collections.abc import Mapping, Sequence
from datetime import date, datetime, time
from typing import Any

from kterminal.core.enums import SignalAction
from kterminal.domain.instruments import Instrument
from kterminal.domain.market import Bar
from kterminal.domain.sessions import to_local, to_utc
from kterminal.domain.signals import Signal
from kterminal.domain.timeframes import Timeframe
from kterminal.strategies.orb_breakout import OrbBreakout
from kterminal.strategy_engine.testing import StrategyTestResult, run_strategy
from tests.unit.strategies.pine_port_support import real_catalog

NY = "America/New_York"
LONDON = "Europe/London"

Row = tuple[float, float, float, float]


def instrument(symbol: str = "NAS100") -> Instrument:
    return real_catalog().instrument(symbol)


def local(day: date, hhmm: str, tz: str = NY) -> datetime:
    """The UTC instant of local wall-clock ``hhmm`` on ``day`` in ``tz``."""
    hour, minute = (int(part) for part in hhmm.split(":"))
    return to_utc(datetime.combine(day, time(hour, minute)), tz)


def hhmm(ts: datetime, tz: str = NY) -> str:
    return to_local(ts, tz).strftime("%H:%M")


def day_bars(
    day: date,
    rows: Mapping[str, Row | float],
    *,
    start: str = "08:00",
    end: str = "17:00",
    price: float = 100.0,
    tz: str = NY,
    timeframe: str = "5m",
    symbol: str = "NAS100",
    skip: Sequence[str] = (),
) -> list[Bar]:
    """Bars opening from ``start`` to before ``end`` (local) on ``day``.

    ``rows`` maps a local open time to ``(open, high, low, close)`` or to a single
    price (a flat bar there); every other bar is flat at the previous close (``price``
    before the first row). Times in ``skip`` have no bar (a data gap)."""
    tf = Timeframe.parse(timeframe)
    t = local(day, start, tz)
    stop = local(day, end, tz)
    last = price
    out: list[Bar] = []
    while t < stop:
        key = hhmm(t, tz)
        row = rows.get(key)
        if key in skip:
            t += tf.duration
            continue
        if row is None:
            o = h = low = c = last
        elif isinstance(row, (int, float)):
            o = h = low = c = float(row)
        else:
            o, h, low, c = row
        out.append(Bar.of(symbol, tf, t, repr(o), repr(h), repr(low), repr(c), 100))
        last = c
        t += tf.duration
    return out


def run(
    bars: Sequence[Bar],
    *,
    params: dict[str, Any] | None = None,
    symbol: str = "NAS100",
    timeframe: str = "5m",
    **kwargs: Any,
) -> StrategyTestResult:
    """The strategy through the real runner, with the real catalog's session book."""
    return run_strategy(
        OrbBreakout,
        instrument=instrument(symbol),
        bars=bars,
        timeframe=timeframe,
        params=params,
        sessions=real_catalog().sessions,
        **kwargs,
    )


def at(signals: Sequence[Signal], tz: str = NY) -> list[tuple[str, SignalAction]]:
    """``(local bar open time, action)`` of every signal."""
    out = []
    for signal in signals:
        assert signal.bar_time is not None
        out.append((hhmm(signal.bar_time, tz), signal.signal))
    return out


def strategy_object(result: StrategyTestResult) -> OrbBreakout:
    assert result.runner is not None
    strategy = result.runner._strategy
    assert isinstance(strategy, OrbBreakout)
    return strategy
