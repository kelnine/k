"""ICT Sweep + Order Flow Models [NY] — Model A (S5) and Model B (S4) (doc 13).

Port of models A and B of ``terminal/pine/received/02_ict_sweep_order_flow_models.pine``
(spec ``terminal/pine/specs/02_ict_sweep_order_flow_models.md``). Both run the script's
shared engine (``engine.py``, ``SweepModel.run`` L466-595) on closed 1m bars, in New York
time on all seven days:

* **Model A** (``ict_model_a``): at the first bar of ``aWin`` (20:00-02:00) the levels
  are the most recent untaken 15m swing high and low (``f_liqSwings(aSwing)`` through
  ``request.security(..., lookahead_on)``, L616), read from
  ``ctx.series("15m", tradingview_lag=True)``;
* **Model B** (``ict_model_b``): at the first bar of ``bWin`` (09:00-12:00) the levels
  are the high and low of the 1m bars opening in ``bRange`` (08:00-09:00), used only
  if that range started less than 24 hours ago (L786-797); arming also needs a close
  back inside the range (``needBack``).

The engine's transitions become signals: an armed setup is a resting LIMIT entry at
the FVG edge with the script's stop (sweep extreme ∓ buffer) and target (the opposite
level, or the fixed RR); the script's cancels — the target traded before the fill
(``missed``) and the window end — are EXITs of the resting order the theoretical book
holds (``ctx.pending_entry``; the lab has no such rule), and the order also expires
with the window's last bar. A filled trade is held as the script holds it, until its
stop or target or the model's next window start, where ``ctx.flatten()`` closes it with
the reason ``SESSION_CLOSE`` (doc 13 D6); ``after_window: flat`` flattens at the window
end instead (the D6 variant). The time exits are sent whenever the window's cycle had a
fill, whatever ``ctx.position`` says, so they also close a position the account kept
after the book closed it. The README lists every deviation from the script.
"""

import math
from abc import abstractmethod
from datetime import datetime
from decimal import Decimal
from typing import ClassVar, Literal

from pydantic import Field, JsonValue

from kterminal.core.enums import Direction, OrderType
from kterminal.domain.market import Bar
from kterminal.domain.signals import Signal
from kterminal.indicators import na
from kterminal.strategies.ict_sweep_models.engine import (
    ARMED,
    EngineConfig,
    EntryMode,
    SharedSeries,
    Step,
    SweepModel,
    TargetMode,
)
from kterminal.strategies.ict_sweep_models.levels import LiquiditySwings, RangeCandle
from kterminal.strategy_engine import (
    PendingEntryView,
    PositionEvent,
    PositionEventKind,
    SessionSpec,
    SessionString,
    SignalOutput,
    Strategy,
    StrategyMeta,
    StrategyParams,
    parse_session,
    register_strategy,
)

TZ = "America/New_York"  # the script's TZ constant (L26); its windows add ALL_DAYS (L27)
HTF = "15m"  # Model A's liquidity timeframe (request.security "15", L616)

AfterWindow = Literal["hold", "flat"]


class SweepParams(StrategyParams):
    """The script's General inputs used by models A and B (L37-42; Pine defaults and
    names) and the doc 13 D6 choice."""

    entry_mode: EntryMode = Field(
        "FVG edge", description="entryMode: limit at the FVG edge or its 50% (CE)"
    )
    mss_len: int = Field(2, ge=1, le=10, description="mssLen: 1m swing strength for the MSS")
    disp_mult: float = Field(
        1.5,
        ge=0.5,
        le=100,
        allow_inf_nan=False,
        description="dispMult: displacement body >= this × the 20-bar average body",
    )
    min_fvg_ticks: int = Field(0, ge=0, le=1_000_000, description="minFvgTicks")
    sl_buf_ticks: int = Field(0, ge=0, le=1_000_000, description="slBufTicks: stop buffer")
    min_rr: float = Field(
        1.0,
        ge=0,
        le=100,
        allow_inf_nan=False,
        description="minRR: a closer opposite level falls back to the fixed RR target",
    )
    after_window: AfterWindow = Field(
        "hold",
        description=(
            "hold: a filled trade runs until its stop, target or the model's next window "
            "start, as the script does; flat: it is closed at the window end (D6 variant)"
        ),
    )


