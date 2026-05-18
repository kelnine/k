"""OHLCV data feed.

Uses ccxt (Bybit public endpoint by default) when available.
Falls back to deterministic synthetic data for offline testing.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_CCXT_AVAILABLE = False
try:
    import ccxt
    _CCXT_AVAILABLE = True
except ImportError:
    pass

_TIMEFRAME_MS: dict[str, int] = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}


class DataFeed:
    def __init__(self, config: dict) -> None:
        self.timeframe: str = config.get("timeframe", "15m")
        self._exchange: Optional[object] = None
        self._init_exchange()

    def fetch(self, symbol: str, limit: int = 500) -> pd.DataFrame:
        """Return a DataFrame with columns: timestamp, open, high, low, close, volume."""
        if self._exchange is not None:
            df = self._fetch_live(symbol, limit)
            if df is not None and len(df) >= 50:
                return df
        return self._synthetic(symbol, limit)

    def get_latest_price(self, symbol: str) -> float:
        return float(self.fetch(symbol, limit=5)["close"].iloc[-1])

    # ── Private ───────────────────────────────────────────────────────────────

    def _init_exchange(self) -> None:
        if not _CCXT_AVAILABLE:
            logger.warning("ccxt not installed — using synthetic OHLCV data")
            return
        try:
            self._exchange = ccxt.bybit({"options": {"defaultType": "linear"}})
            logger.info("DataFeed using Bybit public market data")
        except Exception as exc:
            logger.warning(f"DataFeed: could not initialise exchange ({exc})")

    def _fetch_live(self, symbol: str, limit: int) -> Optional[pd.DataFrame]:
        ccxt_symbol = self._to_ccxt(symbol)
        try:
            raw = self._exchange.fetch_ohlcv(  # type: ignore[union-attr]
                ccxt_symbol, self.timeframe, limit=limit
            )
            df = pd.DataFrame(
                raw, columns=["timestamp", "open", "high", "low", "close", "volume"]
            )
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
            logger.debug(f"Fetched {len(df)} bars for {symbol}")
            return df
        except Exception as exc:
            logger.error(f"Live fetch failed for {symbol}: {exc} — falling back to synthetic")
            return None

    @staticmethod
    def _to_ccxt(symbol: str) -> str:
        base = symbol.replace("-PERP", "").replace(":USDT", "")
        return f"{base}/USDT:USDT"

    @staticmethod
    def _synthetic(symbol: str, limit: int) -> pd.DataFrame:
        """Seeded synthetic OHLCV walk — used for offline / CI runs."""
        seed = abs(hash(symbol)) % (2**31)
        rng = np.random.default_rng(seed)

        base_price = {"BTC-PERP": 65_000.0, "ETH-PERP": 3_500.0}.get(symbol, 100.0)
        tf_ms = _TIMEFRAME_MS.get("15m", 900_000)
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        ts = [now_ms - (limit - i) * tf_ms for i in range(limit)]

        log_returns = rng.normal(0, 0.002, limit)
        closes = base_price * np.exp(np.cumsum(log_returns))

        noise_h = np.abs(rng.normal(0, 0.003, limit))
        noise_l = np.abs(rng.normal(0, 0.003, limit))
        highs = closes * (1 + noise_h)
        lows = closes * (1 - noise_l)
        opens = np.roll(closes, 1)
        opens[0] = closes[0]
        volumes = rng.uniform(50, 500, limit) * base_price / 1_000

        df = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(ts, unit="ms", utc=True),
                "open": opens,
                "high": highs,
                "low": lows,
                "close": closes,
                "volume": volumes,
            }
        )
        logger.debug(f"Generated {limit} synthetic bars for {symbol}")
        return df
