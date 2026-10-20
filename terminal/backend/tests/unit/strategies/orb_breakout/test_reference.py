"""The port against an independent, array-based transcription of script 8's ORB lines.

The reference re-reads lines 100-156 directly — session membership by bar open time
from the wall clock (``zoneinfo``, half-open ranges), ``inOR[1]`` from the previous
bar, the ``ORDay`` record replaced only on ``orStart``, the state trigger with Pine's
tolerant comparisons and the per-day counters — plus the D5 levels and the "no fill
at or after the flatten" rule. The streaming strategy must emit the same entries on
long synthetic runs of real-catalog instruments (several seeds, New York and London,
filter on and off, both stop modes), and no trade may outlive its flatten time.
"""

import math
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from kterminal.domain.market import Bar
from kterminal.domain.timeframes import Timeframe
from kterminal.indicators import Ema, feed
from kterminal.marketdata.synthetic import synthetic_bars
from kterminal.strategies.orb_breakout import OrbParams
from kterminal.strategy_engine import PositionEventKind
from tests.unit.strategies.orb_breakout.helpers import instrument, run
from tests.unit.strategies.pine_port_support import real_catalog

TOLERANCE = 1e-10
START = datetime(2026, 2, 23, tzinfo=UTC)  # a Monday; three weeks span the US clock change


def pine_gt(a: float, b: float) -> bool:
    return not (math.isnan(a) or math.isnan(b)) and a - b > TOLERANCE


def pine_lt(a: float, b: float) -> bool:
    return not (math.isnan(a) or math.isnan(b)) and a - b < -TOLERANCE


def inside(ts: datetime, session: str, tz: ZoneInfo) -> bool:
    """``not na(time(timeframe.period, "HHMM-HHMM:1234567", tz))`` for a same-day range."""
    start, end = session.split(":")[0].split("-")
    local = ts.astimezone(tz)
    minutes = local.hour * 60 + local.minute
    begin = int(start[:2]) * 60 + int(start[2:])
    finish = int(end[:2]) * 60 + int(end[2:])
    return begin <= minutes < finish


def tick_round(value: Decimal, tick: Decimal) -> float:
    """Exact decimal, ties away from zero on the tick grid (the D5 levels)."""
    units = int((value / tick).to_integral_value(rounding="ROUND_HALF_UP"))
    return float(units * tick)


@dataclass(frozen=True)
class Expected:
    index: int
    action: str  # LONG / SHORT / NO_TRADE
    stop: float
    target: float | None


def reference(bars: list[Bar], p: OrbParams, tick: Decimal) -> list[Expected]:
    tz = ZoneInfo(p.timezone)
    closes = [float(b.close) for b in bars]
    fast = feed(Ema(p.fast_length).update, closes)
    slow = feed(Ema(p.slow_length).update, closes)
    flatten = time.fromisoformat(p.flatten_time)
    out: list[Expected] = []
    cur: dict[str, Any] | None = None
    prev_in_or = False
    for i, bar in enumerate(bars):
        high, low, close = float(bar.high), float(bar.low), closes[i]
        in_or = inside(bar.open_time, p.or_session, tz)
        in_lvls = inside(bar.open_time, p.levels_session, tz)
        or_start, or_end = in_or and not prev_in_or, not in_or and prev_in_or
        prev_in_or = in_or
        if or_start:
            cur = {"hi": high, "lo": low, "formed": False, "long": False, "short": False}
        elif in_or and cur is not None:
            cur["hi"], cur["lo"] = max(cur["hi"], high), min(cur["lo"], low)
        if or_end and cur is not None:
            cur["formed"] = True
        if cur is None or not cur["formed"] or not in_lvls:
            continue
        bull, bear = pine_gt(fast[i], slow[i]), pine_lt(fast[i], slow[i])
        local_day = bar.open_time.astimezone(tz).date()
        deadline = datetime.combine(local_day, flatten, tzinfo=tz)
        for side in ("long", "short"):
            is_long = side == "long"
            beyond = pine_gt(close, cur["hi"]) if is_long else pine_lt(close, cur["lo"])
            trend = bull if is_long else bear
            if cur[side] or not beyond or (p.or_filter and not trend):
                continue
            cur[side] = True
            hi, lo = Decimal(str(cur["hi"])), Decimal(str(cur["lo"]))
            level = (lo if is_long else hi) if p.stop_mode == "range" else (hi + lo) / 2
            stop = tick_round(level, tick)
            target = None
            if p.target_r is not None:
                risk = abs(bar.close - Decimal(str(stop)))
                move = p.target_r * risk
                target = tick_round(bar.close + move if is_long else bar.close - move, tick)
            if bar.close_time >= deadline:
                out.append(Expected(i, "NO_TRADE", stop, target))
            else:
                out.append(Expected(i, "LONG" if is_long else "SHORT", stop, target))
    return out


