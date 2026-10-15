"""Script 2's shared sweep → MSS → displacement-FVG → resting-limit engine (models A and B).

A line-by-line port of ``terminal/pine/received/02_ict_sweep_order_flow_models.pine``:

* :class:`SharedSeries` — the script's shared 1m series (L155-170): the 20-bar SMA of
  the candle body, the displacement fair value gaps ``bullDisp``/``bearDisp`` and the
  ``mssLen`` swing pivots stored with their pivot bar (``pHp/pHb``, ``pLp/pLb``, cap 100,
  L726-737) and searched by ``f_pivotBefore`` (L184-194);
* :class:`SweepModel` — the ``SweepModel`` type (L133-148) and its ``run`` method
  (L466-595), its five-state machine: wait for the sweep (0), swept and wait for
  the MSS with a displacement FVG (1), limit armed and waiting for the fill (2), filled
  (3), idle until the next window start (4).

Everything is plain float64 maths with Pine's comparisons (``gt``/``ge``/``lt``/``le``:
1e-10 tolerance, false with na). Bar indices are the strategy's ``ctx.bar_index``
(Pine's ``bar_index``: only differences are used). The engine knows nothing about
orders: the strategy (``strategy.py``) turns its transitions into signals.
"""

import math
from collections import deque
from dataclasses import dataclass
from typing import Literal

from kterminal.indicators import PivotHigh, PivotLow, Sma, ge, gt, le, lt, na, nz

PIVOT_CAP = 100  # pHp/pLp keep the newest 100 pivots (L728-737)
AVG_BODY_LENGTH = 20  # avgBody = ta.sma(body, 20) (L159)

EntryMode = Literal["FVG edge", "FVG 50% (CE)"]
TargetMode = Literal["Opposite level", "Fixed RR"]

# SweepModel.state (L137)
WAIT_SWEEP = 0
WAIT_MSS = 1
ARMED = 2
IN_TRADE = 3
IDLE = 4

NAN = math.nan


@dataclass(frozen=True, slots=True)
class BarState:
    """One closed 1m bar with the script's shared series (L155-170)."""

    index: int  # bar_index
    open: float
    high: float
    low: float
    close: float
    bull_disp: bool  # bullDisp (L169)
    bear_disp: bool  # bearDisp (L170)
    bull_top: float  # bullTopNow = low (L165)
    bull_bot: float  # bullBotNow = high[2] (L166)
    bear_top: float  # bearTopNow = low[2] (L167)
    bear_bot: float  # bearBotNow = high (L168)
    body_1: float  # body[1]: the middle candle of the gap
    avg_body_1: float  # nz(avgBody[1])


