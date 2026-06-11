#!/usr/bin/env python3
"""See the bot in action without internet access.

Simulates six weeks of realistic, correlated markets for all five
instruments at their native timeframes and replays them through the real
engine — same strategies, sizing, stops, and correlation filter as live.
Writes everything to demo_output/: trade journal, equity curve, action
log, and a sample 7am briefing + 9pm recap.
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd

from tradingbot.broker import PaperBroker
from tradingbot.config import INSTRUMENTS, BotConfig
from tradingbot.engine import Engine
from tradingbot.reports import evening_recap, morning_briefing

OUT_DIR = "demo_output"
WEEKS = 6
START = "2026-04-27"

# rough 2026 price levels and per-bar volatility per instrument
LEVELS = {"SPX": 5600.0, "NDX": 20000.0, "BTC": 62000.0, "GOLD": 2400.0, "OIL": 78.0}
BAR_VOL = {"15m": 0.0012, "1h": 0.004, "4h": 0.006}
BARS_PER_DAY = {"15m": 96, "1h": 24, "4h": 6}
PANDAS_FREQ = {"15m": "15min", "1h": "1h", "4h": "4h"}


def simulate_market(seed: int = 11) -> dict[str, pd.DataFrame]:
    """Correlated paths: SPX/NDX/BTC share a risk-on factor (which is what
    makes the correlation filter earn its keep), gold/oil get slow waves."""
    rng = np.random.default_rng(seed)
    days = WEEKS * 7
    data: dict[str, pd.DataFrame] = {}

    # one risk-on factor sampled at 15m resolution, aggregated as needed
    factor_15m = rng.normal(0, 1, days * BARS_PER_DAY["15m"])

    for sym, inst in INSTRUMENTS.items():
        tf = inst.timeframe
        n = days * BARS_PER_DAY[tf]
        stride = len(factor_15m) // n
        factor = factor_15m[: n * stride].reshape(n, stride).sum(axis=1) / np.sqrt(stride)

        beta = {"SPX": 0.7, "NDX": 0.8, "BTC": 0.5}.get(sym, 0.0)
        idio = rng.normal(0, 1, n)
        shocks = (beta * factor + np.sqrt(1 - beta**2) * idio) * BAR_VOL[tf]
        if inst.strategy == "trend_following":
            # commodities: add slow waves so there are trends to follow
            t = np.arange(n)
            shocks = shocks + 0.0025 * np.sin(2 * np.pi * t / (n / 3))
        closes = LEVELS[sym] * np.exp(shocks.cumsum())

        idx = pd.date_range(START, periods=n, freq=PANDAS_FREQ[tf])
        opens = np.concatenate([[closes[0]], closes[:-1]])
        spread = np.abs(rng.normal(0, 0.4, n)) * closes * BAR_VOL[tf]
        data[sym] = pd.DataFrame(
            {
                "open": opens,
                "high": np.maximum(opens, closes) + spread,
                "low": np.minimum(opens, closes) - spread,
                "close": closes,
                "volume": rng.uniform(500, 5000, n),
            },
            index=idx,
        )
    return data


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    journal_path = os.path.join(OUT_DIR, "journal.csv")
    if os.path.exists(journal_path):
        os.remove(journal_path)

    data = simulate_market()
    config = BotConfig(journal_path=journal_path)
    broker = PaperBroker(equity=config.risk.starting_equity, journal_path=journal_path)
    engine = Engine(config=config, broker=broker)

    clock = sorted(set().union(*[df.index for df in data.values()]))
    equity_points: dict[pd.Timestamp, float] = {}
    for ts in clock:
        window = {
            sym: df.loc[:ts].tail(400)
            for sym, df in data.items()
            if ts in df.index
        }
        if not window:
            continue
        engine.step(window, ts.to_pydatetime())
        prices = {sym: float(df.loc[:ts, "close"].iloc[-1]) for sym, df in data.items()
                  if not df.loc[:ts].empty}
        equity_points[ts] = broker.mark_to_market(prices)

    curve = pd.Series(equity_points).sort_index()
    peak = curve.cummax()
    max_dd = float(((peak - curve) / peak).max())
    wins = sum(1 for t in broker.closed_trades if t.pnl > 0)
    n_trades = len(broker.closed_trades)

    with open(os.path.join(OUT_DIR, "action_log.txt"), "w") as f:
        f.write("\n".join(engine.log) + "\n")

    last_ts = clock[-1].to_pydatetime()
    briefing = morning_briefing(
        {s: df for s, df in data.items()}, INSTRUMENTS, broker,
        last_ts.replace(hour=7, minute=0),
    )
    recap = evening_recap(broker, last_ts.replace(hour=21, minute=0))
    with open(os.path.join(OUT_DIR, "daily_messages.txt"), "w") as f:
        f.write(briefing + "\n\n" + "=" * 60 + "\n\n" + recap + "\n")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(11, 5))
        ax.plot(curve.index, curve.values, lw=1.2)
        ax.axhline(config.risk.starting_equity, color="grey", ls="--", lw=0.8)
        ax.set_title(
            f"Paper equity over {WEEKS} simulated weeks — "
            f"{n_trades} trades, {wins / n_trades:.0%} winners, max DD {max_dd:.1%}"
        )
        ax.set_ylabel("equity ($)")
        fig.autofmt_xdate()
        fig.tight_layout()
        fig.savefig(os.path.join(OUT_DIR, "equity_curve.png"), dpi=130)
    except ImportError:
        print("(matplotlib not installed — skipping equity_curve.png)")

    print()
    print("=" * 60)
    print(briefing)
    print()
    print(recap)
    print()
    print("=" * 60)
    print(
        f"RESULT: {n_trades} trades, {wins}/{n_trades} winners "
        f"({wins / n_trades:.0%}), final equity {broker.equity:,.0f} "
        f"({broker.equity / config.risk.starting_equity - 1:+.1%}), "
        f"max drawdown {max_dd:.1%}"
    )
    print(f"Artifacts written to {OUT_DIR}/: journal.csv, action_log.txt, "
          "daily_messages.txt, equity_curve.png")


if __name__ == "__main__":
    main()
