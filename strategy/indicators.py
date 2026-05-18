"""Technical indicator calculations: EMA, RSI, ADX, ATR, Volume Ratio."""
from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass


@dataclass
class Indicators:
    ema_9: pd.Series
    ema_21: pd.Series
    ema_50: pd.Series
    ema_200: pd.Series
    rsi: pd.Series
    adx: pd.Series
    di_plus: pd.Series
    di_minus: pd.Series
    atr: pd.Series
    volume_ratio: pd.Series  # current bar volume / 20-bar average


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(span=period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(span=period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def _adx(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Returns (ADX, +DI, -DI)."""
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)

    up = high.diff()
    down = -low.diff()
    pos_dm = pd.Series(
        np.where((up > down) & (up > 0), up, 0.0), index=high.index
    )
    neg_dm = pd.Series(
        np.where((down > up) & (down > 0), down, 0.0), index=high.index
    )

    smooth_tr = tr.ewm(span=period, adjust=False).mean().replace(0, np.nan)
    di_plus = 100 * pos_dm.ewm(span=period, adjust=False).mean() / smooth_tr
    di_minus = 100 * neg_dm.ewm(span=period, adjust=False).mean() / smooth_tr

    dx = (
        100
        * (di_plus - di_minus).abs()
        / (di_plus + di_minus).replace(0, np.nan)
    ).fillna(0)
    adx = dx.ewm(span=period, adjust=False).mean()

    return adx.fillna(0), di_plus.fillna(0), di_minus.fillna(0)


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def compute(df: pd.DataFrame, cfg: dict) -> Indicators:
    """Compute all indicators from an OHLCV DataFrame.

    Required columns: open, high, low, close, volume.
    """
    periods = cfg.get("ema_periods", [9, 21, 50, 200])
    adx, di_plus, di_minus = _adx(
        df["high"], df["low"], df["close"], cfg.get("adx_period", 14)
    )
    avg_vol = df["volume"].rolling(20).mean().replace(0, np.nan)

    return Indicators(
        ema_9=_ema(df["close"], periods[0]),
        ema_21=_ema(df["close"], periods[1]),
        ema_50=_ema(df["close"], periods[2]),
        ema_200=_ema(df["close"], periods[3]),
        rsi=_rsi(df["close"], cfg.get("rsi_period", 14)),
        adx=adx,
        di_plus=di_plus,
        di_minus=di_minus,
        atr=_atr(df["high"], df["low"], df["close"]),
        volume_ratio=df["volume"] / avg_vol,
    )
