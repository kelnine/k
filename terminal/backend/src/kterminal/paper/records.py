"""Records emitted by the lab and paper accounts.

The simulator never writes to a database itself: it appends these immutable
records to an outbox that the lab flushes to a :class:`~kterminal.paper.store.LabStore`
(in memory for tests, PostgreSQL in production) once per bar batch. Every
record carries the ids needed to rebuild the full audit trail of a trade —
signal → decision → orders → fills → trade → ledger.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from kterminal.core.enums import Direction, OrderSide, OrderType
from kterminal.domain.signals import Signal
from kterminal.strategy_engine.model import Fault


@dataclass(frozen=True, slots=True)
class SignalRecord:
    id: UUID
    instance_id: str
    strategy_version: str  # config hash; the store maps it to strategy_versions.id
    definition_id: str
    received_at: datetime
    status: str  # ROUTED | IGNORED | INVALID
    signal: Signal | None = None
    instrument: str | None = None
    timeframe: str | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)
    reject_code: str | None = None
    reject_detail: str | None = None
    market_snapshot: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    id: UUID
    signal_id: UUID
    account_id: UUID
    instance_id: str  # whose signal it decides on (the account's own instance)
    account_config_version_id: UUID
    decided_at: datetime
    approved: bool
    primary_reason: str | None
    rule_results: list[dict[str, Any]]
    account_state: dict[str, Any]
    quote: dict[str, Any]
    requested_qty: Decimal | None = None
    approved_qty: Decimal | None = None
    risk_amount: Decimal | None = None
    risk_pct: Decimal | None = None


@dataclass(frozen=True, slots=True)
class OrderRecord:
    id: UUID
    client_order_id: str
    account_id: UUID
    instance_id: str
    purpose: str  # ENTRY | STOP_LOSS | TAKE_PROFIT | EXIT | FLATTEN
    venue: str
    instrument: str
    venue_symbol: str
    side: OrderSide
    order_type: OrderType
    qty: Decimal
    status: str
    created_at: datetime
    correlation_id: UUID
    trade_id: UUID | None = None
    signal_id: UUID | None = None
    decision_id: UUID | None = None
    requested_price: Decimal | None = None
    completed_at: datetime | None = None
    filled_qty: Decimal = Decimal(0)
    avg_fill_price: Decimal | None = None
    slippage: Decimal | None = None
    commission: Decimal = Decimal(0)
    reject_reason: str | None = None


@dataclass(frozen=True, slots=True)
class FillRecord:
    id: UUID
    order_id: UUID
    account_id: UUID
    ts: datetime
    qty: Decimal
    price: Decimal
    commission: Decimal
    liquidity: str
    spread_cost: Decimal  # account currency
    slippage: Decimal  # price units, adverse-positive


@dataclass(frozen=True, slots=True)
class TradeRecord:
    """Emitted when a trade opens (status OPEN) and again, complete, when it closes."""

    id: UUID
    account_id: UUID
    account_config_version_id: UUID
    instance_id: str
    strategy_version: str
    entry_signal_id: UUID
    mode: str
    instrument: str
    venue: str
    venue_symbol: str
    timeframe: str
    direction: Direction
    qty: Decimal
    entry_requested: Decimal
    entry_price: Decimal
    entry_time: datetime
    initial_stop: Decimal
    initial_target: Decimal | None
    current_stop: Decimal
    current_target: Decimal | None
    initial_risk: Decimal
    status: str  # OPEN | CLOSED
    correlation_id: UUID
    session: str | None = None
    exit_signal_id: UUID | None = None
    exit_price: Decimal | None = None
    exit_time: datetime | None = None
    exit_reason: str | None = None
    gross_pnl: Decimal | None = None
    commission: Decimal = Decimal(0)
    swap: Decimal = Decimal(0)
    funding: Decimal = Decimal(0)
    net_pnl: Decimal | None = None
    r_multiple: Decimal | None = None
    entry_slippage: Decimal | None = None
    exit_slippage: Decimal | None = None
    spread_cost: Decimal = Decimal(0)
    mae: Decimal | None = None
    mfe: Decimal | None = None


@dataclass(frozen=True, slots=True)
class TradeEventRecord:
    id: UUID
    trade_id: UUID
    ts: datetime
    kind: str  # STOP_MOVED | BREAKEVEN | TARGET_MOVED | NOTE
    old_value: Decimal | None = None
    new_value: Decimal | None = None
    signal_id: UUID | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LedgerRecord:
    id: UUID
    account_id: UUID
    ts: datetime
    kind: str  # DEPOSIT | REALIZED_PNL | COMMISSION | SWAP | FUNDING | ADJUSTMENT
    amount: Decimal
    balance_after: Decimal
    trade_id: UUID | None = None
    fill_id: UUID | None = None
    note: str = ""


@dataclass(frozen=True, slots=True)
class EquityRecord:
    account_id: UUID
    ts: datetime
    balance: Decimal
    equity: Decimal
    open_pnl: Decimal
    open_risk: Decimal
    daily_pnl: Decimal
    drawdown: Decimal
    high_water_mark: Decimal


@dataclass(frozen=True, slots=True)
class FaultRecord:
    instance_id: str
    fault: Fault
    recorded_at: datetime


Record = (
    SignalRecord
    | DecisionRecord
    | OrderRecord
    | FillRecord
    | TradeRecord
    | TradeEventRecord
    | LedgerRecord
    | EquityRecord
    | FaultRecord
)
