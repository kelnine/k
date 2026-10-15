"""S2 · Opening range breakout — the port of script 8, "FRVP + ORB + 9/20 EMA".

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

The script defines no stop, target or exit; doc 13 D4/D5 apply (README):
stop on the other side of the range (or its midpoint), a target of
``target_r`` × the risk measured from the signal close, flat at
``flatten_time`` (16:00 New York) with exit reason ``SESSION_CLOSE``, and no
entry whose next-open fill would land at or after that time. Signals are
emitted whenever the script would draw its marker, also while a position is
open; the definition's ``on_opposite_signal: ignore`` then refuses them in the
theoretical book and in the accounts alike.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AfterValidator, Field, JsonValue

from kterminal.core.enums import Direction
from kterminal.domain.market import Bar
from kterminal.domain.sessions import format_time, parse_time, to_local, to_utc
from kterminal.domain.signals import Signal
from kterminal.indicators import Ema, gt, lt, na, round_to_mintick
from kterminal.strategy_engine import (
    SessionString,
    SignalOutput,
    Strategy,
    StrategyMeta,
    StrategyParams,
    TimeZoneName,
    register_strategy,
)

TRIGGER_LONG = "ORB long"  # the script's alertcondition titles (lines 161-162)
TRIGGER_SHORT = "ORB short"
SKIP_AFTER_FLATTEN = "FILL_AT_OR_AFTER_FLATTEN"


def _wall_time(value: str) -> str:
    """``"16:00"`` (local wall-clock time, ``HH:MM``), normalised."""
    return format_time(parse_time(value, "flatten_time"))


WallTime = Annotated[str, AfterValidator(_wall_time), Field(validate_default=True)]


class OrbParams(StrategyParams):
    # ── the script's inputs that change signals (Pine defaults) ──────────────
    timezone: TimeZoneName = "America/New_York"  # tz (line 9)
    or_session: SessionString = "0930-0945"  # orSess, "Opening range" (line 30)
    levels_session: SessionString = "0930-1600"  # lvlSess, "Levels active during" (line 31)
    or_filter: bool = True  # orFilter, "Only in the direction of the EMAs" (line 34)
    fast_length: int = Field(9, ge=1, le=1_000)  # fastLen (line 38)
    slow_length: int = Field(20, ge=1, le=1_000)  # slowLen (line 40)
    # ── doc 13 D5 (the script defines no stop, target or exit) ───────────────
    stop: Literal["range", "midpoint"] = Field(
        "range", description="Stop on the other side of the opening range, or at its midpoint"
    )
    target_r: Decimal | None = Field(
        Decimal("2"),
        gt=0,
        le=100,
        description="Target = signal close ± target_r × (close − stop); null = no target",
    )
    flatten_time: WallTime = Field(
        "16:00",
        description="Local time (in `timezone`) by which every position is closed; signals "
        "whose next-open fill would land at or after it are skipped",
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
            "range, 2R, flat at 16:00 New York (doc 13 D5)."
        ),
        # The OR must hold at least one bar: a chart timeframe no bigger than the range.
        timeframes=("1m", "5m", "15m"),
        # EMA 20 convergence and the latest opening range: a full day of 5m bars.
        warmup_bars=300,
        on_opposite_signal="ignore",  # D4: ignore while in a trade
        skip_entry_beyond_levels=True,  # D3: no fill once the open has passed stop/target
        tags=("pine-port", "script-8", "s2", "orb"),
    )
    Params = OrbParams

    def on_start(self) -> None:
        p = self.params
        self._ema_fast = Ema(p.fast_length)
        self._ema_slow = Ema(p.slow_length)
        self._flatten = parse_time(p.flatten_time, "flatten_time")
        self._prev_in_or = False  # inOR[1]; false before the first bar, as in Pine
        self._range: OpeningRange | None = None  # Pine's ``cur``

    def on_bar(self, bar: Bar) -> SignalOutput:
        p = self.params
        ctx = self.ctx
        close, high, low = float(bar.close), float(bar.high), float(bar.low)
        fast = self._ema_fast.update(close)  # lines 100-103, every bar
        slow = self._ema_slow.update(close)
        bull, bear = gt(fast, slow), lt(fast, slow)

        out: list[Signal] = []
        flatten = self._flatten_exit(bar)  # D5: flat by flatten_time
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
            current.long_done = True
            out.append(self._entry(Direction.LONG, bar, current, fast, slow))
        if not current.short_done and lt(close, current.low) and (not p.or_filter or bear):
            current.short_done = True
            out.append(self._entry(Direction.SHORT, bar, current, fast, slow))
        return out

    # ── decisions the script leaves open (doc 13 D5) ────────────────────────
    def flatten_at(self, ts: datetime) -> datetime:
        """The flatten instant of the local day (in ``timezone``) that ``ts`` falls on."""
        tz = self.params.timezone
        local_day = to_local(ts, tz).date()
        return to_utc(datetime.combine(local_day, self._flatten), tz)

    def _flatten_exit(self, bar: Bar) -> Signal | None:
        """Close the position on the first bar that ends at or after its day's flatten time:
        the exit fills at the next open, the first price at or after it."""
        position = self.ctx.position
        if position is None or bar.close_time < self.flatten_at(position.entry_time):
            return None
        metadata: dict[str, JsonValue] = {
            "exit": "flatten",
            "flatten_time": self.params.flatten_time,
        }
        if position.is_long:
            return self.ctx.exit_long(session_close=True, metadata=metadata)
        return self.ctx.exit_short(session_close=True, metadata=metadata)

    def _entry(
        self, direction: Direction, bar: Bar, current: OpeningRange, fast: float, slow: float
    ) -> Signal:
        p = self.params
        ctx = self.ctx
        tick = ctx.instrument.tick_size
        long = direction is Direction.LONG
        close = float(bar.close)
        if p.stop == "range":
            stop = current.low if long else current.high
        else:
            stop = round_to_mintick(current.mid, tick)
        target: float | None = None
        if p.target_r is not None:
            risk = close - stop if long else stop - close
            move = float(p.target_r) * risk
            target = round_to_mintick(close + move if long else close - move, tick)
        flatten = self.flatten_at(bar.open_time)
        metadata: dict[str, JsonValue] = {
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
            "stop_mode": p.stop,
            "target_r": None if p.target_r is None else str(p.target_r),
            "flatten_at": flatten.isoformat(),
        }
        if bar.close_time >= flatten:  # the next-open fill would be at or after the flatten
            return ctx.no_trade(SKIP_AFTER_FLATTEN, persist=True, metadata=metadata)
        if (stop >= close) if long else (stop <= close):  # cannot happen: close is beyond OR
            return ctx.no_trade("WRONG_SIDE_STOP", persist=True, metadata=metadata)
        build = ctx.long if long else ctx.short
        return build(
            stop_loss=stop,
            take_profit=target,
            reason=TRIGGER_LONG if long else TRIGGER_SHORT,
            metadata=metadata,
        )

    def _stale(self, current: OpeningRange, bar: Bar) -> bool:
        """Whether the range is a previous day's (no OR bars today, lines 120-156)."""
        tz = self.params.timezone
        return to_local(current.start, tz).date() != to_local(bar.open_time, tz).date()


def _num(value: float) -> float | None:
    """A float for signal metadata (JSON has no NaN): None while Pine's value is na."""
    return None if na(value) else value