def five_minute_bars(symbol: str, seed: int, days: int = 21) -> list[Bar]:
    inst = instrument(symbol)
    calendar = real_catalog().sessions.calendar(inst.trading_hours)
    return list(
        synthetic_bars(
            symbol,
            start=START,
            count=days * 23 * 12,
            start_price=Decimal(20_000),
            tick_size=inst.tick_size,
            timeframe=Timeframe.parse("5m"),
            volatility=0.0015,
            seed=seed,
            is_open=calendar.is_open,
        )
    )


NEW_YORK: dict[str, Any] = {}
LONDON: dict[str, Any] = {
    "timezone": "Europe/London",
    "or_session": "0800-0815",
    "levels_session": "0800-1630",
    "flatten_time": "16:30",
}


@pytest.mark.parametrize("seed", [1, 2, 3])
@pytest.mark.parametrize(
    ("symbol", "params"),
    [
        ("NAS100", NEW_YORK),
        ("MNQ", {"or_filter": False}),
        ("US30", {"stop_mode": "midpoint", "target_r": "1.5"}),
        ("US500", {"stop_mode": "midpoint", "target_r": None}),
        ("NAS100", LONDON),
        ("US30", {**LONDON, "or_filter": False, "stop_mode": "midpoint", "target_r": "1"}),
    ],
)
def test_port_matches_the_transcription(seed: int, symbol: str, params: dict[str, Any]) -> None:
    bars = five_minute_bars(symbol, seed)
    p = OrbParams.model_validate(params)
    expected = reference(bars, p, instrument(symbol).tick_size)
    result = run(bars, params=params, symbol=symbol)
    assert result.fault is None and result.rejected == []
    index = {bar.open_time: i for i, bar in enumerate(bars)}
    got = [
        Expected(
            index[s.bar_time],
            s.signal.value,
            float(s.stop_loss) if s.stop_loss is not None else math.nan,
            float(s.take_profit) if s.take_profit is not None else None,
        )
        for s in result.signals
        if s.bar_time is not None and (s.signal.is_entry or s.signal.value == "NO_TRADE")
    ]
    trades = [e for e in expected if e.action != "NO_TRADE"]
    assert len(trades) >= 10  # the comparison covers many breakouts
    assert [(e.index, e.action) for e in got] == [(e.index, e.action) for e in expected]
    for mine, theirs in zip(got, expected, strict=True):
        if mine.action == "NO_TRADE":
            continue
        assert mine.stop == theirs.stop
        assert mine.target == theirs.target

    # D5: no trade survives its signal day's flatten time by more than the closing bar.
    tz = ZoneInfo(p.timezone)
    flatten = time.fromisoformat(p.flatten_time)
    opened = [e for e in result.events if e.kind is PositionEventKind.OPENED]
    closed = [e for e in result.events if e.kind is PositionEventKind.CLOSED]
    assert len(closed) >= len(opened) - 1
    for start, end in zip(opened, closed, strict=False):
        assert start.signal is not None and start.signal.bar_time is not None
        day = start.signal.bar_time.astimezone(tz).date()
        deadline = datetime.combine(day, flatten, tzinfo=tz)
        assert end.time <= deadline + timedelta(minutes=5)
