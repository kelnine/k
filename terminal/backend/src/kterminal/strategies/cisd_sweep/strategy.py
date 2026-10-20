"""S6 · CISD after a liquidity sweep — the main-chart model of script 1 (doc 13).

Source: ``terminal/pine/received/01_breakout_targets_ict_cisd.pine`` ("Breakout Targets
+ ICT Levels + CISD"), spec ``terminal/pine/specs/01_breakout_targets_ict_cisd.md``;
line numbers below refer to the received file. Only the CISD model and what feeds it
are ported; the range breakout, trendlines, zones, opens and the scanner table are
display or alert only (doc 13 D12; the scanner's own CISD model is ``cisd_scanner``).

Every closed bar, in the script's order:

1. ``ph/pl = ta.pivothigh/low(high/low, pvL, pvR)``, ``atr = ta.atr(14)`` (L192-194).
2. Session trackers (L477-537): Asia 20:00-00:00, London 02:00-05:00 and NY AM
   09:30-12:00 New York (``tz``) high/low, reset on each session's first bar.
3. Liquidity sweeps (L585-624): the latest 5/5 pivot high is kept (``lastPH``); a
   buy-side sweep is ``high > lastPH`` or a trade-through (``high > L and high[1] <=
   L``) of PDH, PWH, PMH (``ctx.periods``, the ``request.security(…, "D"/"W"/"M",
   high[1], lookahead_on)`` of L400-402) or of the last completed Asia / London / NY
   AM high, the session levels only while outside their session and only on charts of
   60 minutes or less (``showSess``); it stamps ``lastBslBar`` and clears ``lastPH``.
   Sell-side mirrors it.
4. CISD (L629-683): the latest up-close / down-close runs (``runs.CisdRuns``); a close
   below the up-close run's open is a bearish CISD when the body is at least
   ``minBody × nz(atr)`` and a buy-side sweep happened within ``sweepLook`` bars — the
   level is consumed whatever the filters say; the bullish check runs only when no
   bearish CISD passed; the signal window is applied last (L674-683).
5. The trade (L721-736): entry = the CISD level, stop = the run's extreme, TP1/TP2 =
   entry ± 1R/2R, turned into orders by :class:`~.orders.CisdTradeStrategy` (doc 13
   D7/D4/D3); the script stops tracking a trade 4,500 bars after its signal (L764).
"""

from datetime import datetime
from typing import ClassVar, Literal

from pydantic import Field, JsonValue

from kterminal.domain.market import Bar
from kterminal.indicators import Atr, PivotHigh, PivotLow, ge, gt, le, lt, na, nz
from kterminal.strategies.cisd_sweep.levels import SessionClock, SessionRange
from kterminal.strategies.cisd_sweep.orders import CisdParams, CisdSetup, CisdTradeStrategy
from kterminal.strategies.cisd_sweep.runs import NAN, CisdRuns, Cross
from kterminal.strategy_engine import (
    PeriodBar,
    SessionString,
    StrategyMeta,
    TimeZoneName,
    register_strategy,
)

ATR_LENGTH = 14  # ta.atr(14) (L194)
MAX_BACK = 4_500  # the tracker drops a trade after this many bars (L27, L764)
SESSION_MAX_SECONDS = 3_600  # showSess: intraday charts of 60 minutes or less (L388)

SignalWindow = Literal[
    "Any time", "NY AM", "NY AM + NY PM", "London + NY AM", "London + NY AM + NY PM"
]

TRIGGER_BEAR = "Bearish CISD"  # the script's alertcondition titles (L998-999)
TRIGGER_BULL = "Bullish CISD"


class CisdSweepParams(CisdParams):
    """The script's inputs that change CISD signals (Pine defaults, Pine names)."""

    pv_l: int = Field(5, ge=1, le=100, description="pvL: pivot left bars (L47)")
    pv_r: int = Field(5, ge=1, le=100, description="pvR: pivot right bars (L48)")
    tz: TimeZoneName = Field("America/New_York", description="tz: session time zone (L58)")
    asia_sess: SessionString = Field("2000-0000", description="asiaSess (L67)")
    lon_sess: SessionString = Field("0200-0500", description="lonSess (L69)")
    ny_am_sess: SessionString = Field("0930-1200", description="nyAmSess (L71)")
    ny_pm_sess: SessionString = Field(
        "1330-1600", description="nyPmSess (L73): only in the signal-window options"
    )
    sig_window: SignalWindow = Field("Any time", description="sigWindow: signal only during (L86)")