class ModelAParams(SweepParams):
    """Model A's inputs (L44-48)."""

    a_swing: int = Field(2, ge=1, le=10, description="aSwing: 15m swing strength")
    a_win: SessionString = Field("2000-0200", description="aWin: trade window (New York)")
    a_tgt: TargetMode = Field("Opposite level", description="aTgt: target")
    a_rr: float = Field(
        2.0, ge=0.5, le=100, allow_inf_nan=False, description="aRR: fixed RR or fallback"
    )


class ModelBParams(SweepParams):
    """Model B's inputs (L50-54)."""

    b_range: SessionString = Field("0800-0900", description="bRange: range candle (New York)")
    b_win: SessionString = Field("0900-1200", description="bWin: trade window (New York)")
    b_tgt: TargetMode = Field("Opposite level", description="bTgt: target")
    b_rr: float = Field(
        2.0, ge=0.5, le=100, allow_inf_nan=False, description="bRR: fixed RR or fallback"
    )


class WindowClock:
    """One Pine session string evaluated once per bar: inside (``not na(time(...))``),
    window start (``inSess and not inSess[1]``) and the bars left in the occurrence.

    The previous bar's membership is the value this object computed on it, exactly
    Pine's ``inSess[1]``. The occurrence found last is reused while bars stay inside it.
    """

    __slots__ = ("_span", "inside", "previous", "spec")

    def __init__(self, session: str) -> None:
        self.spec: SessionSpec = parse_session(session, TZ)
        self._span: tuple[datetime, datetime] | None = None
        self.inside = False
        self.previous = False

    def update(self, open_time: datetime) -> None:
        span = self._span
        if span is None or not span[0] <= open_time < span[1]:
            span = self.spec.window_at(open_time)
        self._span = span
        self.previous, self.inside = self.inside, span is not None

    @property
    def started(self) -> bool:
        return self.inside and not self.previous

    @property
    def end(self) -> datetime | None:
        """End of the occurrence the bar is in (None outside)."""
        return self._span[1] if self.inside and self._span is not None else None


