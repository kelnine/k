from datetime import datetime

import numpy as np

from tradingbot.broker import PaperBroker
from tradingbot.config import INSTRUMENTS, BotConfig
from tradingbot.engine import Engine
from tradingbot.strategies.base import LONG

from .conftest import make_ohlcv


def test_round_trip_pnl_is_net_of_both_fills():
    broker = PaperBroker(equity=100_000)
    now = datetime(2026, 1, 1)
    broker.open_position("SPX", LONG, 10, 5000, 4950, now, cost=7.50)
    trade = broker.close_position("SPX", 5010, now, reason="exit", cost=7.52)
    assert abs(trade.costs - 15.02) < 1e-9
    assert abs(trade.pnl - (10 * 10 - 15.02)) < 1e-9
    assert abs(broker.equity - (100_000 + trade.pnl)) < 1e-9


def test_engine_charges_costs_on_entry(tmp_path):
    cfg = BotConfig(journal_path=str(tmp_path / "journal.csv"))
    engine = Engine(cfg, instruments={"BTC": INSTRUMENTS["BTC"]})
    flat = np.full(60, 50_000.0) + np.sin(np.arange(60)) * 100
    breakout = flat.copy()
    breakout[-1] = 54_000.0
    engine.step({"BTC": make_ohlcv(breakout, spread=50)}, datetime(2026, 1, 2))
    pos = engine.broker.positions["BTC"]
    expected = pos.entry_price * pos.quantity * INSTRUMENTS["BTC"].cost_bps / 10_000
    assert abs(pos.cost_paid - expected) < 1e-6
    assert pos.cost_paid > 0


def test_costs_turn_a_scratch_trade_into_a_loss():
    broker = PaperBroker(equity=100_000)
    now = datetime(2026, 1, 1)
    broker.open_position("NDX", LONG, 5, 18_000, 17_900, now, cost=18.0)
    trade = broker.close_position("NDX", 18_000, now, reason="flat exit", cost=18.0)
    assert trade.pnl < 0  # zero price move still costs the spread twice
