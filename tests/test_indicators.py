import numpy as np
import pandas as pd

from tradingbot.indicators import atr, donchian, ema, rsi, sma, zscore

from .conftest import make_ohlcv


def test_sma_and_ema_track_constant_series():
    s = pd.Series([5.0] * 50)
    assert sma(s, 10).iloc[-1] == 5.0
    assert abs(ema(s, 10).iloc[-1] - 5.0) < 1e-9


def test_zscore_flags_extension():
    closes = np.full(60, 100.0) + np.sin(np.arange(60))  # mild oscillation
    closes[-1] = 110.0  # big stretch
    z = zscore(pd.Series(closes), 20)
    assert z.iloc[-1] > 2.0


def test_rsi_bounds_and_direction():
    up = pd.Series(np.linspace(100, 150, 60))
    down = pd.Series(np.linspace(150, 100, 60))
    assert 70 < rsi(up).iloc[-1] <= 100
    assert 0 <= rsi(down).iloc[-1] < 30


def test_atr_positive_and_scales_with_range():
    quiet = make_ohlcv(np.full(60, 100.0), spread=0.1)
    wild = make_ohlcv(np.full(60, 100.0), spread=5.0)
    assert atr(quiet).iloc[-1] > 0
    assert atr(wild).iloc[-1] > 10 * atr(quiet).iloc[-1]


def test_donchian_excludes_current_bar():
    closes = np.linspace(100, 120, 40)
    df = make_ohlcv(closes)
    upper, _ = donchian(df, 20)
    # current close is a new high, so it must exceed the *prior* channel top
    assert df["close"].iloc[-1] > upper.iloc[-1]