class SweepModelStrategy[P: SweepParams](Strategy[P]):
    """Models A and B: the shared engine and how its transitions become signals."""

    TAG: ClassVar[str]

    # ── model-specific parts ───────────────────────────────────────────────────
    @abstractmethod
    def _window(self) -> str:
        """The trade window session string (aWin / bWin)."""

    @abstractmethod
    def _engine_config(self, sl_buf: float) -> EngineConfig: ...

    @abstractmethod
    def _start_model(self) -> None:
        """Create the model's own level state."""

    @abstractmethod
    def _before_run(self, bar: Bar) -> None:
        """Update the model's levels with this bar (runs before ``SweepModel.run``)."""

    @abstractmethod
    def _levels(self, bar: Bar) -> tuple[float, float]:
        """``nHi, nLo``: the levels a window starting on this bar uses."""

    @abstractmethod
    def _level_metadata(self) -> dict[str, JsonValue]: ...

    # ── lifecycle ──────────────────────────────────────────────────────────────
    def on_start(self) -> None:
        p = self.params
        tick = float(self.ctx.instrument.tick_size)
        self._series = SharedSeries(p.mss_len, p.disp_mult, p.min_fvg_ticks * tick)
        self._model = SweepModel(self.TAG)
        self._config = self._engine_config(p.sl_buf_ticks * tick)
        self._clock = WindowClock(self._window())
        self._opened_at: datetime | None = None  # open time of the book's latest fill
        self._traded = False  # a fill since the last time exit: the next one must flatten
        self._start_levels: dict[str, JsonValue] = {}
        self._start_model()

    def on_position_event(self, event: PositionEvent) -> SignalOutput:
        if event.kind is PositionEventKind.OPENED:
            self._opened_at = event.time
            self._traded = True
        return None

    def on_bar(self, bar: Bar) -> SignalOutput:
        ctx = self.ctx
        state = self._series.update(
            ctx.bar_index, float(bar.open), float(bar.high), float(bar.low), float(bar.close)
        )
        self._before_run(bar)
        clock = self._clock
        clock.update(bar.open_time)
        start_now = clock.started
        new_hi, new_lo = self._levels(bar) if start_now else (math.nan, math.nan)
        step = self._model.run(
            state,
            self._series,
            self._config,
            active=clock.inside,
            start_now=start_now,
            new_hi=new_hi,
            new_lo=new_lo,
        )
        if start_now:
            self._start_levels = self._level_metadata()
        return self._signals(bar, step)

    # ── engine transitions → signals ───────────────────────────────────────────
    def _signals(self, bar: Bar, step: Step) -> list[Signal]:
        ctx = self.ctx
        model = self._model
        clock = self._clock
        out: list[Signal] = []
        flatten: Signal | None = None
        # The book filled our order on a bar where the script dropped the setup instead
        # (after the window end when its last bars are missing, or a "missed" on a bar
        # that reached the order's rounded CE price but not the script's). A fill while
        # the script still waits (a CE level rounded towards the market) is kept.
        late_fill = self._opened_at == bar.open_time and not step.filled and model.state != ARMED
        if step.started and self._traded:
            # L470-472: the open trade is closed (neutral) at the model's next window start
            flatten = self._flatten("closed", "window start: the script closes it")
        pending = ctx.pending_entry
        if flatten is None and pending is not None and model.state != ARMED:
            out.append(self._cancel(pending, step))
        if flatten is None and late_fill:
            flatten = self._flatten("late fill", "filled after the script cancelled")
        if flatten is None and self.params.after_window == "flat" and self._traded:
            end = clock.end
            window_over = (end is not None and end <= bar.close_time) or (
                not clock.inside and clock.previous
            )
            if window_over:  # D6 variant: flat at the window end
                flatten = self._flatten("window end", "flat at the window end (D6)")
        if flatten is not None:
            out.insert(0, flatten)
        if step.armed:
            out.append(self._entry(bar, step))
        return out

    def _entry(self, bar: Bar, step: Step) -> Signal:
        ctx = self.ctx
        model = self._model
        is_long = step.armed > 0
        bars_left = self._bars_left(bar)
        side = "long" if is_long else "short"
        metadata: dict[str, JsonValue] = {
            **self._common(f"{self.TAG} {side} setup"),
            "pine_signal": f"ev{self.TAG}",
            "ev": step.ev,
            **self._start_levels,
            "range_high": _num(model.hi),
            "range_low": _num(model.lo),
            "swept": "low" if is_long else "high",
            "sweep_extreme": _num(model.ext),
            "sweep_bar_index": model.ext_bar,
            "back_in": model.back_in,
            "mss_level": _num(model.mss_level),
            "mss_pivot_bar_index": model.mss_level_bar,
            "mss_bar_index": model.mss_bar,
            "fvg_top": _num(model.fvg_top),
            "fvg_bottom": _num(model.fvg_bot),
            "fvg_bar_index": model.fvg_bar,
            "displacement_body": _num(model.fvg_body),
            "avg_body": _num(model.fvg_avg_body),
            "entry_mode": self.params.entry_mode,
            "target_kind": model.target_kind,
            "script_entry": _num(model.entry),
            "script_stop": _num(model.sl),
            "script_target": _num(model.tp),
            "planned_rr": _num(_planned_rr(model)),
            "expires_after_bars": bars_left,
        }
        if bars_left < 1:
            # Armed on the window's last bar: the script cancels it before the next bar
            # can fill it (L491-492), so no order is placed.
            return ctx.no_trade("ARMED_ON_LAST_WINDOW_BAR", persist=True, metadata=metadata)
        problem = self._invalid_levels(is_long, model.entry, model.sl, model.tp)
        if problem is not None:  # doc 13 D3: no trade with levels on the wrong side
            return ctx.no_trade(problem, persist=True, metadata=metadata)
        build = ctx.long if is_long else ctx.short
        return build(
            entry=model.entry,
            stop_loss=model.sl,
            take_profit=model.tp,
            order_type=OrderType.LIMIT,
            expires_after_bars=bars_left,
            reason=f"Model {self.TAG} {side} setup: limit in the displacement FVG",
            metadata=metadata,
        )

    def _cancel(self, order: PendingEntryView, step: Step) -> Signal:
        """Cancel the book's resting limit: the script dropped the setup (or filled it
        where the book did not)."""
        if step.missed:
            trigger, why = f"{self.TAG} missed", "target traded before the fill"
        elif step.window_cancelled is not None:
            trigger, why = "window end", "unfilled limit cancelled at the window end"
        elif step.started:
            trigger, why = "window start", "unfilled limit cancelled at the window start"
        else:
            trigger, why = "fill not matched", "the script filled, the book did not"
        metadata = {**self._common(trigger), "order_entry": _decimal(order.entry)}
        is_long = order.direction is Direction.LONG
        build = self.ctx.exit_long if is_long else self.ctx.exit_short
        return build(reason=f"Model {self.TAG}: {why}", metadata=metadata)

    def _flatten(self, trigger: str, why: str) -> Signal:
        """A time exit at the next open (``SESSION_CLOSE``): ``ctx.flatten()`` closes the
        trade wherever it is still open — the theoretical book, the account or both — and
        changes nothing where it already closed."""
        self._traded = False
        position = self.ctx.position
        metadata: dict[str, JsonValue] = {
            **self._common(trigger),
            "detail": why,
            "pine_signal": "closeTrade(0)" if trigger == "closed" else None,
            "position_entry": None if position is None else _decimal(position.entry_price),
        }
        return self.ctx.flatten(metadata=metadata)

    def _common(self, trigger: str) -> dict[str, JsonValue]:
        return {
            "model": self.TAG,
            "trigger": trigger,
            "state": self._model.state,
            "window": self._window(),
            "after_window": self.params.after_window,
            "bar_index": self.ctx.bar_index,
        }

    def _invalid_levels(
        self, is_long: bool, entry: float, stop: float, target: float
    ) -> str | None:
        """Why the setup's levels cannot be traded after rounding to the tick, or None."""
        if na(entry) or na(stop) or na(target):
            return "LEVELS_NA"
        if entry <= 0 or stop <= 0 or target <= 0:
            return "LEVELS_NOT_POSITIVE"
        round_price = self.ctx.instrument.round_price
        e, s, t = (round_price(Decimal(repr(v))) for v in (entry, stop, target))
        if (s >= e) if is_long else (s <= e):
            return "STOP_WRONG_SIDE"
        if (t <= e) if is_long else (t >= e):
            return "TARGET_WRONG_SIDE"
        return None

    def _bars_left(self, bar: Bar) -> int:
        """Bars of this timeframe left in the window after ``bar``: the last one on which
        the script still checks the limit (L491-496) is the window's last bar."""
        end = self._clock.end
        if end is None:
            return 0
        return max(0, int((end - bar.close_time) / self.ctx.timeframe.duration))


