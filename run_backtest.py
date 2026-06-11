#!/usr/bin/env python3
"""Backtest the full five-instrument book on recent Yahoo Finance history."""

from __future__ import annotations

from tradingbot.backtest import run_backtest
from tradingbot.config import INSTRUMENTS
from tradingbot.data import fetch_ohlcv


def main() -> None:
    data = {}
    for sym, inst in INSTRUMENTS.items():
        print(f"fetching {sym} ({inst.ticker}, {inst.timeframe})...")
        data[sym] = fetch_ohlcv(inst)
        print(f"  {len(data[sym])} bars, {data[sym].index[0]} -> {data[sym].index[-1]}")

    result = run_backtest(data, INSTRUMENTS)
    print()
    print(result.summary())


if __name__ == "__main__":
    main()
