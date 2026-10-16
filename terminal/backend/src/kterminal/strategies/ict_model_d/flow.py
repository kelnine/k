"""Model D's order-flow proxy and the script's own trade tracking.

A line-by-line port of these parts of
``terminal/pine/received/02_ict_sweep_order_flow_models.pine``:

* :class:`CandleFlow` — the default ``dDelta = "Candle estimate"`` (L634-643): the bar's
  volume ``nz(volume)`` split by where it closed in its range (``buyV = vol × (close −
  low) / (high − low)``, half each when the range is 0), ``barDelta = buyV − sellV``,
  ``avgVol = ta.sma(barVol, 20)`` (the current bar included), and the aggressive
  flags: ``barVol > 0``, ``barVol >= dVolMult × avgVol`` and ``|delta| >= dDeltaPct %``
  of the volume, buyers when the delta is positive. The ``Intrabar (lower TF)`` source
  (L629-633, seconds data) is not ported;
* :class:`ScriptTrade` — the script's ``Trade`` (L105-114) with ``openTrade``
  (L434-449), ``closeTrade`` (L417-432) and ``manage`` (L452-464): from the bar after
  the signal, a touch of the stop (checked first) or the target closes it. Model D
  looks for new setups only while it is closed (L881, L897, L904, L919), so the
  strategy keeps it exactly as the script does, independent of the lab's fills.

Comparisons are Pine's (``gt``/``ge``/``le``: 1e-10 tolerance, false with na).
"""

import math
from dataclasses import dataclass

from kterminal.indicators import Sma, ge, gt, le, nz

AVG_VOLUME_LENGTH = 20  # avgVol = ta.sma(barVol, 20) (L641)

NAN = math.nan


@dataclass(frozen=True, slots=True)
class Flow:
    """The order-flow proxy of one bar (L627-643)."""

    buy: float  # buyV
    sell: float  # sellV
    delta: float  # barDelta
    volume: float  # barVol
    avg_volume: float  # avgVol (na for the first 19 bars)
    aggr_buy: bool  # aggrBuy
    aggr_sell: bool  # aggrSell

    @property
    def delta_pct(self) -> float:
        """The delta as a percentage of the volume (na without volume)."""
        return 100.0 * self.delta / self.volume if self.volume > 0 else NAN


class CandleFlow:
    """``buyV``/``sellV``/``avgVol``/``aggrBuy``/``aggrSell`` with the candle estimate."""

    __slots__ = ("_avg", "_delta_pct", "_vol_mult")

    def __init__(self, vol_mult: float, delta_pct: float) -> None:
        self._vol_mult = vol_mult  # dVolMult
        self._delta_pct = delta_pct  # dDeltaPct
        self._avg = Sma(AVG_VOLUME_LENGTH)  # L641: every bar

    def update(self, high: float, low: float, close: float, volume: float) -> Flow:
        rng = high - low  # L635
        v0 = nz(volume)  # L636
        buy = v0 * (close - low) / rng if gt(rng, 0.0) else v0 / 2  # L637
        sell = v0 - buy  # L638
        delta = buy - sell  # L639
        bar_vol = buy + sell  # L640
        avg = self._avg.update(bar_vol)  # L641
        loud = gt(bar_vol, 0.0) and ge(bar_vol, self._vol_mult * avg)
        share = self._delta_pct / 100.0 * bar_vol
        return Flow(
            buy=buy,
            sell=sell,
            delta=delta,
            volume=bar_vol,
            avg_volume=avg,
            aggr_buy=loud and ge(delta, share),  # L642
            aggr_sell=loud and ge(-delta, share),  # L643
        )


class ScriptTrade:
    """The script's ``tD`` (L105-114, L417-464), unrounded, at the signal bar's close."""

    __slots__ = ("bar", "dir", "entry", "live", "result", "sl", "tp")

    def __init__(self) -> None:
        self.dir = 0
        self.entry = NAN
        self.sl = NAN
        self.tp = NAN
        self.bar = -1
        self.live = False
        self.result = 0  # closeTrade's res: +1 target, -1 stop, 0 neutral

    def open(self, direction: int, entry: float, sl: float, tp: float, index: int) -> None:
        """``openTrade`` (L434-441)."""
        self.dir, self.entry, self.sl, self.tp = direction, entry, sl, tp
        self.bar = index
        self.live = True
        self.result = 0

    def close(self, result: int) -> None:
        """``closeTrade`` (L417-419)."""
        if self.live:
            self.live = False
            self.result = result

    def manage(self, index: int, high: float, low: float) -> int:
        """``manage`` (L452-464): returns −1 / +1 when the stop / target closed it here."""
        if not (self.live and index > self.bar):
            return 0
        long = self.dir > 0
        hit_sl = le(low, self.sl) if long else ge(high, self.sl)  # L458
        hit_tp = ge(high, self.tp) if long else le(low, self.tp)  # L459
        if hit_sl:
            self.close(-1)
            return -1
        if hit_tp:
            self.close(1)
            return 1
        return 0
