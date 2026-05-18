"""Paper trading execution engine with slippage simulation, SL/TP management,
trade history CSV, and dashboard JSON output."""
from __future__ import annotations

import csv
import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from risk.engine import TradeParams

logger = logging.getLogger(__name__)


@dataclass
class PaperTrade:
    id: str
    symbol: str
    direction: str          # "long" | "short"
    entry_price: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    size_usd: float         # margin deposited
    leverage: int
    entry_time: str
    exit_time: Optional[str] = None
    exit_price: Optional[float] = None
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    status: str = "open"    # "open" | "closed"
    exit_reason: Optional[str] = None  # "sl" | "tp1" | "tp2" | "manual"
    tp1_hit: bool = False   # internal flag — excluded from CSV


_CSV_FIELDS = [
    "id", "symbol", "direction", "entry_price", "stop_loss",
    "take_profit_1", "take_profit_2", "size_usd", "leverage",
    "entry_time", "exit_time", "exit_price", "pnl", "pnl_pct",
    "status", "exit_reason",
]


class PaperExecution:
    def __init__(self, config: dict) -> None:
        self.cfg = config
        pcfg = config.get("paper_trading", {})
        self.slippage_bps: int = int(pcfg.get("slippage_bps", 5))
        self.balance: float = float(pcfg.get("starting_balance", 10_000.0))
        self.initial_balance: float = self.balance

        lcfg = config.get("logging", {})
        self.csv_path = Path(lcfg.get("trade_history_csv", "logs/trade_history.csv"))
        self.json_path = Path(lcfg.get("dashboard_json", "logs/dashboard.json"))
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)

        self._trades: dict[str, PaperTrade] = {}     # all trades (open + closed)
        self._open: dict[str, PaperTrade] = {}        # open trades only
        self._init_csv()

    # ── Public API ────────────────────────────────────────────────────────────

    def open_trade(self, params: TradeParams) -> PaperTrade:
        fill = self._slippage(params.entry_price, params.direction, is_entry=True)
        trade = PaperTrade(
            id=str(uuid.uuid4())[:8],
            symbol=params.symbol,
            direction=params.direction,
            entry_price=fill,
            stop_loss=params.stop_loss,
            take_profit_1=params.take_profit_1,
            take_profit_2=params.take_profit_2,
            size_usd=params.size_usd,
            leverage=params.leverage,
            entry_time=datetime.utcnow().isoformat(),
        )
        self._trades[trade.id] = trade
        self._open[trade.id] = trade
        logger.info(
            f"[PAPER] OPEN {trade.direction.upper()} {trade.symbol} "
            f"@ {fill:.4f} | margin=${trade.size_usd:.2f} | {trade.leverage}x | id={trade.id}"
        )
        self._flush_dashboard()
        return trade

    def update_positions(
        self, symbol: str, current_price: float
    ) -> tuple[list[PaperTrade], list[PaperTrade]]:
        """Check open positions against current_price.

        Returns (closed_trades, tp1_events).
        tp1_events: trades that just hit TP1 (SL moved to breakeven; not fully closed).
        """
        closed: list[PaperTrade] = []
        tp1_events: list[PaperTrade] = []

        for tid, trade in list(self._open.items()):
            if trade.symbol != symbol:
                continue

            long = trade.direction == "long"
            hit_sl = current_price <= trade.stop_loss if long else current_price >= trade.stop_loss
            hit_tp1 = (
                (not trade.tp1_hit)
                and (current_price >= trade.take_profit_1 if long else current_price <= trade.take_profit_1)
            )
            hit_tp2 = (
                trade.tp1_hit
                and (current_price >= trade.take_profit_2 if long else current_price <= trade.take_profit_2)
            )

            if hit_sl:
                closed.append(self._close(trade, trade.stop_loss, "sl"))
            elif hit_tp2:
                closed.append(self._close(trade, trade.take_profit_2, "tp2"))
            elif hit_tp1:
                trade.tp1_hit = True
                # Trail SL to breakeven
                if long:
                    trade.stop_loss = max(trade.stop_loss, trade.entry_price)
                else:
                    trade.stop_loss = min(trade.stop_loss, trade.entry_price)
                logger.info(
                    f"[PAPER] TP1 hit {trade.id} @ {trade.take_profit_1:.4f} "
                    f"— SL moved to breakeven ({trade.entry_price:.4f})"
                )
                tp1_events.append(trade)

        return closed, tp1_events

    def close_all(self, symbol: str, current_price: float) -> list[PaperTrade]:
        """Force-close all open positions for a symbol (e.g. end-of-backtest)."""
        return [
            self._close(t, current_price, "manual")
            for t in list(self._open.values())
            if t.symbol == symbol
        ]

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _slippage(self, price: float, direction: str, is_entry: bool) -> float:
        slip = price * self.slippage_bps / 10_000
        # Adverse slippage: entry long pays more, entry short receives less; exits reversed.
        if (direction == "long" and is_entry) or (direction == "short" and not is_entry):
            return price + slip
        return price - slip

    def _close(self, trade: PaperTrade, exit_price: float, reason: str) -> PaperTrade:
        fill = self._slippage(exit_price, trade.direction, is_entry=False)
        notional = trade.size_usd * trade.leverage

        if trade.direction == "long":
            raw_pct = (fill - trade.entry_price) / trade.entry_price
        else:
            raw_pct = (trade.entry_price - fill) / trade.entry_price

        pnl = notional * raw_pct

        trade.exit_price = fill
        trade.exit_time = datetime.utcnow().isoformat()
        trade.exit_reason = reason
        trade.status = "closed"
        trade.pnl = round(pnl, 4)
        trade.pnl_pct = round(raw_pct * 100 * trade.leverage, 4)

        self.balance += pnl
        del self._open[trade.id]

        sign = "+" if pnl >= 0 else ""
        logger.info(
            f"[PAPER] CLOSE {trade.direction.upper()} {trade.symbol} "
            f"@ {fill:.4f} | PnL {sign}${pnl:.2f} ({sign}{trade.pnl_pct:.2f}%) "
            f"| reason={reason} | id={trade.id}"
        )
        self._append_csv(trade)
        self._flush_dashboard()
        return trade

    def _init_csv(self) -> None:
        if not self.csv_path.exists():
            with open(self.csv_path, "w", newline="") as fh:
                csv.DictWriter(fh, fieldnames=_CSV_FIELDS).writeheader()

    def _append_csv(self, trade: PaperTrade) -> None:
        row = {k: getattr(trade, k, None) for k in _CSV_FIELDS}
        with open(self.csv_path, "a", newline="") as fh:
            csv.DictWriter(fh, fieldnames=_CSV_FIELDS).writerow(row)

    def _flush_dashboard(self) -> None:
        closed = [t for t in self._trades.values() if t.status == "closed"]
        wins = [t for t in closed if t.pnl and t.pnl > 0]
        losses = [t for t in closed if t.pnl and t.pnl <= 0]

        dashboard = {
            "updated_at": datetime.utcnow().isoformat(),
            "balance": round(self.balance, 2),
            "initial_balance": self.initial_balance,
            "total_pnl": round(self.balance - self.initial_balance, 2),
            "total_pnl_pct": round((self.balance / self.initial_balance - 1) * 100, 2),
            "open_positions": len(self._open),
            "total_trades": len(closed),
            "win_rate_pct": round(len(wins) / len(closed) * 100, 1) if closed else 0.0,
            "avg_win_usd": round(sum(t.pnl for t in wins) / len(wins), 2) if wins else 0.0,
            "avg_loss_usd": round(sum(t.pnl for t in losses) / len(losses), 2) if losses else 0.0,
            "open_trades": [
                {k: getattr(t, k, None) for k in _CSV_FIELDS}
                for t in self._open.values()
            ],
        }
        with open(self.json_path, "w") as fh:
            json.dump(dashboard, fh, indent=2, default=str)
