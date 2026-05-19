"""
Confirms trade direction using EMA and VWAP on intraday price data.

Uses yfinance for free market data (5-minute bars, current session).
A call signal is confirmed when price is above both EMA20 and VWAP.
A put signal is confirmed when price is below both EMA20 and VWAP.
"""
import logging
from datetime import datetime

import numpy as np
import pandas as pd
import pytz

logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _vwap(df: pd.DataFrame) -> pd.Series:
    """Session VWAP: cumulative (typical_price * volume) / cumulative volume."""
    tp = (df["High"] + df["Low"] + df["Close"]) / 3
    cum_tpv = (tp * df["Volume"]).cumsum()
    cum_vol = df["Volume"].cumsum()
    return cum_tpv / cum_vol


class TrendConfirmer:
    def __init__(self, ema_fast: int = 20, ema_slow: int = 50):
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self._cache: dict[str, tuple[datetime, bool]] = {}

    async def confirm(self, signal: dict) -> bool:
        """
        Returns True when the underlying's trend agrees with the signal direction.
        Falls back to True (allow the trade) if market data is unavailable.
        """
        ticker = signal["ticker"]
        option_type = signal["option_type"]

        # Simple cache: re-use result for same ticker within 2 minutes
        now = datetime.utcnow()
        if ticker in self._cache:
            cached_time, cached_result = self._cache[ticker]
            if (now - cached_time).seconds < 120:
                logger.debug(f"Trend cache hit for {ticker}: {cached_result}")
                return cached_result

        try:
            df = await self._fetch_intraday(ticker)
            if df is None or df.empty or len(df) < self.ema_fast:
                logger.warning(f"Not enough data for {ticker}, allowing trade.")
                return True

            df["EMA_fast"] = _ema(df["Close"], self.ema_fast)
            df["EMA_slow"] = _ema(df["Close"], self.ema_slow)
            df["VWAP"] = _vwap(df)

            last = df.iloc[-1]
            price = last["Close"]
            ema_f = last["EMA_fast"]
            ema_s = last["EMA_slow"]
            vwap = last["VWAP"]

            logger.info(
                f"{ticker} | Price={price:.2f} EMA{self.ema_fast}={ema_f:.2f} "
                f"EMA{self.ema_slow}={ema_s:.2f} VWAP={vwap:.2f}"
            )

            if option_type == "call":
                confirmed = price > ema_f and price > vwap
            else:  # put
                confirmed = price < ema_f and price < vwap

            if not confirmed:
                logger.info(f"Trend NOT confirmed for {ticker} {option_type}")
            else:
                logger.info(f"Trend CONFIRMED for {ticker} {option_type}")

            self._cache[ticker] = (now, confirmed)
            return confirmed

        except Exception as exc:
            logger.warning(f"Trend confirm failed for {ticker}: {exc}. Allowing trade.")
            return True

    async def _fetch_intraday(self, ticker: str) -> pd.DataFrame | None:
        try:
            import yfinance as yf

            # Run blocking yf call in thread to avoid blocking the event loop
            import asyncio
            loop = asyncio.get_event_loop()
            df = await loop.run_in_executor(
                None,
                lambda: yf.download(
                    ticker,
                    period="1d",
                    interval="5m",
                    progress=False,
                    auto_adjust=True,
                ),
            )
            if df.empty:
                return None
            # Flatten multi-level columns if present
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            return df
        except Exception as exc:
            logger.warning(f"yfinance download failed for {ticker}: {exc}")
            return None