class _Sweep:
    """The latest sweep of one side: its bar and the levels taken on it."""

    __slots__ = ("bar_index", "levels", "time")

    def __init__(self) -> None:
        self.bar_index = -100_000  # lastBslBar / lastSslBar (L617-618)
        self.time: datetime | None = None
        self.levels: list[dict[str, JsonValue]] = []

    def stamp(self, bar_index: int, time: datetime, levels: list[dict[str, JsonValue]]) -> None:
        self.bar_index, self.time, self.levels = bar_index, time, levels

    def describe(self, bar_index: int) -> dict[str, JsonValue]:
        return {
            "bar_index": self.bar_index,
            "bars_ago": bar_index - self.bar_index,
            "time": None if self.time is None else self.time.isoformat(),
            "levels": list(self.levels),
        }


@register_strategy
class CisdSweep(CisdTradeStrategy[CisdSweepParams]):
    meta = StrategyMeta(
        id="cisd_sweep",
        name="CISD after a liquidity sweep · script 1 main model",
        version="1.0.0",
        description=(
            "Port of 'Breakout Targets + ICT Levels + CISD': a close through the open of the "
            "latest opposing run (body >= 0.3 ATR) within 12 bars of a sweep of PDH/PDL, "
            "PWH/PWL, PMH/PML, the last Asia/London/NY AM high/low or the latest 5/5 pivot; "
            "limit at the CISD level, stop at the run extreme, TP1 1R / TP2 2R (doc 13 S6)."
        ),
        # ATR(14), the 5/5 pivots and the session ranges (the last NY AM can be a weekend
        # old). The previous day/week/month need more: forward warm-up adds
        # period_warmup_bars for each level this module asks ctx.periods for.
        warmup_bars=600,
        on_opposite_signal="reverse",  # D4: market mode reverses on an opposite CISD
        skip_entry_beyond_levels=True,  # D3 for market mode (limits are not affected)
        tags=("pine-port", "script-1", "s6", "cisd"),
    )
    Params = CisdSweepParams
    MAX_TRACK_BARS: ClassVar[int | None] = MAX_BACK

    def _start_model(self) -> None:
        p = self.params
        self._ph = PivotHigh(p.pv_l, p.pv_r)  # L192
        self._pl = PivotLow(p.pv_l, p.pv_r)  # L193
        self._atr = Atr(ATR_LENGTH)  # L194
        self._asia = SessionClock(p.asia_sess, p.tz)  # inAsia (L477)
        self._lon = SessionClock(p.lon_sess, p.tz)  # inLon (L478)
        self._ny_am = SessionClock(p.ny_am_sess, p.tz)  # inNYAM (L496)
        self._ny_pm = SessionClock(p.ny_pm_sess, p.tz)  # inNYPM (L497)
        self.asia = SessionRange()  # asiaH / asiaL
        self.london = SessionRange()  # lonH / lonL
        self.ny_am = SessionRange()  # nyAmH / nyAmL
        self.last_ph = NAN  # lastPH (L588)
        self.last_pl = NAN  # lastPL (L589)
        self.last_ph_bar: int | None = None  # its pivot bar (bar_index - pvR)
        self.last_pl_bar: int | None = None
        self.bsl = _Sweep()  # buy-side: lastBslBar
        self.ssl = _Sweep()  # sell-side: lastSslBar
        self.runs = CisdRuns()
        self._previous_high = NAN  # high[1]
        self._previous_low = NAN  # low[1]
        self._show_sess = self.ctx.timeframe.seconds <= SESSION_MAX_SECONDS

    def _evaluate(self, bar: Bar) -> CisdSetup | None:
        p = self.params
        ctx = self.ctx
        bar_index = ctx.bar_index
        open_, high, low, close = float(bar.open), float(bar.high), float(bar.low), float(bar.close)
        ph = self._ph.update(high)  # L192-194: every bar
        pl = self._pl.update(low)
        atr = self._atr.update(high, low, close)

        for clock in (self._asia, self._lon, self._ny_am, self._ny_pm):  # L477-523
            clock.update(bar.open_time)
        self.asia.update(self._asia, bar.open_time, high, low)  # L486-494
        self.ny_am.update(self._ny_am, bar.open_time, high, low)  # L505-513
        self.london.update(self._lon, bar.open_time, high, low)  # L529-537

        # ── liquidity sweeps (L585-624) ──
        if not na(ph):  # L590-593
            self.last_ph, self.last_ph_bar = ph, bar_index - p.pv_r
        if not na(pl):
            self.last_pl, self.last_pl_bar = pl, bar_index - p.pv_r
        levels = self._levels()
        previous_high, previous_low = self._previous_high, self._previous_low
        self._previous_high, self._previous_low = high, low
        # tookHigh(l) = not na(l) and high > l and high[1] <= l (L585-586)
        taken_high: list[dict[str, JsonValue]] = [
            {"level": name, "price": price}
            for name, price in levels["high"]
            if gt(high, price) and le(previous_high, price)
        ]
        taken_low: list[dict[str, JsonValue]] = [
            {"level": name, "price": price}
            for name, price in levels["low"]
            if lt(low, price) and ge(previous_low, price)
        ]
        if gt(high, self.last_ph):  # not na(lastPH) and high > lastPH (L614)
            taken_high.insert(0, {"level": "pivot high", "price": self.last_ph})
        if lt(low, self.last_pl):  # L615
            taken_low.insert(0, {"level": "pivot low", "price": self.last_pl})
        if taken_high:  # bslSwept (L619-621)
            self.bsl.stamp(bar_index, bar.open_time, taken_high)
            self.last_ph, self.last_ph_bar = NAN, None
        if taken_low:  # sslSwept (L622-624)
            self.ssl.stamp(bar_index, bar.open_time, taken_low)
            self.last_pl, self.last_pl_bar = NAN, None

        # ── CISD (L629-683) ──
        self.runs.update(bar_index, open_, high, low, close)
        body = abs(close - open_)
        min_points = p.min_body * nz(atr)
        big_body = ge(body, min_points)  # bigBody (L631)
        bear = self.runs.bear_cross(bar_index, close)  # L660, consumed (L665)
        bear_cisd = bear is not None and big_body and self._swept(self.bsl)  # L661
        bull: Cross | None = None
        bull_cisd = False
        if not bear_cisd:  # L667
            bull = self.runs.bull_cross(bar_index, close)  # consumed (L672)
            bull_cisd = bull is not None and big_body and self._swept(self.ssl)  # L668
        if not (bear_cisd or bull_cisd) or not self._in_window():  # L674-683
            return None
        cross = bear if bear_cisd else bull
        if cross is None:  # pragma: no cover - set whenever a CISD passed
            return None
        long = bull_cisd
        live_levels: dict[str, JsonValue] = {
            name: _num(price) for name, price in levels["high"] + levels["low"]
        }
        live_levels["pivot high"] = _num(self.last_ph)
        live_levels["pivot low"] = _num(self.last_pl)
        metadata: dict[str, JsonValue] = {
            "model": "main",
            "cisd_level": cross.level,
            "run_extreme": cross.extreme,
            "run_start_bar_index": cross.start,
            "run_bars": bar_index - cross.start + 1,
            "body": body,
            "atr": None if na(atr) else atr,
            "min_body_points": min_points,
            "sweep": (self.ssl if long else self.bsl).describe(bar_index),
            "sig_window": p.sig_window,
            "levels": live_levels,
        }
        return CisdSetup(
            long=long,
            entry=cross.level,
            stop=cross.extreme,
            trigger=TRIGGER_BULL if long else TRIGGER_BEAR,
            pine_signal="bullCisd" if long else "bearCisd",
            metadata=metadata,
        )

    def _levels(self) -> dict[str, list[tuple[str, float]]]:
        """The level sweep sources of L602-613 on this bar (na where not available)."""
        periods = self.ctx.periods
        pd = periods.previous("D")  # [pdh, pdl] (L400)
        pw = periods.previous("W")  # [pwh, pwl] (L401)
        pm = periods.previous("M")  # [pmh, pml] (L402)
        live = self._show_sess
        s_ah, s_al = self.asia.levels(self._asia, live)  # L595-596
        s_lh, s_ll = self.london.levels(self._lon, live)  # L597-598
        s_nh, s_nl = self.ny_am.levels(self._ny_am, live)  # L599-600
        return {
            "high": [
                ("PDH", _high(pd)),
                ("PWH", _high(pw)),
                ("PMH", _high(pm)),
                ("Asia high", s_ah),
                ("LNDN high", s_lh),
                ("NY AM high", s_nh),
            ],
            "low": [
                ("PDL", _low(pd)),
                ("PWL", _low(pw)),
                ("PML", _low(pm)),
                ("Asia low", s_al),
                ("LNDN low", s_ll),
                ("NY AM low", s_nl),
            ],
        }

    def _swept(self, sweep: _Sweep) -> bool:
        """``not reqSweep or bar_index - lastBslBar <= sweepLook`` (L661, L668)."""
        p = self.params
        return not p.req_sweep or self.ctx.bar_index - sweep.bar_index <= p.sweep_look

    def _in_window(self) -> bool:
        """``inWindow`` (L674-680): ignored on charts above 60 minutes."""
        if not self._show_sess:
            return True
        window = self.params.sig_window
        ny_am, ny_pm, london = self._ny_am.inside, self._ny_pm.inside, self._lon.inside
        if window == "NY AM":
            return ny_am
        if window == "NY AM + NY PM":
            return ny_am or ny_pm
        if window == "London + NY AM":
            return london or ny_am
        if window == "London + NY AM + NY PM":
            return london or ny_am or ny_pm
        return True


def _high(period: PeriodBar | None) -> float:
    return NAN if period is None else float(period.high)


def _low(period: PeriodBar | None) -> float:
    return NAN if period is None else float(period.low)


def _num(value: float) -> float | None:
    """A float for JSON metadata: na becomes null."""
    return None if na(value) else float(value)