@register_strategy
class IctModelA(SweepModelStrategy[ModelAParams]):
    meta = StrategyMeta(
        id="ict_model_a",
        name="ICT Sweep Models · A · 20:00 15m swing sweep",
        version="1.0.0",
        description=(
            "Pine port of script 2 Model A: after 20:00 New York a sweep of the most "
            "recent untaken 15m swing high/low, a 1m MSS and a displacement FVG arm a "
            "limit at the FVG edge; stop at the sweep extreme, target the opposite level "
            "or 2R. Doc 13 S5."
        ),
        timeframes=("1m",),
        context_timeframes=(HTF,),
        warmup_bars=480,  # 15m bars (the largest timeframe): 5 days of liquidity swings
        on_opposite_signal="ignore",  # doc 13 D4: one setup or trade at a time
        tags=("pine-port", "script-2", "s5", "model-a"),
    )
    Params = ModelAParams
    TAG = "A"

    def _window(self) -> str:
        return self.params.a_win

    def _engine_config(self, sl_buf: float) -> EngineConfig:
        p = self.params
        return EngineConfig(
            need_back=False,  # L783
            target_mode=p.a_tgt,
            rr=p.a_rr,
            min_rr=p.min_rr,
            entry_mode=p.entry_mode,
            sl_buf=sl_buf,
        )

    def _start_model(self) -> None:
        self._liquidity = LiquiditySwings(self.params.a_swing)
        self._last_htf: datetime | None = None  # open time of the last 15m bar fed

    def _before_run(self, bar: Bar) -> None:
        """Feed the 15m bars that closed by this bar's open (lookahead_on + [1])."""
        view = self.ctx.series(HTF, tradingview_lag=True)
        count = len(view)
        if count == 0:
            return
        last = self._last_htf
        if last is not None and view.bar(-1).open_time <= last:
            return
        fresh: list[Bar] = []
        for i in range(1, count + 1):
            htf = view.bar(-i)
            if last is not None and htf.open_time <= last:
                break
            fresh.append(htf)
        for htf in reversed(fresh):
            self._liquidity.update(float(htf.high), float(htf.low), htf.open_time)
        self._last_htf = fresh[0].open_time

    def _levels(self, bar: Bar) -> tuple[float, float]:
        return self._liquidity.last_high, self._liquidity.last_low  # aHi15, aLo15

    def _level_metadata(self) -> dict[str, JsonValue]:
        liquidity = self._liquidity
        return {
            "level_high_pivot_time": _iso(liquidity.last_high_time),
            "level_low_pivot_time": _iso(liquidity.last_low_time),
            "levels_from_15m_bar": _iso(self._last_htf),
        }


