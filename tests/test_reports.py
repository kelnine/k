from datetime import datetime

import numpy as np

from tradingbot.broker import PaperBroker
from tradingbot.config import INSTRUMENTS
from tradingbot.reports import evening_recap, morning_briefing
from tradingbot.strategies.base import LONG

from .conftest import make_ohlcv


def test_morning_briefing_mentions_every_instrument():
    data = {sym: make_ohlcv(np.linspace(100, 105, 60)) for sym in INSTRUMENTS}
    broker = PaperBroker(equity=100_000)
    text = morning_briefing(data, INSTRUMENTS, broker, datetime(2026, 6, 10, 7, 0))
    for sym in INSTRUMENTS:
        assert sym in text
    assert "Equity" in text


def test_evening_recap_reports_closed_trades():
    broker = PaperBroker(equity=100_000)
    now = datetime(2026, 6, 10, 21, 0)
    broker.open_position("SPX", LONG, 2, 5000, 4950, now)
    broker.close_position("SPX", 5025, now, reason="reverted to mean")
    text = evening_recap(broker, now)
    assert "SPX" in text and "+50.00" in text
    assert "1 winners" in text or "1 trade(s)" in text


def test_evening_recap_handles_no_trades():
    broker = PaperBroker(equity=100_000)
    text = evening_recap(broker, datetime(2026, 6, 10, 21, 0))
    assert "No trades closed today" in text
