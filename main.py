"""
Options Flow Paper-Trading Bot
──────────────────────────────
Watches unusual options flow on SPY, QQQ, NVDA, TSLA, AMD, AAPL, META, MSFT.
Places paper trades via Tradier Sandbox or Alpaca Paper API.
Sends Telegram alerts on entry, exit, and daily report.

Run:
    python main.py

Requires:
    pip install -r requirements.txt
    cp .env.example .env  # then fill in your API keys
"""
import asyncio
import logging
import signal
import sys
from datetime import datetime, time, timedelta
from typing import NoReturn

import pytz

from config import (
    LIVE_TRADING,
    SCAN_INTERVAL_SECONDS,
    POSITION_CHECK_INTERVAL_SECONDS,
    MAX_TRADES_PER_DAY,
    NO_TRADE_MINUTES_AFTER_OPEN,
)
from bot.flow_scanner import FlowScanner
from bot.signal_filter import SignalFilter
from bot.trend_confirm import TrendConfirmer
from bot.paper_trader import PaperTrader
from bot.alerts import TelegramAlerter
from bot.reporter import DailyReporter
from bot.state import TradingState

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("bot.log"),
    ],
)
logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")
MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)
NO_TRADE_UNTIL = time(9, 30 + NO_TRADE_MINUTES_AFTER_OPEN)  # 9:35 ET


def _now_et() -> datetime:
    return datetime.now(ET)


def _is_market_open(now_et: datetime) -> bool:
    t = now_et.time()
    # Monday–Friday only
    return now_et.weekday() < 5 and MARKET_OPEN <= t < MARKET_CLOSE


def _in_no_trade_window(now_et: datetime) -> bool:
    t = now_et.time()
    return MARKET_OPEN <= t < NO_TRADE_UNTIL


def _seconds_until_market_open(now_et: datetime) -> float:
    """Seconds until next market open. Returns 0 if market is already open."""
    t = now_et.time()
    if now_et.weekday() >= 5:
        # Weekend: sleep until Monday 09:30
        days_ahead = 7 - now_et.weekday()
        next_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0) + timedelta(days=days_ahead)
    elif t < MARKET_OPEN:
        next_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    elif t >= MARKET_CLOSE:
        if now_et.weekday() == 4:  # Friday
            next_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0) + timedelta(days=3)
        else:
            next_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0) + timedelta(days=1)
    else:
        return 0.0
    return (next_open - now_et).total_seconds()


async def run_bot():
    if LIVE_TRADING:
        # config.py already demanded manual confirmation; double-check here
        logger.critical("LIVE_TRADING=true — this bot supports paper trading only. Aborting.")
        sys.exit(1)

    logger.info("=" * 60)
    logger.info("Options Flow Paper-Trading Bot — PAPER MODE")
    logger.info("=" * 60)

    scanner = FlowScanner()
    sig_filter = SignalFilter()
    trend = TrendConfirmer()
    trader = PaperTrader()
    alerter = TelegramAlerter()
    reporter = DailyReporter()
    state = TradingState()

    logger.info(f"Paper balance: ${state.balance:,.2f}")
    logger.info(f"Open positions: {len(state.positions)}")

    await alerter.send(
        f"Bot started — PAPER MODE\nBalance: ${state.balance:,.2f} | "
        f"Open positions: {len(state.positions)}"
    )

    last_position_check = 0.0
    last_report_date = None

    while True:
        now = _now_et()
        today = now.date()

        # ── Reset daily counters at midnight ──────────────────────────────────
        if last_report_date != today:
            state.trades_today = 0
            state.seen_flow_ids.clear()
            state.report_sent_today = False

        # ── Pre-market / after-hours: sleep until open ────────────────────────
        if not _is_market_open(now):
            # Send daily report once after market close
            if (
                now.time() >= MARKET_CLOSE
                and not state.report_sent_today
                and last_report_date != today
            ):
                # EOD close any lingering positions
                eod_closed = await trader.close_all_eod(state)
                for t in eod_closed:
                    await alerter.send_exit(t)

                report_text = reporter.generate(state)
                await alerter.send_daily_report(report_text)
                logger.info("Daily report sent.")
                state.report_sent_today = True
                last_report_date = today

            wait = _seconds_until_market_open(now)
            sleep_secs = min(wait, 300)  # wake up every 5 min max to recheck
            logger.info(
                f"Market closed. Next open in ~{wait/60:.0f} min. "
                f"Sleeping {sleep_secs:.0f}s."
            )
            await asyncio.sleep(sleep_secs)
            continue

        # ── Check open positions for SL/TP ────────────────────────────────────
        loop_time = asyncio.get_event_loop().time()
        if loop_time - last_position_check >= POSITION_CHECK_INTERVAL_SECONDS:
            exits = await trader.check_positions(state)
            for closed_trade in exits:
                await alerter.send_exit(closed_trade)
            last_position_check = loop_time

        # ── Scan for new signals ───────────────────────────────────────────────
        if _in_no_trade_window(now):
            logger.info("In no-trade window (first 5 min after open). Scanning but not trading.")
            trade_allowed = False
        elif state.trades_today >= MAX_TRADES_PER_DAY:
            logger.info(f"Max trades/day ({MAX_TRADES_PER_DAY}) reached. Monitoring only.")
            trade_allowed = False
        else:
            trade_allowed = True

        try:
            alerts = await scanner.get_flow()
        except Exception as exc:
            logger.error(f"Flow scan error: {exc}", exc_info=True)
            await asyncio.sleep(SCAN_INTERVAL_SECONDS)
            continue

        filtered = sig_filter.filter(alerts, state.seen_flow_ids, state.recent_signals)

        for signal in filtered:
            state.seen_flow_ids.add(signal["id"])

            if not trade_allowed:
                logger.info(f"Signal detected but trading not allowed: {signal['ticker']} {signal['option_type']}")
                continue

            try:
                confirmed = await trend.confirm(signal)
            except Exception as exc:
                logger.warning(f"Trend confirm error for {signal['ticker']}: {exc}. Allowing.")
                confirmed = True

            if not confirmed:
                continue

            position = await trader.enter_trade(signal, state)
            if position:
                await alerter.send_entry(position)

        await asyncio.sleep(SCAN_INTERVAL_SECONDS)


def _handle_shutdown(signum, frame):
    logger.info(f"Received signal {signum}. Shutting down gracefully.")
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, _handle_shutdown)
    signal.signal(signal.SIGTERM, _handle_shutdown)

    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt. Exiting.")
    except SystemExit:
        pass
    except Exception as exc:
        logger.critical(f"Unhandled exception: {exc}", exc_info=True)
        sys.exit(1)
