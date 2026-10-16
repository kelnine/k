"""ICT Sweep + Order Flow Models [NY] — Model C (S9): PD-array bias + IFVG / CISD (doc 13).

Port of Model C of ``terminal/pine/received/02_ict_sweep_order_flow_models.pine``
(spec ``terminal/pine/specs/02_ict_sweep_order_flow_models.md``); line numbers refer to
the received file. Every closed 1m bar, in the script's order (New York time, all seven
days):

1. the shared 1m gaps (L163-168), the CISD run opens (L740-743) and the 1m gaps waiting
   to be inverted (L745-773) — ``triggers.py``;
2. the bias and the draw on liquidity of the last closed bias-timeframe bar
   (``f_pdBias`` through ``request.security(cBiasTF, …, lookahead_on)``, L617, L622) —
   ``bias.py``, fed from ``ctx.series("1h", tradingview_lag=True)``;
3. a fresh 5m gap becomes a zone (``f_htfFvg``, L618, L623, L801-805), then every zone
   is updated with this bar around the clock (``f_updateZones``, L806) — ``zones.py``;
4. at the first bar of ``cWin`` (09:30-12:00) the day's count resets (L807-808) and the
   previous trade is closed: ``ctx.flatten()`` (doc 13 D6, the script's neutral close);
5. inside the window, with no trade yet today and a non-zero bias, the newest unused
   zone of the bias direction that was tapped and whose extreme is at most ``cLook``
   bars old triggers on a 1m IFVG or a close beyond its CISD level (L811-830): a
   MARKET entry at the next open with the script's stop (the zone extreme ∓ buffer)
   and target (the draw on liquidity when it is at least ``minRR`` × risk away, else
   ``cRR`` × risk), both computed from the signal close. Doc 13 D3: the entry is
   skipped when the next open is at or beyond either (``skip_entry_beyond_levels``)
   and not sent when a level is on the wrong side after tick rounding.

``after_window: flat`` (the D6 variant) closes the trade at the 12:00 window end
instead. The README lists every deviation from the script.
"""

import math
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field, JsonValue

