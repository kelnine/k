"""Risk management engine.

Enforces: max daily loss, max trade size, max leverage, max open positions,
mandatory stop loss, kill switch, and no-trade mode.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

logger = logging.getLogger(__name__)


class RiskError(Exception):
    """Raised when a trade violates a risk rule."""


@dataclass
class TradeParams:
    symbol: str
    direction: str
    entry_price: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    size_usd: float         # USD notional before leverage
    leverage: int
    signal: object          # back-ref to the originating Signal


class RiskEngine:
    def __init__(self, config: dict) -> None:
        self.cfg = config.get("risk", {})
        self.account_balance: float = (
            config.get("paper_trading", {}).get("starting_balance", 10_000.0)
        )

        self._open_positions: int = 0
        self._daily_pnl: float = 0.0
        self._daily_date: date = date.today()
        self._kill_switch: bool = bool(self.cfg.get("kill_switch", False))
        self._no_trade: bool = bool(self.cfg.get("no_trade_mode", False))

    # ── Public properties ─────────────────────────────────────────────────────

    @property
    def kill_switch(self) -> bool:
        return self._kill_switch

    @property
    def no_trade_mode(self) -> bool:
        return self._no_trade

    @property
    def open_positions(self) -> int:
        return self._open_positions

    @property
    def daily_pnl(self) -> float:
        self._maybe_reset_daily()
        return self._daily_pnl

    # ── State mutators ────────────────────────────────────────────────────────

    def activate_kill_switch(self, reason: str = "") -> None:
        if not self._kill_switch:
            logger.critical(f"KILL SWITCH ACTIVATED — {reason or 'manual'}")
        self._kill_switch = True

    def deactivate_kill_switch(self) -> None:
        logger.warning("Kill switch deactivated — trading resumed")
        self._kill_switch = False

    def set_no_trade_mode(self, active: bool) -> None:
        self._no_trade = active
        logger.info(f"No-trade mode {'enabled' if active else 'disabled'}")

    def update_balance(self, balance: float) -> None:
        self.account_balance = balance

    def open_position(self) -> None:
        self._open_positions += 1

    def close_position(self) -> None:
        self._open_positions = max(0, self._open_positions - 1)

    def record_pnl(self, pnl: float) -> None:
        self._maybe_reset_daily()
        self._daily_pnl += pnl
        self.account_balance += pnl

        max_daily_loss = self.cfg.get("max_daily_loss_pct", 3.0) / 100 * self.account_balance
        if self._daily_pnl < -abs(max_daily_loss):
            self.activate_kill_switch(
                f"daily loss limit breached: {self._daily_pnl:.2f} vs limit -{abs(max_daily_loss):.2f}"
            )

    # ── Core validation ───────────────────────────────────────────────────────

    def validate(self, signal) -> TradeParams:  # signal: Signal
        """Validate signal against all risk rules; return TradeParams or raise RiskError."""
        self._maybe_reset_daily()

        if self._kill_switch:
            raise RiskError("Kill switch is active — no new trades")

        if self._no_trade:
            raise RiskError("No-trade mode is active")

        max_pos = self.cfg.get("max_open_positions", 3)
        if self._open_positions >= max_pos:
            raise RiskError(
                f"Max open positions reached ({self._open_positions}/{max_pos})"
            )

        # Approaching daily loss limit (warn at 80 %)
        max_daily_loss = self.cfg.get("max_daily_loss_pct", 3.0) / 100 * self.account_balance
        if self._daily_pnl < -abs(max_daily_loss) * 0.8:
            raise RiskError(
                f"Approaching daily loss limit: {self._daily_pnl:.2f} "
                f"(limit=${-abs(max_daily_loss):.2f})"
            )

        # Stop loss validation
        if self.cfg.get("stop_loss_required", True):
            if signal.stop_loss is None:
                raise RiskError("Stop loss is required but missing")
            if signal.direction == "long" and signal.stop_loss >= signal.entry_price:
                raise RiskError(
                    f"Long SL ({signal.stop_loss:.4f}) must be below entry ({signal.entry_price:.4f})"
                )
            if signal.direction == "short" and signal.stop_loss <= signal.entry_price:
                raise RiskError(
                    f"Short SL ({signal.stop_loss:.4f}) must be above entry ({signal.entry_price:.4f})"
                )

        # Position sizing: risk a fixed % of account per trade
        risk_dist_pct = abs(signal.entry_price - signal.stop_loss) / signal.entry_price
        if risk_dist_pct == 0:
            raise RiskError("Entry and stop loss are identical")

        risk_pct_per_trade = self.cfg.get("max_trade_size_pct", 2.0) / 100
        risk_usd = self.account_balance * risk_pct_per_trade

        # Notional size so that if SL is hit, loss == risk_usd
        notional_usd = risk_usd / risk_dist_pct

        # Choose leverage conservatively (never exceed max_leverage)
        max_lev = self.cfg.get("max_leverage", 10)
        ideal_lev = max(1, int(1.0 / (risk_dist_pct * 2)))
        leverage = min(max_lev, ideal_lev)

        # Size in USD deposited as margin
        margin_usd = notional_usd / leverage

        logger.info(
            f"Risk OK — {signal.symbol} {signal.direction} | "
            f"notional=${notional_usd:.2f} | margin=${margin_usd:.2f} | "
            f"lev={leverage}x | risk_dist={risk_dist_pct*100:.2f}%"
        )

        return TradeParams(
            symbol=signal.symbol,
            direction=signal.direction,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit_1=signal.take_profit_1,
            take_profit_2=signal.take_profit_2,
            size_usd=margin_usd,
            leverage=leverage,
            signal=signal,
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _maybe_reset_daily(self) -> None:
        today = date.today()
        if today != self._daily_date:
            self._daily_pnl = 0.0
            self._daily_date = today
            logger.info("Daily PnL counter reset")

    def status(self) -> dict:
        return {
            "kill_switch": self._kill_switch,
            "no_trade_mode": self._no_trade,
            "open_positions": self._open_positions,
            "daily_pnl": round(self._daily_pnl, 2),
            "account_balance": round(self.account_balance, 2),
        }
