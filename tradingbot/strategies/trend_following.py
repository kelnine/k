"""Slow trend following for gold and oil on the 4-hour.

Commodities move in cleaner, longer waves; the edge is staying with the
wave, not trading every wiggle. Classic dual-EMA system:

- long while the fast EMA is above the slow EMA and price confirms,
  short in the mirror case
- a minimum EMA separation (in ATR units) filters out the chop where the
  averages braid around each other
"""

from __future__ import annotations

import pandas as pd

from ..indicators import atr, ema
from .base import FLAT, LONG, SHORT, Signal, Strategy


class TrendFollowing(Strategy):
    def __init__(
        self,
        fast: int = 20,
        slow: int = 50,
        atr_period: int = 14,
        min_separation_atr: float = 0.25,
    ):
        self.fast = fast
        self.slow = slow
        self.atr_period = atr_period
        self.min_separation_atr = min_separation_atr
        self.warmup = slow + 10

    def signal(self, df: pd.DataFrame, current_direction: int = FLAT) -> Signal:
        if len(df) < self.warmup:
            return Signal(FLAT, "warmup")

        f = ema(df["close"], self.fast).iloc[-1]
        s = ema(df["close"], self.slow).iloc[-1]
        a = atr(df, self.atr_period).iloc[-1]
        close = df["close"].iloc[-1]
        separation = abs(f - s)

        trend = FLAT
        if f > s and close > s:
            trend = LONG
        elif f < s and close < s:
            trend = SHORT

        # Exit as soon as the trend flips or dies; only *enter* when the
        # separation shows a real wave rather than chop.
        if current_direction != FLAT:
            if trend == current_direction:
                return Signal(current_direction, "trend intact")
            return Signal(FLAT, "trend flipped")

        if trend != FLAT and separation >= self.min_separation_atr * a:
            side = "up" if trend == LONG else "down"
            return Signal(trend, f"{side}trend (ema{self.fast}/{self.slow} apart {separation:.2f})")
        return Signal(FLAT, "no clear wave")