from kterminal.domain.market import Bar
from kterminal.domain.signals import Signal
from kterminal.domain.timeframes import Timeframe
from kterminal.indicators import ge, gt, lt, na
from kterminal.strategies.ict_model_c.bias import PdBias
from kterminal.strategies.ict_model_c.triggers import (
    ChartGaps,
    InversionGaps,
    Inversions,
    RunOpens,
)
from kterminal.strategies.ict_model_c.zones import HtfFvgFeed, Zone, ZoneBook
from kterminal.strategy_engine import (
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

BiasTimeframe = Literal["15m", "30m", "1h", "4h"]
FvgTimeframe = Literal["5m", "15m"]
TriggerMode = Literal["IFVG or CISD", "IFVG only", "CISD only"]
TargetMode = Literal["Draw on liquidity", "Fixed RR"]
AfterWindow = Literal["hold", "flat"]

TRIGGER_LONG = "C long"  # the script's alertcondition titles (L969-970)
TRIGGER_SHORT = "C short"


class ModelCParams(StrategyParams):
    """Model C's inputs (L56-64), the General inputs it uses (L40, L41, L42; Pine
    defaults and names) and the doc 13 D6 choice."""

    c_bias_tf: BiasTimeframe = Field(
        "1h", description="cBiasTF: bias and liquidity timeframe (Pine '60')"
    )
    c_fvg_tf: FvgTimeframe = Field("5m", description="cFvgTF: setup FVG timeframe (Pine '5')")
    c_win: SessionString = Field("0930-1200", description="cWin: trade window (New York)")
    c_trig: TriggerMode = Field("IFVG or CISD", description="cTrig: 1m trigger")
    c_look: int = Field(
        30, ge=5, le=10_000, description="cLook: trigger lookback in 1m bars (IFVG age, extreme)"
    )
    c_liq_len: int = Field(
        3, ge=1, le=10, description="cLiqLen: liquidity swing strength on the bias timeframe"
    )
    c_tgt: TargetMode = Field("Draw on liquidity", description="cTgt: target")
    c_rr: float = Field(
        2.0, ge=0.5, le=100, allow_inf_nan=False, description="cRR: fixed RR or fallback"
    )
    min_rr: float = Field(
        1.0,
        ge=0,
        le=100,
        allow_inf_nan=False,
        description="minRR: a closer draw on liquidity falls back to the fixed RR target",
    )
    min_fvg_ticks: int = Field(
        0, ge=0, le=1_000_000, description="minFvgTicks: minimum 1m gap for the IFVG list"
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
    def end(self) -> datetime | None:
        """End of the occurrence the bar is in (None outside)."""
        return self._span[1] if self.inside and self._span is not None else None

    def last_bar(self, close_time: datetime) -> bool:
        """The bar closing at ``close_time`` is the occurrence's last one."""
        end = self.end
        return end is not None and end <= close_time

    def over(self, close_time: datetime) -> bool:
        """The window ends with this bar, or ended before it (its last bar is missing)."""
        return self.last_bar(close_time) or (not self.inside and self.previous)


@dataclass(frozen=True, slots=True)
class _Setup:
    """What the trigger scan found on this bar (L816-829)."""

    zone: Zone
    via_ifvg: bool
    via_cisd: bool
    sl: float
    risk: float
    dol: float
    dol_time: datetime | None
    dol_ok: bool
    tp: float

    @property
    def dir(self) -> int:
        return self.zone.dir


@register_strategy
class IctModelC(Strategy[ModelCParams]):
    meta = StrategyMeta(
        id="ict_model_c",
        name="ICT Sweep Models · C · PD-array bias + IFVG / CISD",
        version="1.0.0",
        description=(
            "Pine port of script 2 Model C: the 1H PD-array bias picks the side; a 5m FVG "
            "of that side tapped (around the clock) triggers in 09:30-12:00 New York on a "
            "1m inversion FVG or a close beyond the zone's CISD level; market entry, stop "
            "at the zone extreme, target the 1H draw on liquidity or 2R; one trade a day. "
            "Doc 13 S9."
        ),
        timeframes=("1m",),
        context_timeframes=("5m", "1h"),
        # 1h bars (the largest timeframe): a week round the clock for the persistent
        # bias, the 1H gaps and the untaken pivots (10,140 1m bars)
        warmup_bars=168,
        on_opposite_signal="ignore",  # doc 13 D4: one trade a day, never two at once
        skip_entry_beyond_levels=True,  # doc 13 D3: priced at the signal bar's close
        tags=("pine-port", "script-2", "s9", "model-c"),
    )
    Params = ModelCParams

    # ── lifecycle ──────────────────────────────────────────────────────────────
    def on_start(self) -> None:
        p = self.params
        ctx = self.ctx
        declared = set(ctx.timeframes)
        for name, tf in (("c_bias_tf", p.c_bias_tf), ("c_fvg_tf", p.c_fvg_tf)):
            if Timeframe.parse(tf) not in declared:
                raise ValueError(
                    f"{name} {tf} is not a timeframe of this instance: add it to its "
                    "context_timeframes"
                )
        tick = float(ctx.instrument.tick_size)
        self._sl_buf = p.sl_buf_ticks * tick  # slBuf (L156)
        self._gaps = ChartGaps(p.min_fvg_ticks * tick)  # minGap (L157)
        self._runs = RunOpens()
        self._inversions = InversionGaps(p.c_look)
        self._bias = PdBias(p.c_liq_len)
        self._bias_last: datetime | None = None  # open time of the last bias bar fed
        self._fvg_feed = HtfFvgFeed()
        self._zones = ZoneBook()
        self._clock = WindowClock(p.c_win)
        self._taken = 0  # cTaken (L686)
        self._traded = False  # a fill since the last time exit: the next one must flatten

    def on_position_event(self, event: PositionEvent) -> SignalOutput:
        if event.kind is PositionEventKind.OPENED:
            self._traded = True
        return None

    def on_bar(self, bar: Bar) -> SignalOutput:
        ctx = self.ctx
        p = self.params
        index = ctx.bar_index
        o, h, low, c = float(bar.open), float(bar.high), float(bar.low), float(bar.close)
        gaps = self._gaps.update(h, low)  # L163-168
        runs = self._runs
        runs.update(index, o, c)  # L740-743
        inversions = self._inversions.update(index, c, gaps)  # L745-773
        self._feed_bias()  # L617, L622
        fresh = self._fvg_feed.update(ctx.series(p.c_fvg_tf, tradingview_lag=True))  # L618
        if fresh is not None:  # L801-805
            if fresh.bull:
                self._add_zone(1, fresh.bull_top, fresh.bull_bot, fresh.start, bar, index)
            if fresh.bear:
                self._add_zone(-1, fresh.bear_top, fresh.bear_bot, fresh.start, bar, index)
        self._zones.update(index, h, low, c, runs.bear_run_open, runs.bull_run_open)  # L806

        clock = self._clock
        clock.update(bar.open_time)
        flatten: Signal | None = None
        if clock.started:  # L807-810
            self._taken = 0
            if self._traded:
                flatten = self._flatten("closed", "window start: the script closes it")
        setup = None
        bias = self._bias.bias  # cBiasNow = nz(cBias)
        if clock.inside and self._taken < 1 and bias != 0:  # L811
            setup = self._trigger(index, c, bias, inversions)
        if (
            flatten is None
            and p.after_window == "flat"
            and self._traded
            and clock.over(bar.close_time)
        ):  # D6 variant: flat at the window end
            flatten = self._flatten("window end", "flat at the window end (D6)")
        out: list[Signal] = [] if flatten is None else [flatten]
        if setup is not None:
            out.append(self._entry(bar, setup, inversions))
        return out

    # ── the script's state ─────────────────────────────────────────────────────
    def _feed_bias(self) -> None:
        """Feed ``f_pdBias`` every bias-timeframe bar closed by this bar's open (L617)."""
        view = self.ctx.series(self.params.c_bias_tf, tradingview_lag=True)
        count = len(view)
        if count == 0:
            return
        last = self._bias_last
        if last is not None and view.bar(-1).open_time <= last:
            return
        fresh: list[Bar] = []
        for i in range(1, count + 1):
            htf = view.bar(-i)
            if last is not None and htf.open_time <= last:
                break
            fresh.append(htf)
        for htf in reversed(fresh):
            self._bias.update(float(htf.high), float(htf.low), float(htf.close), htf.open_time)
        self._bias_last = fresh[0].open_time

    def _add_zone(
        self, direction: int, top: float, bot: float, start: datetime, bar: Bar, index: int
    ) -> None:
        """``f_addZone(cZones, dir, top, bot, cT)`` (L358-368)."""
        self._zones.add(Zone(direction, top, bot, start, bar.open_time, index))

    def _trigger(self, index: int, close: float, bias: int, inv: Inversions) -> _Setup | None:
        """The trigger scan of L812-830, newest zone first; marks the zone used and counts
        the trade (``cTaken``) whether or not the lab can trade it."""
        p = self.params
        zones = self._zones.zones
        for i in range(len(zones) - 1, -1, -1):
            z = zones[i]
            if not (z.dir == bias and z.tapped and not z.used):  # L816
                continue
            if z.ext_bar is None or z.tap_bar is None or index - z.ext_bar > p.c_look:
                continue
            long = z.dir > 0
            via_ifvg = p.c_trig != "CISD only" and (  # L817
                (inv.bull and inv.bull_bar is not None and inv.bull_bar >= z.tap_bar - p.c_look)
                if long
                else (
                    inv.bear and inv.bear_bar is not None and inv.bear_bar >= z.tap_bar - p.c_look
                )
            )
            via_cisd = (  # L818: a level test, not a cross
                p.c_trig != "IFVG only"
                and not na(z.cisd)
                and (gt(close, z.cisd) if long else lt(close, z.cisd))
            )
            sl = z.ext - self._sl_buf if long else z.ext + self._sl_buf  # L819
            risk = abs(close - sl)  # L820
            if not ((via_ifvg or via_cisd) and gt(risk, 0.0)):  # L821
                continue
            bias_state = self._bias
            dol = bias_state.bsl if long else bias_state.ssl  # L822
            dol_time = bias_state.bsl_time if long else bias_state.ssl_time
            dol_distance = dol - close if long else close - dol  # L823
            dol_ok = (  # L824
                p.c_tgt == "Draw on liquidity"
                and not na(dol)
                and gt(dol_distance, 0.0)
                and ge(dol_distance, p.min_rr * risk)
            )
            tp = dol if dol_ok else close + z.dir * p.c_rr * risk  # L825
            z.used = True  # L827
            self._taken += 1  # L828
            return _Setup(
                z,
                via_ifvg=via_ifvg,
                via_cisd=via_cisd,
                sl=sl,
                risk=risk,
                dol=dol,
                dol_time=dol_time,
                dol_ok=dol_ok,
                tp=tp,
            )
        return None

    # ── signals ────────────────────────────────────────────────────────────────
    def _entry(self, bar: Bar, setup: _Setup, inv: Inversions) -> Signal:
        ctx = self.ctx
        p = self.params
        long = setup.dir > 0
        close = float(bar.close)
        z = setup.zone
        bias = self._bias
        metadata: dict[str, JsonValue] = {
            **self._common(TRIGGER_LONG if long else TRIGGER_SHORT),
            "pine_signal": "evC",
            "trade_tag": "C " + ("IFVG" if setup.via_ifvg else "CISD"),  # L826
            "via_ifvg": setup.via_ifvg,
            "via_cisd": setup.via_cisd,
            "c_trig": p.c_trig,
            "bias": bias.bias,
            "bias_tf": p.c_bias_tf,
            "bias_set_by_bar": _iso(bias.bias_time),
            "bias_events": [bias.bias_events[0], bias.bias_events[1]],
            "bias_from_bar": _iso(self._bias_last),
            "zone": {
                "dir": z.dir,
                "tf": p.c_fvg_tf,
                "top": z.top,
                "bottom": z.bot,
                "first_candle": z.start.isoformat(),
                "added": z.added.isoformat(),
                "added_bar_index": z.added_index,
                "tap_bar_index": z.tap_bar,
                "extreme": _num(z.ext),
                "extreme_bar_index": z.ext_bar,
                "cisd_level": _num(z.cisd),
            },
            "inverted_gap_bar_index": inv.bull_bar if long else inv.bear_bar,
            "inverted_gap_levels": list(inv.bull_levels if long else inv.bear_levels),
            "draw_on_liquidity": _num(setup.dol),
            "dol_pivot_time": _iso(setup.dol_time),
            "dol_ok": setup.dol_ok,
            "target_kind": "Draw on liquidity" if setup.dol_ok else "Fixed RR",
            "script_entry": close,
            "script_stop": setup.sl,
            "script_target": setup.tp,
            "risk_points": setup.risk,
            "planned_rr": abs(setup.tp - close) / setup.risk,
            "zones_live": len(self._zones.zones),
        }
        if p.after_window == "flat" and self._clock.last_bar(bar.close_time):
            # D6 variant: the trade would fill at the open the window-end flatten closes it
            return ctx.no_trade("ENTRY_ON_LAST_WINDOW_BAR", persist=True, metadata=metadata)
        problem = self._invalid_levels(long, close, setup.sl, setup.tp)
        if problem is not None:  # doc 13 D3: no trade with levels on the wrong side
            return ctx.no_trade(problem, persist=True, metadata=metadata)
        build = ctx.long if long else ctx.short
        via = "IFVG" if setup.via_ifvg else "CISD"
        side = "long" if long else "short"
        return build(
            stop_loss=setup.sl,
            take_profit=setup.tp,
            reason=f"Model C {side}: {via} after a tap of a {p.c_fvg_tf} FVG with the bias",
            metadata=metadata,
        )

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
            "position_entry": None if position is None else str(position.entry_price),
        }
        return self.ctx.flatten(metadata=metadata)

    def _common(self, trigger: str) -> dict[str, JsonValue]:
        return {
            "model": "C",
            "trigger": trigger,
            "window": self.params.c_win,
            "after_window": self.params.after_window,
            "c_taken": self._taken,
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


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _num(value: float) -> float | None:
    """A float for JSON metadata: na becomes null."""
    return None if na(value) or math.isinf(value) else float(value)
