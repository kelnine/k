"""Mean reversion for index futures/ETFs on 15-minute candles.

Indices overextend by a couple of standard deviations every few hours and
usually snap back to the short-term mean. We fade those stretches:

- enter long when price closes > `entry_z` std devs *below* the 20-bar mean
  with RSI confirming oversold; short is the mirror image
- exit when price reverts to the mean (z-score crosses ~0), or via the
  hard stop managed by the risk engine
"""

from __future__ import annotations

import pandas as pd

from ..indicators import rsi, zscore
from .base import FLAT, LONG, SHORT, Signal, Strategy


class MeanReversion(Strategy):
    def __init__(
        self,
        lookback: int = 20,
        entry_z: float = 2.0,
        exit_z: float = 0.25,
        rsi_period: int = 14,
        rsi_oversold: float = 32.0,
        rsi_overbought: float = 68.0,
    ):
        self.lookback = lookback
        self.entry_z = entry_z
        self.exit_z = exit_z
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.warmup = max(lookback, rsi_period) + 5

    def signal(self, df: pd.DataFrame, current_direction: int = FLAT) -> Signal:
        if len(df) < self.warmup:
            return Signal(FLAT, "warmup")

        z = zscore(df["close"], self.lookback).iloc[-1]
        r = rsi(df["close"], self.rsi_period).iloc[-1]
        if pd.isna(z):
            return Signal(FLAT, "no signal (flat band)")

        # Exits first: ride the snap-back to the mean, then get out.
        if current_direction == LONG:
            if z >= -self.exit_z:
                return Signal(FLAT, f"reverted to mean (z={z:.2f})")
            return Signal(LONG, "holding reversion long")
        if current_direction == SHORT:
            if z <= self.exit_z:
                return Signal(FLAT, f"reverted to mean (z={z:.2f})")
            return Signal(SHORT, "holding reversion short")

        if z <= -self.entry_z and r <= self.rsi_oversold:
            return Signal(LONG, f"oversold stretch (z={z:.2f}, rsi={r:.0f})")
        if z >= self.entry_z and r >= self.rsi_overbought:
            return Signal(SHORT, f"overbought stretch (z={z:.2f}, rsi={r:.0f})")
        return Signal(FLAT, "inside band")
