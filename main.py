"""Trading bot entry point.

Usage:
    python main.py                    # uses config/settings.yaml
    python main.py --config my.yaml   # custom config path
"""
from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from pathlib import Path

import yaml
from dotenv import load_dotenv

from alerts.telegram import TelegramAlerts
from data.feed import DataFeed
from execution.hyperliquid import HyperliquidAdapter
from execution.paper import PaperExecution
from risk.engine import RiskEngine, RiskError
from strategy.engine import StrategyEngine

load_dotenv()


# ── Logging setup ─────────────────────────────────────────────────────────────

def setup_logging(config: dict) -> None:
    lcfg = config.get("logging", {})
    level = getattr(logging, lcfg.get("level", "INFO").upper(), logging.INFO)
    fmt = "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s"

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]

    log_file = lcfg.get("file", "logs/bot.log")
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    handlers.append(logging.FileHandler(log_file))

    logging.basicConfig(level=level, format=fmt, handlers=handlers, force=True)


def load_config(path: str) -> dict:
    with open(path) as fh:
        return yaml.safe_load(fh)


# ── Bot ───────────────────────────────────────────────────────────────────────

class TradingBot:
    _TIMEFRAME_SECONDS: dict[str, int] = {
        "1m": 60, "3m": 180, "5m": 300, "15m": 900,
        "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400,
    }

    def __init__(self, config: dict) -> None:
        self.config = config
        self.mode: str = config.get("mode", "paper")
        self.symbols: list[str] = config.get("symbols", ["BTC-PERP"])
        self._running = False

        self.strategy = StrategyEngine(config)
        self.risk = RiskEngine(config)
        self.feed = DataFeed(config)
        self.paper = PaperExecution(config)
        self.alerts = TelegramAlerts(config)
        self.live = HyperliquidAdapter(config)

        if self.live.is_enabled and self.mode != "live":
            raise RuntimeError(
                "Hyperliquid is enabled but mode is not 'live'. "
                "Set mode: live in config to proceed."
            )

        self.log = logging.getLogger("bot")
        self.log.info(
            f"TradingBot ready — mode={self.mode} | symbols={self.symbols} | "
            f"tf={config.get('timeframe', '15m')}"
        )

    def run(self) -> None:
        signal.signal(signal.SIGINT, self._on_signal)
        signal.signal(signal.SIGTERM, self._on_signal)

        tf = config.get("timeframe", "15m") if hasattr(self, "config") else "15m"
        poll_secs = self._TIMEFRAME_SECONDS.get(self.config.get("timeframe", "15m"), 900)

        self._running = True
        self.log.info(f"Bot started — polling every {poll_secs}s")
        self.alerts.pnl_update(self.paper.balance, 0.0, 0, 0.0)

        while self._running:
            for symbol in self.symbols:
                if not self._running:
                    break
                try:
                    self._process(symbol)
                except Exception as exc:
                    self.log.error(f"Unhandled error processing {symbol}: {exc}", exc_info=True)

            if not self._running:
                break

            rs = self.risk.status()
            self.log.info(
                f"Cycle done | balance=${self.paper.balance:.2f} | "
                f"open={rs['open_positions']} | daily_pnl=${rs['daily_pnl']:.2f} | "
                f"sleeping {poll_secs}s"
            )

            # Interruptible sleep
            for _ in range(poll_secs):
                if not self._running:
                    break
                time.sleep(1)

        self.log.info("Bot stopped")

    # ── Per-symbol cycle ──────────────────────────────────────────────────────

    def _process(self, symbol: str) -> None:
        df = self.feed.fetch(symbol)
        current_price = float(df["close"].iloc[-1])

        # Update open positions — returns (closed, tp1_events)
        closed, tp1_events = self.paper.update_positions(symbol, current_price)

        for trade in tp1_events:
            self.alerts.take_profit(trade.id, symbol, 1, trade.take_profit_1, None)

        for trade in closed:
            self.risk.close_position()
            self.risk.record_pnl(trade.pnl or 0.0)

            if trade.exit_reason == "sl":
                self.alerts.stop_loss(
                    trade.id, symbol, trade.direction, trade.exit_price, trade.pnl
                )
            elif trade.exit_reason in ("tp2", "manual"):
                lvl = 2 if trade.exit_reason == "tp2" else 0
                self.alerts.take_profit(
                    trade.id, symbol, lvl, trade.exit_price, trade.pnl
                )

        # Kill-switch check (may have triggered inside record_pnl)
        if self.risk.kill_switch:
            self.log.warning(f"{symbol}: kill switch active — skipping signal")
            return

        # Generate signal
        sig = self.strategy.analyze(symbol, df)
        if sig is None:
            self.log.debug(f"{symbol}: no signal @ {current_price:.4f}")
            return

        self.log.info(
            f"{symbol}: {sig.direction.upper()} signal | "
            f"score={sig.score} | conf={sig.confidence:.0%} | "
            f"entry={sig.entry_price:.4f} SL={sig.stop_loss:.4f} "
            f"TP1={sig.take_profit_1:.4f} TP2={sig.take_profit_2:.4f}"
        )
        self.alerts.signal(
            sig.symbol, sig.direction,
            sig.entry_price, sig.stop_loss,
            sig.take_profit_1, sig.take_profit_2,
            sig.reasons, sig.confidence,
        )

        # Risk check
        try:
            params = self.risk.validate(sig)
        except RiskError as exc:
            self.log.info(f"{symbol}: blocked by risk — {exc}")
            self.alerts.risk_warning(f"{symbol}: {exc}")
            return

        # Execute
        if self.mode == "paper":
            trade = self.paper.open_trade(params)
            self.risk.open_position()
            self.alerts.entry(
                trade.id, trade.symbol, trade.direction,
                trade.entry_price, trade.size_usd, trade.leverage,
            )
        elif self.mode == "live" and self.live.is_enabled:
            result = self.live.place_order(params)
            self.log.info(f"[LIVE] Order result: {result}")
        else:
            self.log.warning("Live mode requested but Hyperliquid adapter is disabled")

    # ── Shutdown ──────────────────────────────────────────────────────────────

    def _on_signal(self, sig: int, frame: object) -> None:
        self.log.info(f"Received signal {sig} — shutting down")
        self._running = False


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Perpetual futures trading bot")
    parser.add_argument(
        "--config", default="config/settings.yaml", help="Path to YAML config file"
    )
    args = parser.parse_args()

    global config
    config = load_config(args.config)
    setup_logging(config)

    bot = TradingBot(config)
    bot.run()


if __name__ == "__main__":
    main()
