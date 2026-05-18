"""Telegram alert integration.

Sends formatted messages for: signal, entry, SL hit, TP hit, PnL update,
risk warning, and kill switch events.

Requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables
plus alerts.telegram.enabled = true in config/settings.yaml.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_TG_AVAILABLE = False
try:
    from telegram import Bot
    from telegram.error import TelegramError
    _TG_AVAILABLE = True
except ImportError:
    pass


class TelegramAlerts:
    def __init__(self, config: dict) -> None:
        tg_cfg = config.get("alerts", {}).get("telegram", {})
        self._enabled: bool = bool(tg_cfg.get("enabled", False))
        self._bot: Optional[object] = None
        self._chat_id: Optional[str] = None

        if self._enabled:
            self._init(tg_cfg)

    # ── Alert methods ─────────────────────────────────────────────────────────

    def signal(
        self,
        symbol: str,
        direction: str,
        entry: float,
        sl: float,
        tp1: float,
        tp2: float,
        reasons: list[str],
        confidence: float,
    ) -> None:
        icon = "🟢 LONG" if direction == "long" else "🔴 SHORT"
        rr = abs(tp2 - entry) / abs(entry - sl) if abs(entry - sl) > 0 else 0
        self._send(
            f"<b>📡 SIGNAL — {icon}</b>\n"
            f"Symbol: <code>{symbol}</code>\n"
            f"Entry:  <code>{entry:.5g}</code>\n"
            f"SL:     <code>{sl:.5g}</code>\n"
            f"TP1:    <code>{tp1:.5g}</code>\n"
            f"TP2:    <code>{tp2:.5g}</code>\n"
            f"R/R:    <code>{rr:.2f}</code>\n"
            f"Confidence: <code>{confidence*100:.0f}%</code>\n"
            f"<i>{' | '.join(reasons[:4])}</i>"
        )

    def entry(
        self,
        trade_id: str,
        symbol: str,
        direction: str,
        fill_price: float,
        size_usd: float,
        leverage: int,
    ) -> None:
        icon = "🟢" if direction == "long" else "🔴"
        self._send(
            f"{icon} <b>ENTRY — {direction.upper()}</b>\n"
            f"ID:     <code>{trade_id}</code>\n"
            f"Symbol: <code>{symbol}</code>\n"
            f"Fill:   <code>{fill_price:.5g}</code>\n"
            f"Margin: <code>${size_usd:.2f}</code> @ <code>{leverage}×</code>\n"
            f"Notional: <code>${size_usd * leverage:.2f}</code>"
        )

    def stop_loss(
        self, trade_id: str, symbol: str, direction: str, price: float, pnl: float
    ) -> None:
        sign = "+" if pnl >= 0 else ""
        self._send(
            f"🛑 <b>STOP LOSS HIT</b>\n"
            f"ID:    <code>{trade_id}</code>  {symbol}\n"
            f"Price: <code>{price:.5g}</code>\n"
            f"PnL:   <code>{sign}${pnl:.2f}</code>"
        )

    def take_profit(
        self, trade_id: str, symbol: str, level: int, price: float, pnl: Optional[float]
    ) -> None:
        pnl_str = f"+${pnl:.2f}" if pnl is not None else "open (SL → BE)"
        self._send(
            f"✅ <b>TP{level} HIT</b>\n"
            f"ID:    <code>{trade_id}</code>  {symbol}\n"
            f"Price: <code>{price:.5g}</code>\n"
            f"PnL:   <code>{pnl_str}</code>"
        )

    def pnl_update(
        self,
        balance: float,
        daily_pnl: float,
        open_positions: int,
        win_rate: float,
    ) -> None:
        icon = "📈" if daily_pnl >= 0 else "📉"
        sign = "+" if daily_pnl >= 0 else ""
        self._send(
            f"{icon} <b>PnL UPDATE</b>\n"
            f"Balance:   <code>${balance:,.2f}</code>\n"
            f"Daily PnL: <code>{sign}${daily_pnl:.2f}</code>\n"
            f"Open:      <code>{open_positions}</code>\n"
            f"Win rate:  <code>{win_rate:.1f}%</code>"
        )

    def risk_warning(self, message: str) -> None:
        self._send(f"⚠️ <b>RISK WARNING</b>\n{message}")

    def kill_switch_alert(self, reason: str) -> None:
        self._send(f"🚨 <b>KILL SWITCH ACTIVATED</b>\nReason: {reason}")

    # ── Private ───────────────────────────────────────────────────────────────

    def _init(self, tg_cfg: dict) -> None:
        if not _TG_AVAILABLE:
            logger.warning(
                "python-telegram-bot not installed — Telegram alerts suppressed. "
                "Install: pip install python-telegram-bot"
            )
            self._enabled = False
            return

        token = os.environ.get(tg_cfg.get("token_env", "TELEGRAM_BOT_TOKEN"), "")
        chat_id = os.environ.get(tg_cfg.get("chat_id_env", "TELEGRAM_CHAT_ID"), "")

        if not token or not chat_id:
            logger.warning(
                "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set — alerts suppressed"
            )
            self._enabled = False
            return

        self._bot = Bot(token=token)
        self._chat_id = chat_id
        logger.info("Telegram alerts initialised")

    def _send(self, text: str) -> None:
        if not self._enabled or self._bot is None:
            logger.info(f"[ALERT] {text[:120].replace(chr(10), ' ')}")
            return

        async def _do_send() -> None:
            await self._bot.send_message(  # type: ignore[union-attr]
                chat_id=self._chat_id,
                text=text,
                parse_mode="HTML",
            )

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(_do_send())
            else:
                loop.run_until_complete(_do_send())
        except Exception as exc:
            logger.error(f"Telegram send failed: {exc}")