class SharedSeries:
    """The shared 1m series (L155-173) and the stored MSS pivots (L726-737).

    ``update`` runs once per closed bar, before the models, like the script's global
    series and the top of its ``barstate.isconfirmed`` block.
    """

    __slots__ = (
        "_avg_body",
        "_bar1",
        "_bar2",
        "_disp_mult",
        "_min_gap",
        "_mss_len",
        "_pivot_high",
        "_pivot_low",
        "pivot_highs",
        "pivot_lows",
    )

    def __init__(self, mss_len: int, disp_mult: float, min_gap: float) -> None:
        self._mss_len = mss_len
        self._disp_mult = disp_mult
        self._min_gap = min_gap
        self._avg_body = Sma(AVG_BODY_LENGTH)
        self._pivot_high = PivotHigh(mss_len, mss_len)  # ph1 (L172)
        self._pivot_low = PivotLow(mss_len, mss_len)  # pl1 (L173)
        # (open, high, low, close, body, avgBody) of bar[1] and bar[2]
        self._bar1: tuple[float, float, float, float, float, float] | None = None
        self._bar2: tuple[float, float, float, float, float, float] | None = None
        # (price, pivot bar_index), oldest first (pHp/pHb, pLp/pLb)
        self.pivot_highs: deque[tuple[float, int]] = deque(maxlen=PIVOT_CAP)
        self.pivot_lows: deque[tuple[float, int]] = deque(maxlen=PIVOT_CAP)

    def update(self, index: int, o: float, h: float, low: float, c: float) -> BarState:
        body = abs(c - o)  # L158
        avg_body = self._avg_body.update(body)  # L159
        bar1, bar2 = self._bar1, self._bar2
        high2 = bar2[1] if bar2 is not None else NAN
        low2 = bar2[2] if bar2 is not None else NAN
        min_gap = self._min_gap
        bull_gap = gt(low, high2) and ge(low - high2, min_gap)  # L163
        bear_gap = lt(h, low2) and ge(low2 - h, min_gap)  # L164
        if bar1 is not None:
            o1, c1, body1, avg1 = bar1[0], bar1[3], bar1[4], nz(bar1[5])
        else:
            o1 = c1 = body1 = avg1 = NAN
        threshold = self._disp_mult * avg1
        bull_disp = bull_gap and gt(c1, o1) and ge(body1, threshold)  # L169
        bear_disp = bear_gap and lt(c1, o1) and ge(body1, threshold)  # L170

        # 1m swing points for the MSS, stored when confirmed at the pivot bar (L726-737)
        ph = self._pivot_high.update(h)
        pl = self._pivot_low.update(low)
        if not na(ph):
            self.pivot_highs.append((ph, index - self._mss_len))
        if not na(pl):
            self.pivot_lows.append((pl, index - self._mss_len))

        self._bar2, self._bar1 = bar1, (o, h, low, c, body, avg_body)
        return BarState(
            index=index,
            open=o,
            high=h,
            low=low,
            close=c,
            bull_disp=bull_disp,
            bear_disp=bear_disp,
            bull_top=low,
            bull_bot=high2,
            bear_top=low2,
            bear_bot=h,
            body_1=body1,
            avg_body_1=avg1,
        )

    def pivot_before(self, *, highs: bool, before: int) -> tuple[float, int | None]:
        """``f_pivotBefore`` (L184-194): the most recently stored pivot whose pivot bar is
        before bar ``before``, as ``(price, pivot bar_index)``; ``(nan, None)`` if none."""
        for price, bar in reversed(self.pivot_highs if highs else self.pivot_lows):
            if bar < before:
                return price, bar
        return NAN, None


@dataclass(frozen=True, slots=True)
class EngineConfig:
    """The ``run`` arguments and inputs that do not change from bar to bar."""

    need_back: bool  # needBack: model B needs a close back inside the range
    target_mode: TargetMode  # aTgt / bTgt
    rr: float  # aRR / bRR: fixed RR target and fallback
    min_rr: float  # minRR
    entry_mode: EntryMode  # entryMode
    sl_buf: float  # slBuf = slBufTicks × mintick


@dataclass(slots=True)
class Step:
    """What one ``run`` call did (the script's ``ev`` plus the transitions the port needs)."""

    started: bool = False  # startNow: levels reset (L470-483)
    window_cancelled: int | None = None  # the state < 3 dropped outside the window (L491-492)
    filled: bool = False  # the armed limit traded (L501-510), ev = ±2
    fill_price: float = NAN  # math.min(open, entry) / math.max(open, entry)
    stopped_on_fill: bool = False  # the stop traded on the fill bar (L508-510)
    missed: bool = False  # the target traded before the fill (L502, L511-512)
    swept: int = 0  # -1: range high swept, +1: range low swept (labels L519/L530)
    armed: int = 0  # +1 / -1: a long / short limit setup was armed on this bar (L559-594)
    ev: int = 0  # the script's return value: ±1 armed, ±2 filled, else 0


