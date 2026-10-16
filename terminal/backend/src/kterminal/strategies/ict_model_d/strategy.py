"""ICT Sweep + Order Flow Models [NY] — Model D (S11): order-flow absorption (doc 13).

Port of Model D of ``terminal/pine/received/02_ict_sweep_order_flow_models.pine``
(spec ``terminal/pine/specs/02_ict_sweep_order_flow_models.md``); line numbers refer to
the received file. Every closed 1m bar, in the script's order (New York time, all seven
days):

1. ``ta.atr(14)`` and the level tolerance (L160-161), the candle-estimate order flow
   and the aggressive flags (L627-643) — ``flow.py``;
2. the script's own D trade is managed: stop first, then target, from the bar after
   its signal (L779) — model D looks for setups only while it is closed;
3. the overnight session 18:00-09:30 builds its volume profile; on the first bar after
   it the value area high/low and the overnight high/low become key levels (L835-854)
   — ``profile.py``;
4. a fresh 15m gap becomes a zone, zones closed through die, and the bar is at
   support / resistance when its range overlaps a bullish / bearish zone (L856-865) —
   ``zones.py``; any key level (VAH, VAL, overnight high/low, previous day high/low
   from ``ctx.periods`` on the D8 trading day, manual levels) within ``dTolAtr`` × ATR
   of the bar's range puts it at both (L866-871);
5. at the first bar of ``dWin`` (09:30-16:00) the candidates reset and the previous
   trade is closed: ``ctx.flatten()`` (doc 13 D6, the script's neutral close); outside
   the window the candidates reset (L873-880);
6. inside the window, while the script's trade is closed (L881-924): an aggressive
   selling bar at support becomes a long candidate (its body top, its low, the lowest
   low since); a later aggressive buying bar that closes above the body top within
   ``dMaxBars`` bars — before any close below the candidate's low — is the long: a
   MARKET entry at the next open with the stop at the lowest low since the candidate ∓
   buffer and the target ``dRR`` × risk from the signal close. Shorts mirror it, after
   the long branch. Doc 13 D3: the entry is skipped when the next open is at or beyond
   either level (``skip_entry_beyond_levels``) and not sent when a level is on the
   wrong side after tick rounding.

``after_window: flat`` (the D6 variant) closes the trade at the 16:00 window end
instead. The README lists every deviation from the script.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field, JsonValue

from kterminal.domain.market import Bar
from kterminal.domain.signals import Signal
from kterminal.domain.timeframes import Timeframe
from kterminal.indicators import Atr, ge, gt, le, lt, na, nz
from kterminal.strategies.ict_model_d.flow import CandleFlow, Flow, ScriptTrade
from kterminal.strategies.ict_model_d.profile import OvernightProfile
from kterminal.strategies.ict_model_d.zones import HtfFvgFeed, Zone, ZoneBook
from kterminal.strategy_engine import (
    PeriodBar,
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
ATR_LENGTH = 14  # ta.atr(14) (L160)

ZoneMode = Literal["HTF FVG + key levels", "HTF FVG only", "Key levels only"]
FvgTimeframe = Literal["5m", "15m", "30m", "1h"]
DeltaSource = Literal["Candle estimate"]
AfterWindow = Literal["hold", "flat"]

TRIGGER_LONG = "D long"  # the script's alertcondition titles (L971-972)
TRIGGER_SHORT = "D short"


class ModelDParams(StrategyParams):
    """Model D's inputs (L66-84), the General input it uses (L41; Pine defaults and
    names) and the doc 13 D6 choice."""

    d_win: SessionString = Field("0930-1600", description="dWin: trade window (New York)")
    d_zone_mode: ZoneMode = Field("HTF FVG + key levels", description="dZoneMode: where to look")
    d_fvg_tf: FvgTimeframe = Field("15m", description="dFvgTF: HTF FVG timeframe (Pine '15')")
    d_delta: DeltaSource = Field(
        "Candle estimate",
        description="dDelta: delta source; 'Intrabar (lower TF)' needs seconds data (not ported)",
    )
    d_vol_mult: float = Field(
        1.5,
        ge=1.0,
        le=100,
        allow_inf_nan=False,
        description="dVolMult: aggressive when volume >= this × the 20-bar average",
    )
    d_delta_pct: float = Field(
        30.0,
        ge=5.0,
        le=100.0,
        allow_inf_nan=False,
        description="dDeltaPct: aggressive when |delta| >= this % of the volume",
    )
    d_max_bars: int = Field(
        10, ge=2, le=10_000, description="dMaxBars: max bars from the cluster to the reversal"
    )
    d_rr: float = Field(2.0, ge=0.5, le=100, allow_inf_nan=False, description="dRR: target RR")
    d_tol_atr: float = Field(
        0.25,
        ge=0.0,
        le=100,
        allow_inf_nan=False,
        description="dTolAtr: level touch tolerance as a multiple of ATR(14)",
    )
    d_on_sess: SessionString = Field(
        "1800-0930", description="dOnSess: overnight session (New York)"
    )
    d_va_pct: float = Field(
        70.0, ge=50.0, le=95.0, allow_inf_nan=False, description="dVaPct: value area %"
    )
    d_rows: int = Field(50, ge=10, le=200, description="dRows: profile rows")
    use_va: bool = Field(True, description="useVA: overnight value area high/low as levels")
    use_on: bool = Field(True, description="useON: overnight high/low as levels")
    use_pd: bool = Field(True, description="usePD: previous day high/low as levels")
    d_man1: float = Field(
        0.0, ge=-1e12, le=1e12, allow_inf_nan=False, description="dMan1: manual level (0 = off)"
    )
    d_man2: float = Field(
        0.0, ge=-1e12, le=1e12, allow_inf_nan=False, description="dMan2: manual level (0 = off)"
    )
    sl_buf_ticks: int = Field(0, ge=0, le=1_000_000, description="slBufTicks: stop buffer")
    after_window: AfterWindow = Field(
        "hold",
        description=(
            "hold: the trade runs until its stop, target or the next window start, as the "
            "script does; flat: it is closed at the window end (D6 variant)"
        ),
    )


class WindowClock:
    """One Pine session string evaluated once per bar: inside (``not na(time(...))``),
    window start (``inSess and not inSess[1]``) and the end of the occurrence.

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
    def ended(self) -> bool:
        """The first bar after an occurrence (``not inSess and inSess[1]``)."""
        return self.previous and not self.inside

    @property
    def end(self) -> datetime | None:
        """End of the occurrence the bar is in (None outside)."""
        return self._span[1] if self.inside and self._span is not None else None

    def last_bar(self, close_time: datetime) -> bool:
        """The bar closing at ``close_time`` is the occurrence's last one."""
        end = self.end
        return end is not None and end <= close_time

    def over(self, close_time: datetime) -> bool:
        """The window ends with this bar, or ended before it (its last bar is missing)."""
        return self.last_bar(close_time) or self.ended


