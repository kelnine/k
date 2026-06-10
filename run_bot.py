#!/usr/bin/env python3
"""Live paper-trading loop.

Every 15 minutes: fetch fresh candles for all five instruments, let the
engine manage stops/exits/entries, and persist state. At 07:00 the morning
briefing goes out, at 21:00 the evening recap (local time).

This is PAPER trading — no real orders are placed anywhere.
"""

from __future__ import annotations

import time
from datetime import datetime

from tradingbot.config import INSTRUMENTS, BotConfig
from tradingbot.data import fetch_ohlcv
from tradingbot.engine import Engine
from tradingbot.notify import send
from tradingbot.reports import evening_recap, morning_briefing

POLL_SECONDS = 15 * 60
BRIEFING_HOUR = 7
RECAP_HOUR = 21


def fetch_all() -> dict:
    data = {}
    for sym, inst in INSTRUMENTS.items():
        try:
            data[sym] = fetch_ohlcv(inst)
        except Exception as exc:
            print(f"[data] {sym}: fetch failed ({exc}); skipping this cycle")
    return data


def main() -> None:
    engine = Engine(BotConfig())
    sent_on: dict[str, str] = {}  # message kind -> date already sent

    print(f"Paper trading {', '.join(INSTRUMENTS)} — equity {engine.broker.equity:,.0f}")
    while True:
        now = datetime.now()
        data = fetch_all()
        if data:
            engine.step(data, now)

        today = now.strftime("%Y-%m-%d")
        if now.hour >= BRIEFING_HOUR and sent_on.get("briefing") != today and data:
            send(morning_briefing(data, INSTRUMENTS, engine.broker, now))
            sent_on["briefing"] = today
        if now.hour >= RECAP_HOUR and sent_on.get("recap") != today:
            send(evening_recap(engine.broker, now))
            sent_on["recap"] = today

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