class SweepModel:
    """The script's ``SweepModel`` (L133-148) with ``run`` (L466-595).

    Fields keep the script's names in snake case; ``ext_bar``, ``mss_bar`` and
    ``fvg_bar`` are ``None`` where Pine holds ``na``. Extra fields (``mss_level``,
    ``fvg_body`` …, ``target_kind``) only describe the setup in signal metadata.
    """

    __slots__ = (
        "back_in",
        "dir",
        "entry",
        "ext",
        "ext_bar",
        "fvg_avg_body",
        "fvg_bar",
        "fvg_body",
        "fvg_bot",
        "fvg_top",
        "hi",
        "lo",
        "mss",
        "mss_bar",
        "mss_level",
        "mss_level_bar",
        "sl",
        "state",
        "tag",
        "target_kind",
        "tp",
    )

    def __init__(self, tag: str) -> None:
        self.tag = tag
        self.hi = NAN
        self.lo = NAN
        self.state = IDLE
        self.dir = 0
        self.ext = NAN
        self.ext_bar: int | None = None
        self.back_in = False
        self.mss = False
        self.mss_bar: int | None = None
        self.mss_level = NAN
        self.mss_level_bar: int | None = None
        self.fvg_top = NAN
        self.fvg_bot = NAN
        self.fvg_bar: int | None = None
        self.fvg_body = NAN
        self.fvg_avg_body = NAN
        self.entry = NAN
        self.sl = NAN
        self.tp = NAN
        self.target_kind = ""

    def run(
        self,
        bar: BarState,
        series: SharedSeries,
        config: EngineConfig,
        *,
        active: bool,
        start_now: bool,
        new_hi: float,
        new_lo: float,
    ) -> Step:
        """One closed bar of ``SweepModel.run`` (L468-595). ``active`` is the bar's
        window membership, ``start_now`` the window start, ``new_hi``/``new_lo`` the
        levels the window starts with (read only when ``start_now``)."""
        step = Step()
        if start_now:  # L470-483 (the open trade's neutral close is the strategy's job)
            step.started = True
            self.hi, self.lo = new_hi, new_lo
            self.dir = 0
            self.mss = False
            self.back_in = False
            self.fvg_top = NAN
            self.fvg_bot = NAN
            idle = na(new_hi) or na(new_lo) or le(new_hi, new_lo)
            self.state = IDLE if idle else WAIT_SWEEP
        # L489-490 (state 3 → 4 once the trade has closed) changes nothing the engine
        # reads: both states wait for the next window start, so state 3 is kept.
        if not active and self.state <= ARMED:  # L491-492
            step.window_cancelled = self.state
            self.state = IDLE
        if not (active and self.state <= ARMED):
            return step
        if self.state == ARMED:  # L496-512: wait for price to retrace into the FVG
            self._fill_or_miss(bar, step)
        if self.state <= WAIT_MSS:  # L516-538: sweep, or a new extreme beyond the sweep
            if (self.dir == -1 and gt(bar.high, self.ext)) or (
                self.dir != -1 and gt(bar.high, self.hi)
            ):
                if self.dir != -1:
                    step.swept = -1
                self._new_extreme(-1, bar.high, bar.index)
            if (self.dir == 1 and lt(bar.low, self.ext)) or (
                self.dir != 1 and lt(bar.low, self.lo)
            ):
                if self.dir != 1:
                    step.swept = 1
                self._new_extreme(1, bar.low, bar.index)
        if self.state == WAIT_MSS:  # L540-594: MSS with a displacement FVG, then arm
            if self.dir == 1:
                self._long_leg(bar, series, config, step)
            else:
                self._short_leg(bar, series, config, step)
        return step

    # ── the pieces of run ──────────────────────────────────────────────────────
    def _fill_or_miss(self, bar: BarState, step: Step) -> None:
        long = self.dir > 0
        filled = le(bar.low, self.entry) if long else ge(bar.high, self.entry)  # L501
        missed = ge(bar.high, self.tp) if long else le(bar.low, self.tp)  # L502
        if filled:  # L503-510
            step.filled = True
            step.ev = 2 * self.dir
            step.fill_price = min(bar.open, self.entry) if long else max(bar.open, self.entry)
            step.stopped_on_fill = le(bar.low, self.sl) if long else ge(bar.high, self.sl)
            self.state = IN_TRADE
        elif missed:  # L511-512
            step.missed = True
            self.state = IDLE

    def _new_extreme(self, direction: int, price: float, index: int) -> None:
        """L520-527 / L531-538: a sweep, a flip or a new extreme restarts the MSS search."""
        self.dir = direction
        self.ext = price
        self.ext_bar = index
        self.mss = False
        self.back_in = False
        self.fvg_top = NAN
        self.fvg_bot = NAN
        self.state = WAIT_MSS

    def _fvg_allowed(self, bar: BarState) -> bool:
        """The gap's first candle is at or after the sweep extreme, and its middle candle
        is at most 3 bars after the MSS (L544, L571)."""
        ext_bar = self.ext_bar if self.ext_bar is not None else bar.index
        if bar.index - 2 < ext_bar:
            return False
        return not self.mss or (self.mss_bar is not None and bar.index - 1 <= self.mss_bar + 3)

    def _ready(self, config: EngineConfig) -> bool:
        """L559 / L586: MSS, a live FVG formed by mssBar + 3, and (B) a close back inside."""
        return (
            self.mss
            and not na(self.fvg_top)
            and self.fvg_bar is not None
            and self.mss_bar is not None
            and self.fvg_bar <= self.mss_bar + 3
            and (self.back_in or not config.need_back)
        )

    def _long_leg(
        self, bar: BarState, series: SharedSeries, config: EngineConfig, step: Step
    ) -> None:
        if gt(bar.close, self.lo):  # L542-543
            self.back_in = True
        if bar.bull_disp and self._fvg_allowed(bar):  # L544-547
            self.fvg_top = bar.bull_top
            self.fvg_bot = bar.bull_bot
            self.fvg_bar = bar.index - 1
            self.fvg_body, self.fvg_avg_body = bar.body_1, bar.avg_body_1
        if not na(self.fvg_bot) and lt(bar.close, self.fvg_bot):  # L548-550
            self.fvg_top = NAN
            self.fvg_bot = NAN
        if not self.mss and self.ext_bar is not None:  # L551-558
            level, level_bar = series.pivot_before(highs=True, before=self.ext_bar)
            if not na(level) and gt(bar.close, level):
                self.mss = True
                self.mss_bar = bar.index
                self.mss_level, self.mss_level_bar = level, level_bar
        if self._ready(config):  # L559-567
            edge = config.entry_mode == "FVG edge"
            self.entry = self.fvg_top if edge else (self.fvg_top + self.fvg_bot) / 2
            self.sl = self.ext - config.sl_buf
            target = self.hi if config.target_mode == "Opposite level" else NAN
            risk = self.entry - self.sl
            distance = target - self.entry
            if not na(target) and gt(distance, 0.0) and ge(distance, config.min_rr * risk):
                self.tp, self.target_kind = target, "Opposite level"
            else:
                self.tp, self.target_kind = self.entry + config.rr * risk, "Fixed RR"
            self.state = ARMED
            step.armed = step.ev = 1

    def _short_leg(
        self, bar: BarState, series: SharedSeries, config: EngineConfig, step: Step
    ) -> None:
        if lt(bar.close, self.hi):  # L569-570
            self.back_in = True
        if bar.bear_disp and self._fvg_allowed(bar):  # L571-574
            self.fvg_top = bar.bear_top
            self.fvg_bot = bar.bear_bot
            self.fvg_bar = bar.index - 1
            self.fvg_body, self.fvg_avg_body = bar.body_1, bar.avg_body_1
        if not na(self.fvg_top) and gt(bar.close, self.fvg_top):  # L575-577
            self.fvg_top = NAN
            self.fvg_bot = NAN
        if not self.mss and self.ext_bar is not None:  # L578-585
            level, level_bar = series.pivot_before(highs=False, before=self.ext_bar)
            if not na(level) and lt(bar.close, level):
                self.mss = True
                self.mss_bar = bar.index
                self.mss_level, self.mss_level_bar = level, level_bar
        if self._ready(config):  # L586-594
            edge = config.entry_mode == "FVG edge"
            self.entry = self.fvg_bot if edge else (self.fvg_top + self.fvg_bot) / 2
            self.sl = self.ext + config.sl_buf
            target = self.lo if config.target_mode == "Opposite level" else NAN
            risk = self.sl - self.entry
            distance = self.entry - target
            if not na(target) and gt(distance, 0.0) and ge(distance, config.min_rr * risk):
                self.tp, self.target_kind = target, "Opposite level"
            else:
                self.tp, self.target_kind = self.entry - config.rr * risk, "Fixed RR"
            self.state = ARMED
            step.armed = step.ev = -1
