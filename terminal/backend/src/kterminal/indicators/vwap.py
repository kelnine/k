"""Anchored VWAP with standard-deviation bands: ``ta.vwap(source, anchor, stdev_mult)``."""

import math
from typing import NamedTuple

from kterminal.indicators.pine import div, na

__all__ = ["Vwap", "VwapValue"]


class VwapValue(NamedTuple):
    vwap: float
    stdev: float  # volume-weighted population standard deviation of the source

    def upper(self, mult: float) -> float:
        """Pine's upper band for ``stdev_mult = mult``: ``vwap + mult * stdev``."""
        return self.vwap + mult * self.stdev

    def lower(self, mult: float) -> float:
        """Pine's lower band for ``stdev_mult = mult``: ``vwap - mult * stdev``."""
        return self.vwap - mult * self.stdev


class Vwap:
    """Pine ``ta.vwap(source, anchor, stdev_mult)``, one object for any number of band multipliers.

    On a bar where ``anchor`` is true the sums restart with that bar; on
    other bars they accumulate::

        vwap     = Σ(source × volume) / Σ volume
        variance = max(0, Σ(source² × volume) / Σ volume − vwap²)     (population)
        stdev    = sqrt(variance),  bands = vwap ± mult × stdev

    * The caller supplies the anchor. For the default ``ta.vwap(hlc3)``
      (``timeframe.change("1D")``) pass ``True`` on the first bar of each
      trading day of the instrument — the catalog's trading-day rule (17:00
      New York for CFDs/FX/metals, the CME session for futures, 00:00 UTC for
      crypto) — not on UTC midnight.
    * Until the first anchor the VWAP is na (the history before the first
      period start is incomplete). Pass ``anchor=True`` on the very first bar
      to start immediately instead.
    * Zero total volume gives na (Pine's ``0 / 0``), so a feed without volume
      has no VWAP; a na volume makes the VWAP na until the next anchor (Pine
      arithmetic with na). A na ``source`` returns na and changes nothing —
      not even an anchor on that bar.
    """

    __slots__ = ("_started", "_sum_source_volume", "_sum_square_volume", "_sum_volume", "value")

    def __init__(self) -> None:
        self._started = False
        self._sum_volume = 0.0
        self._sum_source_volume = 0.0
        self._sum_square_volume = 0.0
        self.value = VwapValue(math.nan, math.nan)

    def update(self, source: float, volume: float, anchor: bool) -> VwapValue:
        self.value = VwapValue(math.nan, math.nan)
        if na(source):
            return self.value
        if anchor:
            self._started = True
            self._sum_volume = volume
            self._sum_source_volume = source * volume
            self._sum_square_volume = source * source * volume
        elif self._started:
            self._sum_volume += volume
            self._sum_source_volume += source * volume
            self._sum_square_volume += source * source * volume
        else:
            return self.value
        vwap = div(self._sum_source_volume, self._sum_volume)
        if na(vwap):
            return self.value
        variance = max(0.0, self._sum_square_volume / self._sum_volume - vwap * vwap)
        self.value = VwapValue(vwap, math.sqrt(variance) if math.isfinite(variance) else math.nan)
        return self.value
