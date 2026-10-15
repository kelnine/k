"""``scanCisd`` (L778-872) of script 1: the scanner's CISD model on one slot timeframe.

The scanner runs this function through ``request.security`` for each slot (5m, 15m,
1h, 4h by default). It is not the main-chart model: 3/3 pivots, sweeps of the latest
3/3 swing only (no PDH/PW/PM, no session levels, no window), and a swing-break
**bias**. Every call, in the script's order:

1. ``sPH/sPL = ta.pivothigh/low(3, 3)``, ``sAtr = ta.atr(14)`` (L779-781);
2. a confirmed pivot sets both the sweep level and the break level
   (``swH := bosH := sPH``, L789-794);
3. bias (L795-800): a close beyond the break level sets ``bias`` ±1 and clears that
   level — the low test runs second, so a bar that closes beyond both ends at −1;
4. sweeps (L801-806): ``high > swH`` stamps ``bslBar`` and clears ``swH`` (low mirrors)
   — only the scanner's own pivot sweep clears it;
5. runs and CISD (L808-840): as in the main model (``runs.CisdRuns``), with the body
   ``>= minBody × nz(sAtr)`` and the sweep within ``sweepLook`` bars of this slot; a
   close through the level consumes it whatever the filters say; the bullish check
   runs only when no bearish signal passed;
6. the slot's trade tracker (L843-870): the latest signal overwrites it; from the next
   bar on, the stop is checked first, then TP2, then TP1, and tracking goes on after
   TP1 until TP2 or the stop. The direction ``tDir`` of the latest signal is kept for
   ever (it is what the A+ grade compares).

``bar_index`` is the slot's own bar count (Pine evaluates the function on the slot's
bars). Comparisons are Pine's (``gt``/``ge``…: 1e-10 tolerance, false with na).
"""

import math
from dataclasses import dataclass
from datetime import datetime

from kterminal.indicators import Atr, PivotHigh, PivotLow, ge, gt, le, lt, na, nz
from kterminal.strategies.cisd_sweep import CisdRuns, Cross

NAN = math.nan
PIVOT = 3  # ta.pivothigh(high, 3, 3) (L779-780): fixed in the script
ATR_LENGTH = 14  # ta.atr(14) (L781)

# tSt (L842): 0 active, 1 TP1 hit, 2 TP2 hit, -1 stopped, 3 TP1 then stopped
STATUS = {0: "active", 1: "TP1 hit", 2: "TP2 hit", -1: "stopped", 3: "TP1 then stopped"}


@dataclass(frozen=True, slots=True)
class ScanSignal:
    """A signal of the slot on this bar (``sig``, ``sE``, ``sS``)."""

    direction: int  # +1 long, −1 short
    cross: Cross  # the run's level (sE), extreme (sS) and first bar
    sweep_bar: int  # bslBar / sslBar of the sweep that allowed it
    swept_level: float  # the 3/3 swing that sweep took (na when reqSweep is off and none)
    atr: float
    body: float
    min_body_points: float


