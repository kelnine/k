"""Script 5's order-block and fair-value-gap registries (L283-370, L594-623).

Each side keeps a Pine ``var box[]``: a new zone is pushed after shifting out the
oldest ones while the list is at its cap (``while array.size(a) >= max``), every
zone is deleted on a close beyond its far edge by more than 0.05 × the *current*
ATR, and the sniper's zone point is "the close inside any zone still listed",
bounds inclusive. Only the prices matter here; the drawings are not ported.

These are script 5's own rules (they differ from script 4's order blocks and
script 2's gaps, doc 13 §13.5): an order block is the **body** of the
``ob_len``/``ob_len`` pivot candle itself, and only when it is opposite-coloured;
a fair value gap is the strict three-bar gap ``high[2] < low`` (``low[2] > high``)
with no minimum size, and a partial fill does not delete it.
"""

from dataclasses import dataclass
from typing import Literal

from kterminal.indicators import ge, gt, le, lt

INVALIDATION_ATR = 0.05  # close beyond the far edge by 0.05 × ATR deletes a zone (L319-368)

ZoneKind = Literal["OB", "FVG"]


@dataclass(frozen=True, slots=True)
class Zone:
    """One box: its prices and the bar index of its left edge (the pivot candle of an
    order block, the first bar of a fair value gap)."""

    kind: ZoneKind
    top: float
    bottom: float
    bar_index: int

    def contains(self, close: float) -> bool:
        """``close >= box.get_bottom(b) and close <= box.get_top(b)`` (L598, L612)."""
        return ge(close, self.bottom) and le(close, self.top)


class ZoneList:
    """A FIFO-capped ``var box[]`` of one side (bullish or bearish)."""

    __slots__ = ("bullish", "cap", "zones")

    def __init__(self, cap: int, *, bullish: bool) -> None:
        if cap < 1:
            raise ValueError("cap must be at least 1")
        self.cap = cap
        self.bullish = bullish
        self.zones: list[Zone] = []

    def push(self, zone: Zone) -> None:
        """``while array.size(a) >= cap: array.shift(a)`` then ``array.push(a, zone)``."""
        while len(self.zones) >= self.cap:
            self.zones.pop(0)
        self.zones.append(zone)

    def invalidate(self, close: float, atr: float) -> list[Zone]:
        """Delete every zone the close has left on its far side: a bullish zone on
        ``close < bottom − 0.05 × atr``, a bearish one on ``close > top + 0.05 × atr``.
        With ``atr`` na the comparison is na and nothing is deleted, as in Pine.
        Returns the deleted zones."""
        keep: list[Zone] = []
        gone: list[Zone] = []
        for zone in self.zones:
            if self.bullish:
                beyond = lt(close, zone.bottom - atr * INVALIDATION_ATR)
            else:
                beyond = gt(close, zone.top + atr * INVALIDATION_ATR)
            (gone if beyond else keep).append(zone)
        self.zones = keep
        return gone

    def containing(self, close: float) -> list[Zone]:
        """The zones the close is inside (inclusive bounds)."""
        return [zone for zone in self.zones if zone.contains(close)]


def order_block(open_: float, close: float, *, bullish: bool, bar_index: int) -> Zone | None:
    """The order block of a confirmed pivot candle (L289-313), or None.

    A pivot **low** gives a bullish block only when its candle is bearish
    (``open > close``); a pivot **high** gives a bearish block only when its candle is
    bullish (``close > open``). The block is the candle's body."""
    opposite = gt(open_, close) if bullish else gt(close, open_)
    if not opposite:
        return None
    return Zone("OB", max(open_, close), min(open_, close), bar_index)


def fair_value_gap(
    high_2: float, low_2: float, high: float, low: float, *, bar_index: int
) -> tuple[Zone | None, Zone | None]:
    """The bullish and bearish gaps that end on this bar (L334-356): bullish when
    ``high[2] < low`` (box ``low`` … ``high[2]``), bearish when ``low[2] > high`` (box
    ``low[2]`` … ``high``). Strict, no minimum size; na before the third bar."""
    bull = Zone("FVG", low, high_2, bar_index - 2) if lt(high_2, low) else None
    bear = Zone("FVG", low_2, high, bar_index - 2) if gt(low_2, high) else None
    return bull, bear
