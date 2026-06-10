"""Momentum breakouts for Bitcoin on the 1-hour.

Crypto trends harder than indices, so instead of fading extension we buy
strength: a close above the prior 20-bar high (Donchian breakout) with the
breakout bar showing real range expansion (bar range vs ATR). Exits on a
close back through the channel midline; the hard stop covers the failure
case.
"""

from __future__ import annotations

import pandas as pd

from ..indicators import atr, donchian
from .base import FLAT, LONG, SHORT, Signal, Strategy


class MomentumBreakout(Strategy):
    def __init__(
        self,
        channel: int = 20,
        atr_period: int = 14,
        expansion_mult: float = 1.0,
        allow_short: bool = True,
    ):
        self.channel = channel
        self.atr_period = atr_period
        self.expansion_mult = expansion_mult
        self.allow_short = allow_short
        self.warmup = max(channel, atr_period) + 5

    def signal(self, df: pd.DataFrame, current_direction: int = FLAT) -> Signal:
        if len(df) < self.warmup:
            return Signal(FLAT, "warmup")

        upper, lower = donchian(df, self.channel)
        up, lo = upper.iloc[-1], lower.iloc[-1]
        if pd.isna(up) or pd.isna(lo):
            return Signal(FLAT, "warmup")
        mid = (up + lo) / 2
        close = df["close"].iloc[-1]
        bar_range = df["high"].iloc[-1] - df["low"].iloc[-1]
        avg_range = atr(df, self.atr_period).iloc[-1]

        if current_direction == LONG:
            if close < mid:
                return Signal(FLAT, f"lost momentum (close {close:.0f} < mid {mid:.0f})")
            return Signal(LONG, "riding breakout")
        if current_direction == SHORT:
            if close > mid:
                return Signal(FLAT, f"lost momentum (close {close:.0f} > mid {mid:.0f})")
            return Signal(SHORT, "riding breakdown")

        expanding = bar_range >= self.expansion_mult * avg_range
        if close > up and expanding:
            return Signal(LONG, f"breakout above {self.channel}-bar high {up:.0f}")
        if self.allow_short and close < lo and expanding:
            return Signal(SHORT, f"breakdown below {self.channel}-bar low {lo:.0f}")
        return Signal(FLAT, "inside channel")