@register_strategy
class IctModelB(SweepModelStrategy[ModelBParams]):
    meta = StrategyMeta(
        id="ict_model_b",
        name="ICT Sweep Models · B · 08:00 candle sweep",
        version="1.0.0",
        description=(
            "Pine port of script 2 Model B: after 09:00 New York a sweep of the 08:00 "
            "candle's high/low, a close back inside, a 1m MSS and a displacement FVG arm a "
            "limit at the FVG edge; stop at the sweep extreme, target the opposite side "
            "or 2R. Doc 13 S4."
        ),
        timeframes=("1m",),
        warmup_bars=2_880,  # two days of 1m bars: the range, the pivots and SMA20(body)
        on_opposite_signal="ignore",  # doc 13 D4: one setup or trade at a time
        tags=("pine-port", "script-2", "s4", "model-b"),
    )
    Params = ModelBParams
    TAG = "B"

    def _window(self) -> str:
        return self.params.b_win

    def _engine_config(self, sl_buf: float) -> EngineConfig:
        p = self.params
        return EngineConfig(
            need_back=True,  # L797
            target_mode=p.b_tgt,
            rr=p.b_rr,
            min_rr=p.min_rr,
            entry_mode=p.entry_mode,
            sl_buf=sl_buf,
        )

    def _start_model(self) -> None:
        self._range = RangeCandle()
        self._range_clock = WindowClock(self.params.b_range)

    def _before_run(self, bar: Bar) -> None:
        """L786-794: the range is built from chart bars before ``mB.run``."""
        clock = self._range_clock
        clock.update(bar.open_time)
        if clock.inside:
            self._range.update(float(bar.high), float(bar.low), bar.open_time, first=clock.started)

    def _levels(self, bar: Bar) -> tuple[float, float]:
        candle = self._range
        if candle.fresh(bar.open_time):  # bFresh (L796)
            return candle.high, candle.low
        return math.nan, math.nan

    def _level_metadata(self) -> dict[str, JsonValue]:
        candle = self._range
        return {
            "range_start": _iso(candle.start),
            "range_bars": candle.bars,
            "range_fresh": candle.fresh(self.ctx.bar.open_time),
        }


def _planned_rr(model: SweepModel) -> float:
    risk = abs(model.entry - model.sl)
    return abs(model.tp - model.entry) / risk if risk > 0 else math.nan


def _decimal(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _num(value: float) -> float | None:
    """A float for JSON metadata: na becomes null."""
    return None if na(value) else float(value)
