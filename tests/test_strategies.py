import numpy as np

from tradingbot.strategies import MeanReversion, MomentumBreakout, TrendFollowing
from tradingbot.strategies.base import FLAT, LONG, SHORT

from .conftest import make_ohlcv


def test_mean_reversion_fades_a_dump():
    closes = np.full(80, 100.0) + np.sin(np.arange(80)) * 0.3
    closes[-4:] = [97.5, 95.0, 92.5, 90.0]  # sharp persistent slide
    sig = MeanReversion().signal(make_ohlcv(closes))
    assert sig.direction == LONG


def test_mean_reversion_exits_at_the_mean():
    closes = 100.0 + 0.3 * np.sin(2 * np.pi * np.arange(80) / 20)
    closes[-1] = 100.0  # price back at the 20-bar mean
    sig = MeanReversion().signal(make_ohlcv(closes), current_direction=LONG)
    assert sig.direction == FLAT
    assert "mean" in sig.reason


def test_momentum_buys_breakout_not_chop():
    flat = np.full(60, 100.0) + np.sin(np.arange(60)) * 0.5
    strat = MomentumBreakout()
    assert strat.signal(make_ohlcv(flat)).direction == FLAT

    breakout = flat.copy()
    breakout[-1] = 108.0  # clears the prior 20-bar high with range expansion
    assert strat.signal(make_ohlcv(breakout)).direction == LONG


def test_momentum_shorts_breakdown():
    flat = np.full(60, 100.0) + np.sin(np.arange(60)) * 0.5
    breakdown = flat.copy()
    breakdown[-1] = 92.0
    assert MomentumBreakout().signal(make_ohlcv(breakdown)).direction == SHORT


def test_trend_following_rides_clean_wave_and_skips_chop(rng):
    wave = np.linspace(100, 140, 120)  # clean uptrend
    sig = TrendFollowing().signal(make_ohlcv(wave, freq="4h"))
    assert sig.direction == LONG

    chop = 100 + rng.normal(0, 0.2, 120).cumsum() * 0.1
    sig = TrendFollowing().signal(make_ohlcv(chop, freq="4h"))
    assert sig.direction == FLAT


def test_trend_following_exits_on_flip():
    rolled = np.concatenate([np.linspace(100, 140, 80), np.linspace(140, 110, 40)])
    sig = TrendFollowing().signal(make_ohlcv(rolled, freq="4h"), current_direction=LONG)
    assert sig.direction == FLAT
