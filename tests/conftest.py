from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


def make_ohlcv(closes: np.ndarray, start: str = "2026-01-01", freq: str = "1h",
               spread: float = 0.5) -> pd.DataFrame:
    """Build a plausible OHLCV frame around a given close path."""
    idx = pd.date_range(start, periods=len(closes), freq=freq)
    closes = np.asarray(closes, dtype=float)
    opens = np.concatenate([[closes[0]], closes[:-1]])
    highs = np.maximum(opens, closes) + spread
    lows = np.minimum(opens, closes) - spread
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes,
         "volume": np.full(len(closes), 1000.0)},
        index=idx,
    )


@pytest.fixture
def rng() -> np.random.Generator:
    return np.random.default_rng(7)