class ScanCisd:
    """One slot of the MTF scanner: ``scanCisd`` evaluated on that slot's bars."""

    __slots__ = (
        "_atr",
        "_ph",
        "_pl",
        "bar_index",
        "bias",
        "bos_h",
        "bos_l",
        "bsl_bar",
        "bsl_level",
        "min_body",
        "req_sweep",
        "runs",
        "ssl_bar",
        "ssl_level",
        "sw_h",
        "sw_l",
        "sweep_look",
        "t_bar",
        "t_dir",
        "t_entry",
        "t_status",
        "t_stop",
        "t_time",
        "t_tp1",
        "t_tp2",
        "tp1_r",
        "tp2_r",
    )

    def __init__(
        self, *, min_body: float, req_sweep: bool, sweep_look: int, tp1_r: float, tp2_r: float
    ) -> None:
        self.min_body = min_body
        self.req_sweep = req_sweep
        self.sweep_look = sweep_look
        self.tp1_r = tp1_r
        self.tp2_r = tp2_r
        self._ph = PivotHigh(PIVOT, PIVOT)  # sPH (L779)
        self._pl = PivotLow(PIVOT, PIVOT)  # sPL (L780)
        self._atr = Atr(ATR_LENGTH)  # sAtr (L781)
        self.bar_index = -1
        self.sw_h = NAN  # swH: the sweep level (L782)
        self.sw_l = NAN
        self.bos_h = NAN  # bosH: the break level (L784)
        self.bos_l = NAN
        self.bias = 0  # L786
        self.bsl_bar = -100_000  # L787
        self.ssl_bar = -100_000
        self.bsl_level = NAN  # the swing the latest buy-side sweep took (metadata)
        self.ssl_level = NAN
        self.runs = CisdRuns()  # uOpen/uHigh, dOpn/dLow (L810-823)
        self.t_dir = 0  # the tracker (L843-850)
        self.t_entry = NAN
        self.t_stop = NAN
        self.t_tp1 = NAN
        self.t_tp2 = NAN
        self.t_bar: int | None = None
        self.t_time: datetime | None = None
        self.t_status = 0

    def update(
        self, open_time: datetime, open_: float, high: float, low: float, close: float
    ) -> ScanSignal | None:
        """One bar of the slot; the signal it makes, if any."""
        self.bar_index += 1
        bar_index = self.bar_index
        s_ph = self._ph.update(high)  # L779-781: every call
        s_pl = self._pl.update(low)
        atr = self._atr.update(high, low, close)
        if not na(s_ph):  # L789-794
            self.sw_h = self.bos_h = s_ph
        if not na(s_pl):
            self.sw_l = self.bos_l = s_pl
        if gt(close, self.bos_h):  # L795-797: not na(bosH) and close > bosH
            self.bias, self.bos_h = 1, NAN
        if lt(close, self.bos_l):  # L798-800
            self.bias, self.bos_l = -1, NAN
        if gt(high, self.sw_h):  # L801-803
            self.bsl_bar, self.bsl_level, self.sw_h = bar_index, self.sw_h, NAN
        if lt(low, self.sw_l):  # L804-806
            self.ssl_bar, self.ssl_level, self.sw_l = bar_index, self.sw_l, NAN

        self.runs.update(bar_index, open_, high, low, close)  # L808-823
        body = abs(close - open_)
        min_points = self.min_body * nz(atr)
        big = ge(body, min_points)  # L825
        signal: ScanSignal | None = None
        bear = self.runs.bear_cross(bar_index, close)  # L829, consumed (L834)
        if bear is not None and big and self._swept(self.bsl_bar):  # L830
            signal = ScanSignal(-1, bear, self.bsl_bar, self.bsl_level, atr, body, min_points)
        if signal is None:  # sig == 0 (L835)
            bull = self.runs.bull_cross(bar_index, close)  # consumed (L840)
            if bull is not None and big and self._swept(self.ssl_bar):  # L836
                signal = ScanSignal(1, bull, self.ssl_bar, self.ssl_level, atr, body, min_points)
        self._track(signal, open_time, high, low)
        return signal

    def _swept(self, sweep_bar: int) -> bool:
        return not self.req_sweep or self.bar_index - sweep_bar <= self.sweep_look

    def _track(
        self, signal: ScanSignal | None, open_time: datetime, high: float, low: float
    ) -> None:
        """L851-870: the slot's tracked trade and its status."""
        if signal is not None:
            entry, stop = signal.cross.level, signal.cross.extreme
            risk = abs(entry - stop)
            d = signal.direction
            self.t_dir, self.t_entry, self.t_stop = d, entry, stop
            self.t_tp1 = entry + d * risk * self.tp1_r if risk > 0 and self.tp1_r > 0 else NAN
            self.t_tp2 = entry + d * risk * self.tp2_r if risk > 0 and self.tp2_r > 0 else NAN
            self.t_bar, self.t_time, self.t_status = self.bar_index, open_time, 0
            return
        status = self.t_status
        if self.t_dir == 0 or not (status == 0 or (status == 1 and not na(self.t_tp2))):
            return
        short = self.t_dir < 0
        hit_stop = ge(high, self.t_stop) if short else le(low, self.t_stop)
        hit_tp1 = le(low, self.t_tp1) if short else ge(high, self.t_tp1)
        hit_tp2 = le(low, self.t_tp2) if short else ge(high, self.t_tp2)
        if hit_stop:
            self.t_status = 3 if status == 1 else -1
        elif hit_tp2:
            self.t_status = 2
        elif hit_tp1:
            self.t_status = 1

    @property
    def age(self) -> int | None:
        """Bars since the latest signal (``age``, L871), None before the first."""
        return None if self.t_bar is None else self.bar_index - self.t_bar

    @property
    def status(self) -> str:
        return STATUS[self.t_status]
