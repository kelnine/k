"""Model D's overnight session profile: value area high/low, POC, overnight high/low.

A line-by-line port of ``f_valueArea`` (L307-339) and the overnight block of
``terminal/pine/received/02_ict_sweep_order_flow_models.pine`` (L835-854):

* on the first bar inside ``dOnSess`` (18:00-09:30 New York, ``inON and not inON[1]``)
  the stored bars are cleared and the session high/low restart from the bar; every bar
  inside stores its high, low and ``nz(volume)`` and extends the high/low;
* on the first bar after the session (``inON[1]``, normally the 09:30 bar) the profile
  is computed from those bars and becomes the key levels VAH, VAL, POC and the
  overnight high/low, kept until the next session ends.

``value_area`` is the script's own algorithm, copied exactly: ``rows`` equal rows over
the session's low-high range; each bar's volume spread evenly over the rows from the
one holding its low to the one holding its high (``floor((price − lo) / step)``,
clamped to the range); POC = the **first** row with the most volume; from the POC the
area grows one row at a time towards the larger neighbour — **ties go up** — until it
holds ``vaPct`` % of the volume or covers every row; VAH is the top edge of its highest
row, VAL the bottom edge of its lowest, POC the middle of its row.
"""

import math
from dataclasses import dataclass

from kterminal.indicators import ge, gt, lt

NAN = math.nan


@dataclass(frozen=True, slots=True)
class ValueArea:
    """``[vah, val, poc]`` of ``f_valueArea`` (na when the range or the volume is 0)."""

    vah: float
    val: float
    poc: float


def value_area(
    highs: list[float],
    lows: list[float],
    volumes: list[float],
    lo: float,
    hi: float,
    rows: int,
    va_pct: float,
) -> ValueArea:
    """``f_valueArea(hs, ls, vs, lo, hi, rows, vaPct)`` (L307-339)."""
    n = len(highs)
    if n == 0 or not gt(hi, lo):  # L312
        return ValueArea(NAN, NAN, NAN)
    step = (hi - lo) / rows
    bins = [0.0] * rows
    for i in range(n):  # L315-320
        r0 = max(0, min(rows - 1, math.floor((lows[i] - lo) / step)))
        r1 = max(0, min(rows - 1, math.floor((highs[i] - lo) / step)))
        share = volumes[i] / (r1 - r0 + 1)
        for r in range(r0, r1 + 1):
            bins[r] += share
    total = 0.0
    for v in bins:  # array.sum(), in order
        total += v
    if not gt(total, 0.0):  # L322
        return ValueArea(NAN, NAN, NAN)
    poc_index = bins.index(max(bins))  # bins.indexof(bins.max()): the first maximum
    up = dn = poc_index
    acc = bins[poc_index]
    target = total * va_pct / 100.0
    while lt(acc, target) and (up < rows - 1 or dn > 0):  # L327-335
        v_up = bins[up + 1] if up < rows - 1 else -1.0
        v_dn = bins[dn - 1] if dn > 0 else -1.0
        if ge(v_up, v_dn):
            up += 1
            acc += v_up
        else:
            dn -= 1
            acc += v_dn
    return ValueArea(
        vah=lo + (up + 1) * step,  # L336
        val=lo + dn * step,  # L337
        poc=lo + (poc_index + 0.5) * step,  # L338
    )


class OvernightProfile:
    """``onHs/onLs/onVs``, ``onHi/onLo`` and the levels computed from them (L689-698,
    L835-854)."""

    __slots__ = (
        "_highs",
        "_lows",
        "_rows",
        "_va_pct",
        "_volumes",
        "bars",
        "high",
        "levels_high",
        "levels_low",
        "low",
        "poc",
        "session_bars",
        "vah",
        "val",
    )

    def __init__(self, rows: int, va_pct: float) -> None:
        self._rows = rows
        self._va_pct = va_pct
        self._highs: list[float] = []
        self._lows: list[float] = []
        self._volumes: list[float] = []
        self.high = NAN  # onHi: the running session high
        self.low = NAN  # onLo
        self.vah = NAN  # onVAH
        self.val = NAN  # onVAL
        self.poc = NAN  # onPOC
        self.levels_high = NAN  # lvONH: the last completed session's high
        self.levels_low = NAN  # lvONL
        self.bars = 0  # bars in the running session
        self.session_bars = 0  # bars behind the current levels

    def update(
        self, high: float, low: float, volume: float, *, inside: bool, started: bool, ended: bool
    ) -> bool:
        """One bar: ``inside`` = ``inON``, ``started`` = ``inON and not inON[1]``, ``ended``
        = ``not inON and inON[1]``. Returns True when the levels were recomputed."""
        if inside:  # L835-847
            if started:
                self._highs.clear()
                self._lows.clear()
                self._volumes.clear()
                self.high, self.low, self.bars = high, low, 0
            else:
                self.high = _pine_max(self.high, high)
                self.low = _pine_min(self.low, low)
            self._highs.append(high)
            self._lows.append(low)
            self._volumes.append(volume)
            self.bars += 1
            return False
        if ended:  # L848-854
            area = value_area(
                self._highs,
                self._lows,
                self._volumes,
                self.low,
                self.high,
                self._rows,
                self._va_pct,
            )
            self.vah, self.val, self.poc = area.vah, area.val, area.poc
            self.levels_high, self.levels_low = self.high, self.low
            self.session_bars = self.bars
            return True
        return False


def _pine_max(a: float, b: float) -> float:
    """``math.max``: na if either argument is na."""
    return NAN if math.isnan(a) or math.isnan(b) else max(a, b)


def _pine_min(a: float, b: float) -> float:
    """``math.min``: na if either argument is na."""
    return NAN if math.isnan(a) or math.isnan(b) else min(a, b)
