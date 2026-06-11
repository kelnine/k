from datetime import datetime

import numpy as np

from tradingbot.config import INSTRUMENTS, BotConfig, RiskConfig
from tradingbot.engine import Engine
from tradingbot.liquid import LIQUID_SYMBOLS, entry_ticket, read_tickets
from tradingbot.risk import plan_position
from tradingbot.strategies.base import LONG

from .conftest import make_ohlcv


def test_every_instrument_maps_to_a_liquid_market():
    assert set(LIQUID_SYMBOLS) == set(INSTRUMENTS)


def test_entry_ticket_carries_bot_sizing_and_stop():
    cfg = RiskConfig(starting_equity=10_000)
    plan = plan_position(10_000, 62_000, atr_value=400, direction=LONG, cfg=cfg)
    ticket = entry_ticket(INSTRUMENTS["BTC"], LONG, 62_000, plan,
                          datetime(2026, 6, 11), "breakout")
    assert ticket.liquid_asset == "BTC"
    assert ticket.side == "long"
    assert ticket.stop_loss == plan.stop_price
    assert abs(ticket.notional_usd - plan.quantity * 62_000) < 0.01


def test_engine_emits_tickets_for_entries_and_stops(tmp_path):
    cfg = BotConfig(journal_path=str(tmp_path / "j.csv"),
                    ticket_path=str(tmp_path / "tickets.jsonl"))
    engine = Engine(cfg, instruments={"BTC": INSTRUMENTS["BTC"]})

    flat = np.full(60, 50_000.0) + np.sin(np.arange(60)) * 100
    breakout = flat.copy()
    breakout[-1] = 54_000.0
    engine.step({"BTC": make_ohlcv(breakout, spread=50)}, datetime(2026, 1, 2))

    tickets = read_tickets(cfg.ticket_path)
    assert len(tickets) == 1
    assert tickets[0].action == "open" and tickets[0].side == "long"
    assert tickets[0].stop_loss < 54_000

    # crash through the stop: a close ticket must follow
    crash = np.concatenate([breakout, [40_000.0]])
    engine.step({"BTC": make_ohlcv(crash, spread=50)}, datetime(2026, 1, 3))
    tickets = read_tickets(cfg.ticket_path)
    assert tickets[-1].action == "close"
    assert tickets[-1].reason == "hard stop hit"
