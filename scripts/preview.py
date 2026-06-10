"""Preview rendered signals WITHOUT a Telegram token.

Usage:
    python scripts/preview.py            # live Binance data
    python scripts/preview.py --sample   # offline canned snapshot (Liquid shape)
"""
from __future__ import annotations

import os
import sys

# Minimal env so Config() constructs without a real bot.
os.environ.setdefault("BOT_TOKEN", "preview")
os.environ.setdefault("FREE_CHANNEL", "preview")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.config import Config  # noqa: E402
from bot.datasources import BinanceDataSource, LiquidDataSource  # noqa: E402
from bot.formatter import render  # noqa: E402
from bot.strategy import generate  # noqa: E402

# A canned response in the exact Liquid analyze_market shape (positioning incl.)
SAMPLE = {
    "symbol": "BTC",
    "refCode": "NMX8B0ND",
    "ticker": {"markPx": "61195.0", "funding": "0.0009%",
               "openInterest": "$1,952,787,030", "prevDayPx": "63219.0"},
    "sections": {"size": {"breakdownBySize": [
        {"size": "<$1k", "minSize": None, "maxSize": 1000,
         "totalPositionValue": 3406313, "totalPositionValueLong": 1952009},
        {"size": "$1k–$10k", "minSize": 1000, "maxSize": 10000,
         "totalPositionValue": 25428943, "totalPositionValueLong": 14615602},
        {"size": "$1m–$2.5m", "minSize": 1000000, "maxSize": 2500000,
         "totalPositionValue": 224304708, "totalPositionValueLong": 92388430},
        {"size": ">$2.5m", "minSize": 2500000, "maxSize": None,
         "totalPositionValue": 1238948647, "totalPositionValueLong": 634006019},
    ]}},
}


def main() -> None:
    cfg = Config()
    if "--sample" in sys.argv:
        snaps = [LiquidDataSource.parse(SAMPLE)]
    else:
        src = BinanceDataSource()
        snaps = [src.snapshot(s) for s in cfg.watchlist]

    any_signal = False
    for snap in snaps:
        if not snap:
            continue
        sig = generate(snap)
        if not sig:
            print(f"— {snap.symbol}: no conviction, skipped\n")
            continue
        any_signal = True
        print("=" * 48)
        print(render(sig, cfg, tier="free"))
        print("-" * 48, "(VIP version) ")
        print(render(sig, cfg, tier="vip"))
        print()
    if not any_signal:
        print("No signals met threshold this scan.")


if __name__ == "__main__":
    main()
