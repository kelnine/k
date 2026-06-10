"""Paper broker: holds positions, enforces stops, marks to market, and keeps
the trade journal. This is the only component that touches money, which is
why it is simulated — wiring a real broker means re-implementing this
interface, nothing else changes.
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass, field
from datetime import datetime

from .strategies.base import LONG

JOURNAL_FIELDS = [
    "opened_at",
    "closed_at",
    "symbol",
    "direction",
    "quantity",
    "entry_price",
    "exit_price",
    "stop_price",
    "pnl",
    "equity_after",
    "entry_reason",
    "exit_reason",
]


@dataclass
class Position:
    symbol: str
    direction: int            # LONG or SHORT
    quantity: float
    entry_price: float
    stop_price: float
    opened_at: datetime
    entry_reason: str = ""


@dataclass
class ClosedTrade:
    symbol: str
    direction: int
    quantity: float
    entry_price: float
    exit_price: float
    stop_price: float
    pnl: float
    opened_at: datetime
    closed_at: datetime
    entry_reason: str
    exit_reason: str


@dataclass
class PaperBroker:
    equity: float
    journal_path: str | None = None
    positions: dict[str, Position] = field(default_factory=dict)
    closed_trades: list[ClosedTrade] = field(default_factory=list)

    def open_position(
        self,
        symbol: str,
        direction: int,
        quantity: float,
        price: float,
        stop_price: float,
        at: datetime,
        reason: str = "",
    ) -> Position:
        if symbol in self.positions:
            raise ValueError(f"already holding {symbol}")
        pos = Position(symbol, direction, quantity, price, stop_price, at, reason)
        self.positions[symbol] = pos
        return pos

    def close_position(
        self, symbol: str, price: float, at: datetime, reason: str = ""
    ) -> ClosedTrade:
        pos = self.positions.pop(symbol)
        pnl = (price - pos.entry_price) * pos.quantity * pos.direction
        self.equity += pnl
        trade = ClosedTrade(
            symbol=pos.symbol,
            direction=pos.direction,
            quantity=pos.quantity,
            entry_price=pos.entry_price,
            exit_price=price,
            stop_price=pos.stop_price,
            pnl=pnl,
            opened_at=pos.opened_at,
            closed_at=at,
            entry_reason=pos.entry_reason,
            exit_reason=reason,
        )
        self.closed_trades.append(trade)
        self._journal(trade)
        return trade

    def check_stop(self, symbol: str, bar_high: float, bar_low: float) -> float | None:
        """Return the stop fill price if this bar touched the stop, else None.
        The stop is hard: it fills at the stop price (or the bar's open gap
        if price gapped through)."""
        pos = self.positions.get(symbol)
        if pos is None:
            return None
        if pos.direction == LONG and bar_low <= pos.stop_price:
            return min(pos.stop_price, bar_high)  # gap-through fills worse
        if pos.direction != LONG and bar_high >= pos.stop_price:
            return max(pos.stop_price, bar_low)
        return None

    def mark_to_market(self, prices: dict[str, float]) -> float:
        unrealised = sum(
            (prices[s] - p.entry_price) * p.quantity * p.direction
            for s, p in self.positions.items()
            if s in prices
        )
        return self.equity + unrealised

    def _journal(self, t: ClosedTrade) -> None:
        if not self.journal_path:
            return
        new_file = not os.path.exists(self.journal_path)
        with open(self.journal_path, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=JOURNAL_FIELDS)
            if new_file:
                writer.writeheader()
            writer.writerow(
                {
                    "opened_at": t.opened_at.isoformat(),
                    "closed_at": t.closed_at.isoformat(),
                    "symbol": t.symbol,
                    "direction": "long" if t.direction == LONG else "short",
                    "quantity": f"{t.quantity:.6f}",
                    "entry_price": f"{t.entry_price:.4f}",
                    "exit_price": f"{t.exit_price:.4f}",
                    "stop_price": f"{t.stop_price:.4f}",
                    "pnl": f"{t.pnl:.2f}",
                    "equity_after": f"{self.equity:.2f}",
                    "entry_reason": t.entry_reason,
                    "exit_reason": t.exit_reason,
                }
            )
