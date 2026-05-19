"""
Manages all mutable bot state: balance, positions, trade history, daily counters.
Persists to JSON files so restarts don't wipe the paper account.
"""
import json
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from typing import Optional

from config import STARTING_BALANCE

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
BALANCE_FILE = os.path.join(DATA_DIR, "balance.json")
POSITIONS_FILE = os.path.join(DATA_DIR, "positions.json")
TRADES_FILE = os.path.join(DATA_DIR, "trades.json")


@dataclass
class Position:
    trade_id: str
    ticker: str
    option_symbol: str
    option_type: str          # "call" or "put"
    strike: float
    expiry: str               # "YYYY-MM-DD"
    dte_at_entry: int
    contracts: int
    entry_price: float        # per-contract price
    entry_cost: float         # total cost (contracts * entry_price * 100)
    entry_time: str           # ISO timestamp
    stop_loss: float          # absolute price level
    tp1: float
    tp2: float
    tp1_hit: bool = False
    trail_stop: Optional[float] = None
    broker_order_id: Optional[str] = None
    flow_side: str = ""       # "call" or "put" (signal direction)
    signal_premium: float = 0.0


@dataclass
class ClosedTrade:
    trade_id: str
    ticker: str
    option_symbol: str
    option_type: str
    contracts: int
    entry_price: float
    exit_price: float
    entry_cost: float
    exit_proceeds: float
    pnl: float
    pnl_pct: float
    exit_reason: str          # "SL", "TP1", "TP2", "TRAIL", "EOD"
    entry_time: str
    exit_time: str


class TradingState:
    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        self.balance = self._load_balance()
        self.positions: dict[str, Position] = self._load_positions()
        self.trades: list[ClosedTrade] = self._load_trades()

        today = date.today().isoformat()
        self.trades_today: int = sum(
            1 for t in self.trades if t.entry_time.startswith(today)
        )
        self.seen_flow_ids: set[str] = set()
        self.recent_signals: list[dict] = []   # for repeat-flow detection
        self.report_sent_today: bool = False

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load_balance(self) -> float:
        if os.path.exists(BALANCE_FILE):
            try:
                with open(BALANCE_FILE) as f:
                    data = json.load(f)
                    return float(data.get("balance", STARTING_BALANCE))
            except Exception:
                pass
        return STARTING_BALANCE

    def _save_balance(self):
        with open(BALANCE_FILE, "w") as f:
            json.dump({"balance": self.balance}, f)

    def _load_positions(self) -> dict:
        if os.path.exists(POSITIONS_FILE):
            try:
                with open(POSITIONS_FILE) as f:
                    raw = json.load(f)
                    return {k: Position(**v) for k, v in raw.items()}
            except Exception:
                pass
        return {}

    def _save_positions(self):
        with open(POSITIONS_FILE, "w") as f:
            json.dump({k: asdict(v) for k, v in self.positions.items()}, f, indent=2)

    def _load_trades(self) -> list:
        if os.path.exists(TRADES_FILE):
            try:
                with open(TRADES_FILE) as f:
                    raw = json.load(f)
                    return [ClosedTrade(**t) for t in raw]
            except Exception:
                pass
        return []

    def _save_trades(self):
        with open(TRADES_FILE, "w") as f:
            json.dump([asdict(t) for t in self.trades], f, indent=2, default=str)

    # ── State Mutations ───────────────────────────────────────────────────────

    def open_position(self, position: Position):
        self.balance -= position.entry_cost
        self.positions[position.trade_id] = position
        self.trades_today += 1
        self._save_balance()
        self._save_positions()
        logger.info(
            f"Opened {position.option_type.upper()} on {position.ticker} | "
            f"Cost: ${position.entry_cost:.2f} | Balance: ${self.balance:.2f}"
        )

    def close_position(self, trade_id: str, exit_price: float, reason: str) -> Optional[ClosedTrade]:
        pos = self.positions.pop(trade_id, None)
        if not pos:
            return None

        exit_proceeds = pos.contracts * exit_price * 100
        pnl = exit_proceeds - pos.entry_cost
        pnl_pct = pnl / pos.entry_cost

        self.balance += exit_proceeds

        closed = ClosedTrade(
            trade_id=trade_id,
            ticker=pos.ticker,
            option_symbol=pos.option_symbol,
            option_type=pos.option_type,
            contracts=pos.contracts,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            entry_cost=pos.entry_cost,
            exit_proceeds=exit_proceeds,
            pnl=pnl,
            pnl_pct=pnl_pct,
            exit_reason=reason,
            entry_time=pos.entry_time,
            exit_time=datetime.utcnow().isoformat(),
        )
        self.trades.append(closed)
        self._save_balance()
        self._save_positions()
        self._save_trades()
        logger.info(
            f"Closed {pos.ticker} | Reason: {reason} | P&L: ${pnl:+.2f} ({pnl_pct:+.1%})"
        )
        return closed

    def update_position_tp1_hit(self, trade_id: str):
        if trade_id in self.positions:
            self.positions[trade_id].tp1_hit = True
            self._save_positions()

    def update_trail_stop(self, trade_id: str, new_stop: float):
        if trade_id in self.positions:
            self.positions[trade_id].trail_stop = new_stop
            self._save_positions()

    def today_closed_trades(self) -> list[ClosedTrade]:
        today = date.today().isoformat()
        return [t for t in self.trades if t.entry_time.startswith(today)]

    def all_closed_trades(self) -> list[ClosedTrade]:
        return self.trades
