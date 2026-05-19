"""
Telegram alert dispatcher.

Requires python-telegram-bot >= 20.x (async API).
Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env.
"""
import logging
from datetime import datetime

import aiohttp

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, LIVE_TRADING
from bot.state import Position, ClosedTrade

logger = logging.getLogger(__name__)

_MODE = "LIVE" if LIVE_TRADING else "PAPER"
_EMOJI_CALL = "📈"
_EMOJI_PUT = "📉"
_EMOJI_WIN = "✅"
_EMOJI_LOSS = "❌"
_EMOJI_REPORT = "📊"


class TelegramAlerter:
    def __init__(self):
        self._enabled = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)
        if not self._enabled:
            logger.warning("Telegram not configured — alerts disabled.")

    async def send(self, text: str):
        if not self._enabled:
            logger.info(f"[ALERT] {text}")
            return
        await self._post(text)

    async def send_entry(self, pos: Position):
        emoji = _EMOJI_CALL if pos.option_type == "call" else _EMOJI_PUT
        msg = (
            f"{emoji} *{_MODE} TRADE ENTRY*\n"
            f"Ticker: `{pos.ticker}`\n"
            f"Type: `{pos.option_type.upper()}`\n"
            f"Strike: `${pos.strike:.2f}`\n"
            f"Expiry: `{pos.expiry}` ({pos.dte_at_entry} DTE)\n"
            f"Contracts: `{pos.contracts}`\n"
            f"Entry: `${pos.entry_price:.4f}` × 100 = `${pos.entry_price*100:.2f}/contract`\n"
            f"Total Cost: `${pos.entry_cost:.2f}`\n"
            f"Signal Premium: `${pos.signal_premium:,.0f}`\n"
            f"SL: `${pos.stop_loss:.4f}` | TP1: `${pos.tp1:.4f}` | TP2: `${pos.tp2:.4f}`\n"
            f"Symbol: `{pos.option_symbol}`"
        )
        await self.send(msg)

    async def send_exit(self, trade: ClosedTrade):
        pnl_emoji = _EMOJI_WIN if trade.pnl >= 0 else _EMOJI_LOSS
        msg = (
            f"{pnl_emoji} *{_MODE} TRADE EXIT — {trade.exit_reason}*\n"
            f"Ticker: `{trade.ticker}` ({trade.option_type.upper()})\n"
            f"Contracts: `{trade.contracts}`\n"
            f"Entry: `${trade.entry_price:.4f}` → Exit: `${trade.exit_price:.4f}`\n"
            f"P&L: `${trade.pnl:+.2f}` (`{trade.pnl_pct:+.1%}`)\n"
            f"Exit Reason: `{trade.exit_reason}`"
        )
        await self.send(msg)

    async def send_daily_report(self, report_text: str):
        msg = f"{_EMOJI_REPORT} *DAILY REPORT — {datetime.utcnow().strftime('%Y-%m-%d')}*\n\n{report_text}"
        await self.send(msg)

    async def _post(self, text: str):
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as r:
                    if r.status != 200:
                        resp_text = await r.text()
                        logger.error(f"Telegram send failed {r.status}: {resp_text[:200]}")
        except Exception as exc:
            logger.error(f"Telegram error: {exc}")
