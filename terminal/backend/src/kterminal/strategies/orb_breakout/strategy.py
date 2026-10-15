"""S2 · Opening range breakout — the port of script 8, "FRVP + ORB + 9/20 EMA" (doc 13).

Source: ``terminal/pine/received/08_frvp_orb_ema.pine`` (spec
``terminal/pine/specs/08_frvp_orb_ema.md``); line numbers below refer to it.
The volume profile and the EMA-cross alerts are display/alert only and are
not ported (doc 13 D12).

What the script does, bar by bar (lines 100-156):

1. ``emaFast = ta.ema(close, 9)``, ``emaSlow = ta.ema(close, 20)`` on every bar;
   ``bull = emaFast > emaSlow``, ``bear = emaFast < emaSlow``.
2. ``inOR`` / ``inLvls``: the bar *opens* inside ``orSess`` (09:30-09:45) /
   ``lvlSess`` (09:30-16:00) in ``tz`` (America/New_York, DST-correct).
3. ``orStart = inOR and not inOR[1]`` starts a new opening range (``ORDay``) at
   the bar's wick high/low; later OR bars widen it. ``orEnd = not inOR and
   inOR[1]`` marks it formed — on the first bar after the window, which can
   already signal.
4. On a formed range, while ``inLvls``: a long when ``close > ORH`` (a state,
   not a cross) and, with ``orFilter``, ``bull``; at most one long per OR day
   (``longDone``), consumed only when the signal fires. Shorts mirror it.
5. A day without OR bars keeps the previous day's range and its unused
   signals (``cur`` is only replaced by ``orStart``).

The script defines no stop, target or exit; doc 13 D3/D4/D5 apply (README):
stop on the other side of the range (or at its midpoint), a target of
``target_r`` × the risk measured from the signal close, flat by
``flatten_time`` (16:00 New York) with exit reason ``SESSION_CLOSE``, and no
entry whose next-open fill would land at or after that time. The flatten is
``ctx.flatten()`` on the first bar that closes at or after each day's
``flatten_time``, whatever the theoretical book holds: it closes what the
account holds even if the book is already flat. A signal is emitted whenever
the script would draw its marker, also while a position is open; the
definition's ``on_opposite_signal: ignore`` then refuses it in the theoretical
book and in the accounts alike.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Literal

from pydantic import AfterValidator, Field, JsonValue

from kterminal.core.enums import Direction
from kterminal.domain.instruments import quantize_to_step
from kterminal.domain.market import Bar
from kterminal.domain.sessions import format_time, parse_time, to_local, to_utc
from kterminal.domain.signals import Signal
from kterminal.indicators import Ema, gt, lt, na
from kterminal.strategy_engine import (
    SessionString,
    SignalOutput,
    Strategy,
    StrategyMeta,
    StrategyParams,
    TimeZoneName,
    register_strategy,
)

TRIGGER_LONG = "ORB long"  # the script's plotshape / alertcondition titles (lines 158-162)
TRIGGER_SHORT = "ORB short"
SKIP_AFTER_FLATTEN = "FILL_AT_OR_AFTER_FLATTEN"


def _wall_time(value: str) -> str:
    """``"16:00"`` (local wall-clock time, ``HH:MM``), normalised."""
    return format_time(parse_time(value, "flatten_time"))


WallTime = Annotated[str, AfterValidator(_wall_time), Field(validate_default=True)]


class OrbParams(StrategyParams):
    """The script's inputs that change signals (lines 9-40; Pine defaults, names as the
    inputs) and the doc 13 D5 exit choices the script leaves open."""

    # ── the script's inputs ──────────────────────────────────────────────────
    timezone: TimeZoneName = Field("America/New_York", description="tz (line 9)")
    or_session: SessionString = Field("0930-0945", description="orSess, 'Opening range' (line 30)")
    levels_session: SessionString = Field(
        "0930-1600", description="lvlSess, 'Levels active during' (line 31)"
    )
    or_filter: bool = Field(True, description="orFilter, 'Only in the direction of the EMAs'")
    fast_length: int = Field(9, ge=1, le=1_000, description="fastLen (line 38)")
    slow_length: int = Field(20, ge=1, le=1_000, description="slowLen (line 40)")
    # ── doc 13 D5: the script defines no stop, target or exit ─────────────────
    stop_mode: Literal["range", "midpoint"] = Field(
        "range", description="Stop on the other side of the opening range, or at its midpoint"
    )
    target_r: Decimal | None = Field(
        Decimal("2"),
        gt=0,
        le=100,
        description="Target = signal close ± target_r × |close − stop|; null = no target",
    )
    flatten_time: WallTime = Field(
        "16:00",
        description="Local time (in `timezone`) by which a trade is closed; a signal whose "
        "next-open fill would land at or after it is not traded",
    )


@dataclass(slots=True)
class OpeningRange:
    """Pine's ``ORDay`` (lines 45-57) without the drawings: one OR day's range and its
    two once-per-day signal counters."""

    start: datetime  # open time of the bar that started it (orStart)
    high: float
    low: float
    formed: bool = False
    long_done: bool = False
    short_done: bool = False

    @property
    def mid(self) -> float:
        return (self.high + self.low) / 2  # math.avg(cur.hi, cur.lo), line 135


@register_strategy
class OrbBreakout(Strategy[OrbParams]):
    meta = StrategyMeta(
        id="orb_breakout",
        name="ORB breakout · EMA 9/20 filter (script 8)",
        version="1.0.0",
        description=(
            "Port of 'FRVP + ORB + 9/20 EMA': first close beyond the opening range per "
            "direction and OR day, EMA 9/20 direction filter; stop at the other side of the "
            "range, 2R, flat at 16:00 New York (doc 13 S2, D5)."
        ),
        # The OR must hold at least one bar: a chart timeframe no bigger than the range.
        timeframes=("1m", "5m", "15m"),
        # EMA 20 converges to 1e-12 and the latest opening range is seen: a day of 5m bars.
        warmup_bars=300,
        on_opposite_signal="ignore",  # D4: ignore while in a trade
        skip_entry_beyond_levels=True,  # D3: no fill once the open has passed stop/target
        tags=("pine-port", "script-8", "s2", "orb"),
    )
    Params = OrbParams

    def on_start(self) -> None:
        p = self.params
        self._ema_fast = Ema(p.fast_length)  # line 100
        self._ema_slow = Ema(p.slow_length)  # line 101
        self._flatten = parse_time(p.flatten_time, "flatten_time")
        self._prev_in_or = False  # inOR[1]; false before the first bar, as in Pine
        self._range: OpeningRange | None = None  # Pine's ``var ORDay cur``
        self._last_close: datetime | None = None  # close of the previous bar (any phase)

    def on_bar(self, bar: Bar) -> SignalOutput:
        p = self.params
        ctx = self.ctx
        close, high, low = float(bar.close), float(bar.high), float(bar.low)
        fast = self._ema_fast.update(close)  # lines 100-103, every bar
        slow = self._ema_slow.update(close)
        bull, bear = gt(fast, slow), lt(fast, slow)

        out: list[Signal] = []
        flatten = self._flatten_exit(bar)  # D5: flat by flatten_time; the exit comes first
        if flatten is not None:
            out.append(flatten)

        in_or = ctx.in_session(p.or_session, p.timezone)  # line 113
        in_levels = ctx.in_session(p.levels_session, p.timezone)  # line 114
        or_start = in_or and not self._prev_in_or  # line 115
        or_end = not in_or and self._prev_in_or  # line 116
        self._prev_in_or = in_or

        current = self._range
        if or_start:  # lines 121-126
            current = self._range = OpeningRange(bar.open_time, high, low)
        elif in_or and current is not None:  # lines 127-132
            current.high = max(current.high, high)
            current.low = min(current.low, low)
        if or_end and current is not None:  # lines 134-136
            current.formed = True
        if current is None or not current.formed or not in_levels:  # line 143
            return out
        # lines 150-156; the runner only delivers closed bars (barstate.isconfirmed)
        if not current.long_done and gt(close, current.high) and (not p.or_filter or bull):
            current.long_done = True  # consumed whether or not a trade follows (the marker)
            out.append(self._entry(Direction.LONG, bar, current, fast, slow))
        if not current.short_done and lt(close, current.low) and (not p.or_filter or bear):
            current.short_done = True
            out.append(self._entry(Direction.SHORT, bar, current, fast, slow))
        return out

    # ── decisions the script leaves open (doc 13 D5) ────────────────────────
    def flatten_deadline(self, ts: datetime) -> datetime:
        """The first flatten instant (``flatten_time`` in ``timezone``) at or after ``ts``."""
        tz = self.params.timezone
        day = to_local(ts, tz).date()
        deadline = to_utc(datetime.combine(day, self._flatten), tz)
        if deadline < ts:  # e.g. a window that runs past midnight
            deadline = to_utc(datetime.combine(day + timedelta(days=1), self._flatten), tz)
        return deadline

    def latest_flatten(self, ts: datetime) -> datetime:
        """The last flatten instant (``flatten_time`` in ``timezone``) at or before ``ts``."""
        tz = self.params.timezone
        day = to_local(ts, tz).date()
        instant = to_utc(datetime.combine(day, self._flatten), tz)
        if instant > ts:
            instant = to_utc(datetime.combine(day - timedelta(days=1), self._flatten), tz)
        return instant

    def _flatten_exit(self, bar: Bar) -> Signal | None:
        """Flatten on the first bar that closes at or after a flatten instant — the exit
        fills at the next open, the first price at or after it. After a data gap that is
        the first bar past it, which also closes at once a fill the gap delayed past it.
        ``ctx.flatten()`` closes whatever the book *and the account* hold (in either
        direction) and changes nothing when both are flat, so it does not ask
        ``ctx.position``: a position the account kept while the book closed it on a
        price the account did not trade is closed too."""
        previous, self._last_close = self._last_close, bar.close_time
        instant = self.latest_flatten(bar.close_time)
        if previous is None or not previous < instant <= bar.close_time:
            return None
        metadata: dict[str, JsonValue] = {
            "exit": "flatten",
            "flatten_time": self.params.flatten_time,
            "flatten_at": instant.isoformat(),
        }
        return self.ctx.flatten(metadata=metadata)

    def _entry(
        self, direction: Direction, bar: Bar, current: OpeningRange, fast: float, slow: float
    ) -> Signal:
        p = self.params
        ctx = self.ctx
        long = direction is Direction.LONG
        close = float(bar.close)
        stop, target = self.levels(direction, bar.close, current)
        deadline = self.flatten_deadline(bar.open_time)
        metadata: dict[str, JsonValue] = {
            "pine_signal": "orLong" if long else "orShort",
            "trigger": TRIGGER_LONG if long else TRIGGER_SHORT,
            "close": close,
            "or_high": current.high,
            "or_low": current.low,
            "or_mid": current.mid,
            "or_start": current.start.isoformat(),
            "stale_range": self._stale(current, bar),
            "ema_fast": _num(fast),
            "ema_slow": _num(slow),
            "or_filter": p.or_filter,
            "stop_mode": p.stop_mode,
            "target_r": None if p.target_r is None else str(p.target_r),
            "flatten_at": deadline.isoformat(),
            "bar_index": ctx.bar_index,
        }
        if bar.close_time >= deadline:  # the next-open fill would be at or after the flatten
            return ctx.no_trade(SKIP_AFTER_FLATTEN, persist=True, metadata=metadata)
        entry = ctx.instrument.round_price(bar.close)
        skip = _invalid_levels(entry, stop, target, long)
        if skip is not None:  # D3: never with these stops, kept as the lab's guard
            return ctx.no_trade(skip, persist=True, metadata=metadata)
        build = ctx.long if long else ctx.short
        return build(
            stop_loss=stop,
            take_profit=target,
            reason=TRIGGER_LONG if long else TRIGGER_SHORT,
            metadata=metadata,
        )

    def levels(
        self, direction: Direction, close: Decimal, current: OpeningRange
    ) -> tuple[Decimal, Decimal | None]:
        """D5 stop and target, exact in decimal and rounded to the tick (ties away from
        zero): the other side of the range or its midpoint, and ``target_r`` × the risk
        measured from the signal close (None without a target)."""
        p = self.params
        tick = self.ctx.instrument.tick_size
        long = direction is Direction.LONG
        high, low = _decimal(current.high), _decimal(current.low)
        level = (low if long else high) if p.stop_mode == "range" else (high + low) / 2
        stop = quantize_to_step(level, tick, ROUND_HALF_UP)
        if p.target_r is None:
            return stop, None
        move = p.target_r * abs(close - stop)
        target = quantize_to_step(close + move if long else close - move, tick, ROUND_HALF_UP)
        return stop, target

    def _stale(self, current: OpeningRange, bar: Bar) -> bool:
        """Whether the range is an earlier day's (no OR bars today, lines 120-156)."""
        tz = self.params.timezone
        return to_local(current.start, tz).date() != to_local(bar.open_time, tz).date()


def _invalid_levels(
    entry: Decimal, stop: Decimal, target: Decimal | None, long: bool
) -> str | None:
    """Why the levels cannot be traded against the rounded entry, or None (doc 13 D3)."""
    if (stop >= entry) if long else (stop <= entry):
        return "STOP_WRONG_SIDE"
    if target is not None and ((target <= entry) if long else (target >= entry)):
        return "TARGET_WRONG_SIDE"
    return None


def _decimal(price: float) -> Decimal:
    """A bar price back as the decimal it was read from (the shortest repr round-trips)."""
    return Decimal(repr(price))


def _num(value: float) -> float | None:
    """A float for signal metadata (JSON has no NaN): None while Pine's value is na."""
    return None if na(value) else value
