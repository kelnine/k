"""Bridge to the Liquid paper-trading account.

The Python bot cannot call Liquid directly (execution there goes through a
per-trade confirmation flow), so the wiring is ticket-based:

1. The engine appends an order ticket to `tickets.jsonl` for every entry
   and exit it would take, sized by the same risk engine as the simulator.
2. In a Claude session connected to the Liquid MCP server (paper mode ON),
   Claude reads unprocessed tickets and turns each into a `suggest_trade`
   confirmation card.
3. You press Confirm — a suggestion is never an execution. The stop-loss
   from the ticket rides along, so the hard 1% rule survives the bridge.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime

from .config import Instrument
from .risk import PositionPlan
from .strategies.base import LONG

#: bot symbol -> Liquid market symbol
LIQUID_SYMBOLS = {
    "SPX": "S&P500",
    "NDX": "NASDAQ100",
    "BTC": "BTC",
    "GOLD": "GOLD",
    "OIL": "WTIOIL",
}


@dataclass(frozen=True)
class OrderTicket:
    at: str                 # ISO timestamp the signal fired
    action: str             # "open" | "close"
    symbol: str             # bot symbol
    liquid_asset: str       # Liquid market symbol
    side: str               # "long" | "short"
    notional_usd: float     # position size in USD (leverage 1x)
    mark_price: float       # price the bot sized against
    stop_loss: float | None
    reason: str


def entry_ticket(
    instrument: Instrument,
    direction: int,
    price: float,
    plan: PositionPlan,
    at: datetime,
    reason: str,
) -> OrderTicket:
    return OrderTicket(
        at=at.isoformat(),
        action="open",
        symbol=instrument.symbol,
        liquid_asset=LIQUID_SYMBOLS[instrument.symbol],
        side="long" if direction == LONG else "short",
        notional_usd=round(plan.quantity * price, 2),
        mark_price=price,
        stop_loss=round(plan.stop_price, 2),
        reason=reason,
    )


def close_ticket(
    instrument: Instrument, direction: int, price: float, at: datetime, reason: str
) -> OrderTicket:
    return OrderTicket(
        at=at.isoformat(),
        action="close",
        symbol=instrument.symbol,
        liquid_asset=LIQUID_SYMBOLS[instrument.symbol],
        side="long" if direction == LONG else "short",
        notional_usd=0.0,   # close the whole position
        mark_price=price,
        stop_loss=None,
        reason=reason,
    )


def append_ticket(ticket: OrderTicket, path: str) -> None:
    with open(path, "a") as f:
        f.write(json.dumps(asdict(ticket)) + "\n")


def read_tickets(path: str) -> list[OrderTicket]:
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [OrderTicket(**json.loads(line)) for line in f if line.strip()]
