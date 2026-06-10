from datetime import datetime

import numpy as np

from tradingbot.backtest import run_backtest
from tradingbot.broker import PaperBroker
from tradingbot.config import INSTRUMENTS, BotConfig, Instrument
from tradingbot.engine import Engine
from tradingbot.strategies.base import LONG

from .conftest import make_ohlcv


def test_hard_stop_fires_before_strategy(tmp_path):
    cfg = BotConfig(journal_path=str(tmp_path / "journal.csv"))
    engine = Engine(cfg, instruments={"BTC": INSTRUMENTS["BTC"]})
    engine.broker.open_position("BTC", LONG, 1.0, 50_000, stop_price=49_000,
                                at=datetime(2026, 1, 1), reason="test")
    closes = np.full(60, 50_000.0)
    closes[-1] = 48_500.0  # bar trades through the stop
    df = make_ohlcv(closes, spread=50)
    engine.step({"BTC": df}, datetime(2026, 1, 2))
    assert "BTC" not in engine.broker.positions
    trade = engine.broker.closed_trades[-1]
    assert trade.exit_reason == "hard stop hit"
    assert abs(trade.pnl - (49_000 - 50_000)) < 1e-6
    assert (tmp_path / "journal.csv").exists()


def test_correlation_filter_blocks_third_risk_on_entry_in_engine(tmp_path):
    cfg = BotConfig(journal_path=str(tmp_path / "journal.csv"))
    engine = Engine(cfg, instruments=dict(INSTRUMENTS))
    now = datetime(2026, 1, 1)
    engine.broker.open_position("SPX", LONG, 1, 5000, 4950, now)
    engine.broker.open_position("NDX", LONG, 1, 18000, 17800, now)

    # feed BTC a textbook breakout: it should be skipped, not opened
    flat = np.full(60, 50_000.0) + np.sin(np.arange(60)) * 100
    breakout = flat.copy()
    breakout[-1] = 54_000.0
    engine.step({"BTC": make_ohlcv(breakout, spread=50)}, datetime(2026, 1, 2))
    assert "BTC" not in engine.broker.positions
    assert any("correlation filter" in line for line in engine.log)


def test_backtest_runs_and_keeps_risk_bounded(rng):
    instruments = {
        "SPX": INSTRUMENTS["SPX"],
        "BTC": INSTRUMENTS["BTC"],
        "GOLD": INSTRUMENTS["GOLD"],
    }
    data = {}
    for i, sym in enumerate(instruments):
        walk = 100 * np.exp(rng.normal(0.0002, 0.01, 500).cumsum())
        data[sym] = make_ohlcv(walk, freq="1h", spread=walk.mean() * 0.002)
    result = run_backtest(data, instruments)
    assert result.final_equity > 0
    # with a hard 1% stop per trade, drawdown over 500 bars stays sane
    assert result.max_drawdown < 0.25


def test_mark_to_market_includes_open_pnl():
    broker = PaperBroker(equity=100_000)
    broker.open_position("GOLD", LONG, 10, 2000, 1990, datetime(2026, 1, 1))
    assert broker.mark_to_market({"GOLD": 2005}) == 100_000 + 10 * 5
