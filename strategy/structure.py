"""Market structure analysis: BOS, CHoCH, Order Blocks, FVG, Liquidity Sweeps."""
from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class OrderBlock:
    index: int
    timestamp: str
    high: float
    low: float
    direction: str      # "bullish" | "bearish"
    mitigated: bool = False


@dataclass
class FairValueGap:
    index: int
    timestamp: str
    top: float
    bottom: float
    direction: str      # "bullish" | "bearish"
    filled: bool = False


@dataclass
class StructureResult:
    bos_bullish: bool = False       # bullish Break of Structure on latest bar
    bos_bearish: bool = False       # bearish Break of Structure on latest bar
    choch_bullish: bool = False     # bullish Change of Character (trend flip)
    choch_bearish: bool = False     # bearish Change of Character (trend flip)
    trend: str = "ranging"          # "bullish" | "bearish" | "ranging"
    order_blocks: list[OrderBlock] = field(default_factory=list)
    fvgs: list[FairValueGap] = field(default_factory=list)
    liquidity_sweep_high: bool = False
    liquidity_sweep_low: bool = False


def _ts(df: pd.DataFrame, i: int) -> str:
    if "timestamp" in df.columns:
        return str(df["timestamp"].iloc[i])
    return str(i)


def _find_pivots(
    high: pd.Series, low: pd.Series, window: int = 5
) -> tuple[pd.Series, pd.Series]:
    """Return swing highs and swing lows as series (NaN where not a pivot)."""
    n = len(high)
    pivot_highs = pd.Series(np.nan, index=high.index)
    pivot_lows = pd.Series(np.nan, index=low.index)

    for i in range(window, n - window):
        h_slice = high.iloc[i - window : i + window + 1]
        l_slice = low.iloc[i - window : i + window + 1]
        if high.iloc[i] >= h_slice.max():
            pivot_highs.iloc[i] = high.iloc[i]
        if low.iloc[i] <= l_slice.min():
            pivot_lows.iloc[i] = low.iloc[i]

    return pivot_highs, pivot_lows


def _find_order_blocks(df: pd.DataFrame, lookback: int = 20) -> list[OrderBlock]:
    """Last opposing candle before a significant impulsive move."""
    n = len(df)
    start = max(0, n - lookback - 2)
    last_close = float(df["close"].iloc[-1])
    blocks: list[OrderBlock] = []

    for i in range(start, n - 2):
        c0 = df.iloc[i]
        c1 = df.iloc[i + 1]

        body0 = abs(float(c0["close"]) - float(c0["open"]))
        body1 = abs(float(c1["close"]) - float(c1["open"]))
        # Require c1 to be a meaningful impulse (body > c0 body)
        if body1 < body0:
            continue

        # Bearish OB: last bearish candle before a bullish impulse
        if c0["close"] < c0["open"] and c1["close"] > c1["open"] and c1["close"] > c0["high"]:
            mitigated = float(c0["low"]) <= last_close <= float(c0["high"])
            blocks.append(
                OrderBlock(
                    index=i,
                    timestamp=_ts(df, i),
                    high=float(c0["high"]),
                    low=float(c0["low"]),
                    direction="bearish",
                    mitigated=mitigated,
                )
            )

        # Bullish OB: last bullish candle before a bearish impulse
        elif c0["close"] > c0["open"] and c1["close"] < c1["open"] and c1["close"] < c0["low"]:
            mitigated = float(c0["low"]) <= last_close <= float(c0["high"])
            blocks.append(
                OrderBlock(
                    index=i,
                    timestamp=_ts(df, i),
                    high=float(c0["high"]),
                    low=float(c0["low"]),
                    direction="bullish",
                    mitigated=mitigated,
                )
            )

    return blocks[-5:]


def _find_fvgs(df: pd.DataFrame, lookback: int = 20) -> list[FairValueGap]:
    """3-candle imbalance: gap between candle[i] and candle[i+2]."""
    n = len(df)
    start = max(0, n - lookback - 2)
    last_close = float(df["close"].iloc[-1])
    fvgs: list[FairValueGap] = []

    for i in range(start, n - 2):
        c0 = df.iloc[i]
        c2 = df.iloc[i + 2]

        # Bullish FVG: gap between top of c0 and bottom of c2
        if float(c0["high"]) < float(c2["low"]):
            top = float(c2["low"])
            bottom = float(c0["high"])
            filled = bottom <= last_close <= top
            fvgs.append(
                FairValueGap(
                    index=i + 1,
                    timestamp=_ts(df, i + 1),
                    top=top,
                    bottom=bottom,
                    direction="bullish",
                    filled=filled,
                )
            )

        # Bearish FVG: gap between bottom of c0 and top of c2
        elif float(c0["low"]) > float(c2["high"]):
            top = float(c0["low"])
            bottom = float(c2["high"])
            filled = bottom <= last_close <= top
            fvgs.append(
                FairValueGap(
                    index=i + 1,
                    timestamp=_ts(df, i + 1),
                    top=top,
                    bottom=bottom,
                    direction="bearish",
                    filled=filled,
                )
            )

    return fvgs[-5:]


def detect_structure(df: pd.DataFrame, lookback: int = 50, swing_window: int = 5) -> StructureResult:
    """Analyse the most recent bar for market structure events.

    df must have columns: high, low, close (and optionally timestamp).
    """
    result = StructureResult()
    min_bars = swing_window * 2 + lookback
    if len(df) < min_bars:
        return result

    recent = df.iloc[-lookback:].reset_index(drop=True)
    ph, pl = _find_pivots(recent["high"], recent["low"], swing_window)
    valid_highs = ph.dropna()
    valid_lows = pl.dropna()

    last_close = float(recent["close"].iloc[-1])
    last_high = float(recent["high"].iloc[-1])
    last_low = float(recent["low"].iloc[-1])

    # Trend via 20-bar close slope
    if len(recent) >= 20:
        slope = float(recent["close"].iloc[-1]) - float(recent["close"].iloc[-20])
        result.trend = "bullish" if slope > 0 else ("bearish" if slope < 0 else "ranging")

    # BOS / CHoCH
    if len(valid_highs) >= 1:
        last_sh = float(valid_highs.iloc[-1])
        if last_close > last_sh:
            if result.trend == "bullish":
                result.bos_bullish = True
            else:
                result.choch_bullish = True  # was bearish, now broke structure up → CHoCH

    if len(valid_lows) >= 1:
        last_sl = float(valid_lows.iloc[-1])
        if last_close < last_sl:
            if result.trend == "bearish":
                result.bos_bearish = True
            else:
                result.choch_bearish = True  # was bullish, now broke structure down → CHoCH

    # Liquidity sweeps: wick past prior pivot then closed back
    if len(valid_highs) >= 1:
        prev_sh = float(valid_highs.iloc[-1])
        if last_high > prev_sh and last_close < prev_sh:
            result.liquidity_sweep_high = True

    if len(valid_lows) >= 1:
        prev_sl = float(valid_lows.iloc[-1])
        if last_low < prev_sl and last_close > prev_sl:
            result.liquidity_sweep_low = True

    result.order_blocks = _find_order_blocks(recent)
    result.fvgs = _find_fvgs(recent)

    return result
