"""Market data via Yahoo Finance, normalised to lowercase OHLCV columns.

Yahoo serves 15m bars ~60 days back and 1h bars ~730 days back; 4h bars are
resampled from 1h. Good enough for signal generation and paper trading —
swap this module for a broker/exchange feed when going further.
"""

from __future__ import annotations

import pandas as pd

from .config import Instrument

_FETCH_PARAMS = {  # timeframe -> (yfinance interval, history period)
    "15m": ("15m", "30d"),
    "1h": ("1h", "180d"),
    "4h": ("1h", "360d"),  # fetched at 1h, resampled below
}


def _normalise(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
    return df.dropna(subset=["close"])


def resample_4h(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df.resample("4h")
        .agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
        )
        .dropna(subset=["close"])
    )


def fetch_ohlcv(instrument: Instrument) -> pd.DataFrame:
    import yfinance as yf

    interval, period = _FETCH_PARAMS[instrument.timeframe]
    raw = yf.download(
        instrument.ticker,
        interval=interval,
        period=period,
        auto_adjust=True,
        progress=False,
    )
    if raw is None or raw.empty:
        raise RuntimeError(f"no data returned for {instrument.ticker}")
    df = _normalise(raw)
    if instrument.timeframe == "4h":
        df = resample_4h(df)
    return df
