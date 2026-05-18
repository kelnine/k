"""Backtesting engine.

Replays historical OHLCV data bar-by-bar through the full strategy + risk +
paper execution stack and prints a performance summary.

Usage:
    python backtest.py                          # uses config/settings.yaml
    python backtest.py --config my.yaml --limit 2000
    python backtest.py --symbol BTC-PERP --limit 1000
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

from data.feed import DataFeed
from execution.paper import PaperExecution
from risk.engine import RiskEngine, RiskError
from strategy.engine import StrategyEngine

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("backtest")


def run(config: dict, symbol: str, df, warmup: int = 210) -> dict:
    """Run a full backtest; returns a results dict."""
    strategy = StrategyEngine(config)
    risk = RiskEngine(config)

    # Redirect paper output to a temp location to avoid polluting live logs
    bt_config = {**config}
    bt_config["logging"] = {
        "trade_history_csv": f"logs/bt_{symbol.replace('-','_')}_trades.csv",
        "dashboard_json": f"logs/bt_{symbol.replace('-','_')}_dashboard.json",
    }
    paper = PaperExecution(bt_config)

    signals_fired = 0
    trades_blocked = 0

    for i in range(warmup, len(df)):
        window = df.iloc[: i + 1]
        price = float(df["close"].iloc[i])

        closed, _ = paper.update_positions(symbol, price)
        for t in closed:
            risk.close_position()
            risk.record_pnl(t.pnl or 0.0)

        if risk.kill_switch:
            continue

        sig = strategy.analyze(symbol, window)
        if sig is None:
            continue
        signals_fired += 1

        try:
            params = risk.validate(sig)
        except RiskError:
            trades_blocked += 1
            continue

        paper.open_trade(params)
        risk.open_position()

    # Close remaining open positions at last bar price
    last_price = float(df["close"].iloc[-1])
    paper.close_all(symbol, last_price)

    # Load dashboard stats
    stats: dict = {}
    try:
        with open(paper.json_path) as fh:
            stats = json.load(fh)
    except Exception:
        pass

    return {
        "symbol": symbol,
        "bars_tested": len(df) - warmup,
        "signals_fired": signals_fired,
        "trades_blocked": trades_blocked,
        "trades_taken": stats.get("total_trades", 0),
        "win_rate_pct": stats.get("win_rate_pct", 0.0),
        "avg_win_usd": stats.get("avg_win_usd", 0.0),
        "avg_loss_usd": stats.get("avg_loss_usd", 0.0),
        "final_balance": stats.get("balance", paper.balance),
        "initial_balance": paper.initial_balance,
        "total_return_pct": stats.get("total_pnl_pct", 0.0),
        "trade_csv": str(paper.csv_path),
        "dashboard_json": str(paper.json_path),
    }


def _print_results(results: dict) -> None:
    width = 52
    print("\n" + "═" * width)
    print(f"  Backtest Results — {results['symbol']}")
    print("═" * width)
    rows = [
        ("Bars tested", results["bars_tested"]),
        ("Signals fired", results["signals_fired"]),
        ("Trades blocked (risk)", results["trades_blocked"]),
        ("Trades taken", results["trades_taken"]),
        ("Win rate", f"{results['win_rate_pct']:.1f}%"),
        ("Avg win", f"${results['avg_win_usd']:.2f}"),
        ("Avg loss", f"${results['avg_loss_usd']:.2f}"),
        ("Initial balance", f"${results['initial_balance']:,.2f}"),
        ("Final balance", f"${results['final_balance']:,.2f}"),
        ("Total return", f"{results['total_return_pct']:+.2f}%"),
        ("Trade CSV", results["trade_csv"]),
    ]
    for label, value in rows:
        print(f"  {label:<22} {value}")
    print("═" * width + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest the trading strategy")
    parser.add_argument("--config", default="config/settings.yaml")
    parser.add_argument("--symbol", default=None, help="Override symbol (e.g. BTC-PERP)")
    parser.add_argument("--limit", type=int, default=1000, help="Number of bars to fetch")
    parser.add_argument("--warmup", type=int, default=210, help="Bars to skip before trading")
    args = parser.parse_args()

    with open(args.config) as fh:
        config = yaml.safe_load(fh)

    feed = DataFeed(config)
    symbols = [args.symbol] if args.symbol else config.get("symbols", ["BTC-PERP"])

    Path("logs").mkdir(exist_ok=True)

    for sym in symbols:
        logger.info(f"Fetching {args.limit} bars for {sym}…")
        df = feed.fetch(sym, limit=args.limit)
        logger.info(f"Running backtest on {len(df)} bars…")
        results = run(config, sym, df, warmup=args.warmup)
        _print_results(results)


if __name__ == "__main__":
    main()