@dataclass(slots=True)
class _Candidate:
    """An absorption candidate (``dLS == 1`` with ``dLTop/dLLow0/dLExt/dLBar``, or the
    short mirror ``dSS/dSBot/dSHigh0/dSExt/dSBar``), L897-902 / L919-924."""

    dir: int  # +1: sellers absorbed (long), -1: buyers absorbed (short)
    edge: float  # dLTop = max(open, close) / dSBot = min(open, close)
    origin: float  # dLLow0 = low / dSHigh0 = high
    ext: float  # dLExt / dSExt: the extreme since the candidate bar
    bar: int  # dLBar / dSBar
    time: datetime
    flow: Flow
    location: list[JsonValue] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _Setup:
    """A trade the script opened on this bar (L887-891 / L909-913)."""

    dir: int
    candidate: _Candidate
    entry: float
    sl: float
    tp: float
    risk: float


@register_strategy
class IctModelD(Strategy[ModelDParams]):
    meta = StrategyMeta(
        id="ict_model_d",
        name="ICT Sweep Models · D · Order-flow absorption",
        version="1.0.0",
        description=(
            "Pine port of script 2 Model D: at a 15m FVG or a key level (overnight value "
            "area, overnight high/low, previous day high/low) an aggressive selling bar "
            "(candle-estimate delta) is absorbed when an aggressive buying bar closes above "
            "its body within 10 bars, 09:30-16:00 New York; market entry, stop at the "
            "absorption low, 2R target (shorts mirror it). Doc 13 S11."
        ),
        timeframes=("1m",),
        context_timeframes=("15m",),
        # 15m bars (the largest timeframe): two days round the clock for ATR(14), the
        # volume average, the 15m zones and a complete overnight session; the previous
        # trading day (ctx.periods) adds its own warm-up in forward sessions
        warmup_bars=200,
        on_opposite_signal="ignore",  # doc 13 D4: one trade at a time, as the script
        skip_entry_beyond_levels=True,  # doc 13 D3: priced at the signal bar's close
        tags=("pine-port", "script-2", "s11", "model-d"),
    )
    Params = ModelDParams

    # ── lifecycle ──────────────────────────────────────────────────────────────
    def on_start(self) -> None:
        p = self.params
        ctx = self.ctx
        self._use_zones = p.d_zone_mode != "Key levels only"  # useFvgZ (L101)
        self._use_levels = p.d_zone_mode != "HTF FVG only"  # useLvls (L102)
        if self._use_zones and Timeframe.parse(p.d_fvg_tf) not in set(ctx.timeframes):
            raise ValueError(
                f"d_fvg_tf {p.d_fvg_tf} is not a timeframe of this instance: add it to its "
                "context_timeframes"
            )
        self._sl_buf = p.sl_buf_ticks * float(ctx.instrument.tick_size)  # slBuf (L156)
        self._atr = Atr(ATR_LENGTH)  # L160
        self._flow = CandleFlow(p.d_vol_mult, p.d_delta_pct)
        self._trade = ScriptTrade()  # tD
        self._profile = OvernightProfile(p.d_rows, p.d_va_pct)
        self._on_clock = WindowClock(p.d_on_sess)  # inON
        self._clock = WindowClock(p.d_win)  # inD
        self._fvg_feed = HtfFvgFeed()
        self._zones = ZoneBook()
        self._long: _Candidate | None = None  # dLS == 1
        self._short: _Candidate | None = None  # dSS == 1
        self._traded = False  # a fill since the last time exit: the next one must flatten

    def on_position_event(self, event: PositionEvent) -> SignalOutput:
        if event.kind is PositionEventKind.OPENED:
            self._traded = True
        return None

    def on_bar(self, bar: Bar) -> SignalOutput:
        ctx = self.ctx
        p = self.params
        index = ctx.bar_index
        h, low, c = float(bar.high), float(bar.low), float(bar.close)
        volume = nz(float(bar.volume))
        atr = self._atr.update(h, low, c)  # L160
        tol = p.d_tol_atr * atr  # L161
        flow = self._flow.update(h, low, c, volume)  # L627-643
        self._trade.manage(index, h, low)  # L779

        on = self._on_clock  # L835-854
        on.update(bar.open_time)
        self._profile.update(h, low, volume, inside=on.inside, started=on.started, ended=on.ended)

        support: list[Zone] = []
        resistance: list[Zone] = []
        if self._use_zones:  # L856-865
            fresh = self._fvg_feed.update(ctx.series(p.d_fvg_tf, tradingview_lag=True))
            if fresh is not None:
                if fresh.bull:
                    self._zones.add(
                        Zone(1, fresh.bull_top, fresh.bull_bot, fresh.start, bar.open_time)
                    )
                if fresh.bear:
                    self._zones.add(
                        Zone(-1, fresh.bear_top, fresh.bear_bot, fresh.start, bar.open_time)
                    )
            self._zones.update(c)
            support, resistance = self._zones.touch(h, low)
        touched: list[tuple[str, float]] = []
        if self._use_levels:  # L866-871: every key level is support and resistance
            touched = [
                (name, level)
                for name, level in self._key_levels()
                if not na(level) and le(low, level + tol) and ge(h, level - tol)
            ]
        at_sup = bool(support) or bool(touched)
        at_res = bool(resistance) or bool(touched)

        clock = self._clock
        clock.update(bar.open_time)
        flatten: Signal | None = None
        if clock.started:  # L873-877
            self._long = self._short = None
            self._trade.close(0)
            if self._traded:
                flatten = self._flatten("closed", "window start: the script closes it")
        setup: _Setup | None = None
        if not clock.inside:  # L878-880
            self._long = self._short = None
        elif not self._trade.live:  # L881
            setup = self._long_branch(bar, index, flow, at_sup, support, touched)
            if not self._trade.live:  # L904
                setup = self._short_branch(bar, index, flow, at_res, resistance, touched) or setup

        out: list[Signal] = []
        if setup is not None:
            entry = self._entry(bar, setup, flow, atr, tol)
            if flatten is None and entry.signal.is_entry and ctx.position is not None:
                # the book still holds the previous D trade, which the script closed at
                # its stop or target already: close it at the open the new one fills at
                flatten = self._flatten(
                    "replaced",
                    "the script's previous trade closed; the new one replaces it",
                    reason="Model D: the script closed the previous trade, a new one replaces it",
                )
            out.append(entry)
        if (
            flatten is None
            and p.after_window == "flat"
            and self._traded
            and clock.over(bar.close_time)
        ):  # D6 variant: flat at the window end
            flatten = self._flatten("window end", "flat at the window end (D6)")
        if flatten is not None:
            out.insert(0, flatten)
        return out

    # ── the script's state ─────────────────────────────────────────────────────
    def _key_levels(self) -> list[tuple[str, float]]:
        """``lv`` (L867), na where switched off or unknown."""
        p = self.params
        profile = self._profile
        previous_day = self.ctx.periods.previous("D")  # [pdh, pdl] (L620)
        return [
            ("VAH", profile.vah if p.use_va else math.nan),
            ("VAL", profile.val if p.use_va else math.nan),
            ("ONH", profile.levels_high if p.use_on else math.nan),
            ("ONL", profile.levels_low if p.use_on else math.nan),
            ("PDH", _high(previous_day) if p.use_pd else math.nan),
            ("PDL", _low(previous_day) if p.use_pd else math.nan),
            ("manual 1", p.d_man1 if p.d_man1 > 0 else math.nan),
            ("manual 2", p.d_man2 if p.d_man2 > 0 else math.nan),
        ]

    def _long_branch(
        self,
        bar: Bar,
        index: int,
        flow: Flow,
        at_sup: bool,
        support: list[Zone],
        touched: list[tuple[str, float]],
    ) -> _Setup | None:
        """L883-902: sellers absorbed, then buyers close above them."""
        p = self.params
        c, low = float(bar.close), float(bar.low)
        setup: _Setup | None = None
        cand = self._long
        if cand is not None:
            cand.ext = min(cand.ext, low)  # L884
            if lt(c, cand.origin) or index - cand.bar > p.d_max_bars:  # L885-886
                self._long = None
            elif flow.aggr_buy and gt(c, cand.edge):  # L887
                sl = cand.ext - self._sl_buf  # L888
                risk = c - sl  # L889
                if gt(risk, 0.0):  # L890-892
                    tp = c + p.d_rr * risk
                    self._trade.open(1, c, sl, tp, index)
                    setup = _Setup(1, cand, c, sl, tp, risk)
                self._long = None  # L895-896
                self._short = None
        if self._long is None and not self._trade.live and flow.aggr_sell and at_sup:  # L897
            self._long = _Candidate(
                dir=1,
                edge=max(float(bar.open), c),
                origin=low,
                ext=low,
                bar=index,
                time=bar.open_time,
                flow=flow,
                location=_location(support, touched, self.params.d_fvg_tf),
            )
        return setup

    def _short_branch(
        self,
        bar: Bar,
        index: int,
        flow: Flow,
        at_res: bool,
        resistance: list[Zone],
        touched: list[tuple[str, float]],
    ) -> _Setup | None:
        """L905-924: buyers absorbed, then sellers close below them."""
        p = self.params
        c, high = float(bar.close), float(bar.high)
        setup: _Setup | None = None
        cand = self._short
        if cand is not None:
            cand.ext = max(cand.ext, high)  # L906
            if gt(c, cand.origin) or index - cand.bar > p.d_max_bars:  # L907-908
                self._short = None
            elif flow.aggr_sell and lt(c, cand.edge):  # L909
                sl = cand.ext + self._sl_buf  # L910
                risk = sl - c  # L911
                if gt(risk, 0.0):  # L912-914
                    tp = c - p.d_rr * risk
                    self._trade.open(-1, c, sl, tp, index)
                    setup = _Setup(-1, cand, c, sl, tp, risk)
                self._long = None  # L917-918
                self._short = None
        if self._short is None and not self._trade.live and flow.aggr_buy and at_res:  # L919
            self._short = _Candidate(
                dir=-1,
                edge=min(float(bar.open), c),
                origin=high,
                ext=high,
                bar=index,
                time=bar.open_time,
                flow=flow,
                location=_location(resistance, touched, self.params.d_fvg_tf),
            )
        return setup

    # ── signals ────────────────────────────────────────────────────────────────
    def _entry(self, bar: Bar, setup: _Setup, flow: Flow, atr: float, tol: float) -> Signal:
        ctx = self.ctx
        p = self.params
        long = setup.dir > 0
        cand = setup.candidate
        profile = self._profile
        levels: dict[str, JsonValue] = {name: _num(lv) for name, lv in self._key_levels()}
        levels["POC"] = _num(profile.poc)
        metadata: dict[str, JsonValue] = {
            **self._common(TRIGGER_LONG if long else TRIGGER_SHORT),
            "pine_signal": "evD",
            "trade_tag": "D absorption",  # L891 / L913
            "absorbed": "sellers" if long else "buyers",
            "candidate": {
                "bar_index": cand.bar,
                "time": cand.time.isoformat(),
                "bars_ago": ctx.bar_index - cand.bar,
                "body_edge": cand.edge,
                "origin": cand.origin,
                "extreme": cand.ext,
                **_flow_metadata(cand.flow),
                "at": cand.location,
            },
            "trigger_bar": _flow_metadata(flow),
            "atr": _num(atr),
            "tolerance": _num(tol),
            "levels": levels,
            "zones_live": len(self._zones.zones),
            "zone_mode": p.d_zone_mode,
            "delta_source": p.d_delta,
            "script_entry": setup.entry,
            "script_stop": setup.sl,
            "script_target": setup.tp,
            "risk_points": setup.risk,
            "planned_rr": p.d_rr,
        }
        if p.after_window == "flat" and self._clock.last_bar(bar.close_time):
            # D6 variant: the trade would fill at the open the window-end flatten closes it
            return ctx.no_trade("ENTRY_ON_LAST_WINDOW_BAR", persist=True, metadata=metadata)
        problem = self._invalid_levels(long, setup.entry, setup.sl, setup.tp)
        if problem is not None:  # doc 13 D3: no trade with levels on the wrong side
            return ctx.no_trade(problem, persist=True, metadata=metadata)
        build = ctx.long if long else ctx.short
        who = "sellers" if long else "buyers"
        return build(
            stop_loss=setup.sl,
            take_profit=setup.tp,
            reason=f"Model D {'long' if long else 'short'}: aggressive {who} absorbed",
            metadata=metadata,
        )

    def _flatten(self, trigger: str, why: str, *, reason: str | None = None) -> Signal:
        """Close the trade at the next open wherever it is still open — the theoretical
        book, the account or both — changing nothing where it already closed. A time exit
        (``SESSION_CLOSE``) unless ``reason`` is given (then ``SIGNAL_EXIT``)."""
        self._traded = False
        position = self.ctx.position
        metadata: dict[str, JsonValue] = {
            **self._common(trigger),
            "detail": why,
            "pine_signal": "closeTrade(0)" if trigger == "closed" else None,
            "position_entry": None if position is None else str(position.entry_price),
        }
        if reason is None:
            return self.ctx.flatten(metadata=metadata)
        return self.ctx.flatten(reason=reason, metadata=metadata)

    def _common(self, trigger: str) -> dict[str, JsonValue]:
        return {
            "model": "D",
            "trigger": trigger,
            "window": self.params.d_win,
            "after_window": self.params.after_window,
            "bar_index": self.ctx.bar_index,
        }

    def _invalid_levels(self, long: bool, entry: float, stop: float, target: float) -> str | None:
        """Why the levels cannot be traded after rounding to the tick, or None."""
        if na(entry) or na(stop) or na(target):
            return "LEVELS_NA"
        if entry <= 0 or stop <= 0 or target <= 0:
            return "LEVELS_NOT_POSITIVE"
        round_price = self.ctx.instrument.round_price
        e, s, t = (round_price(Decimal(repr(v))) for v in (entry, stop, target))
        if (s >= e) if long else (s <= e):
            return "STOP_WRONG_SIDE"
        if (t <= e) if long else (t >= e):
            return "TARGET_WRONG_SIDE"
        return None


def _location(zones: list[Zone], touched: list[tuple[str, float]], tf: str) -> list[JsonValue]:
    """What put the candidate bar at support / resistance (signal metadata)."""
    out: list[JsonValue] = [
        {"kind": f"{tf} FVG", "top": z.top, "bottom": z.bot, "first_candle": z.start.isoformat()}
        for z in zones
    ]
    out += [{"kind": "level", "name": name, "price": level} for name, level in touched]
    return out


def _flow_metadata(flow: Flow) -> dict[str, JsonValue]:
    return {
        "volume": flow.volume,
        "avg_volume": _num(flow.avg_volume),
        "delta": flow.delta,
        "delta_pct": _num(flow.delta_pct),
    }


def _high(period: PeriodBar | None) -> float:
    return math.nan if period is None else float(period.high)


def _low(period: PeriodBar | None) -> float:
    return math.nan if period is None else float(period.low)


def _num(value: float) -> float | None:
    """A float for JSON metadata: na becomes null."""
    return None if na(value) or math.isinf(value) else float(value)
