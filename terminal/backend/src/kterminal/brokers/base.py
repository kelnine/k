"""The standard broker interface every venue adapter implements.

The application is never coupled to one broker or prop-firm platform: an MT5
bridge, TradeLocker, Tradovate, Rithmic, ProjectX, a crypto exchange or the
internal paper simulator are all ``BrokerAdapter`` implementations,
registered by name and chosen per account. Adapters speak *venue* symbols and
quantities; translation from canonical instruments happens through the
catalog's listings before an order reaches the adapter.

Only the execution layer calls adapters, and only with orders the risk engine
approved (Phases 5 and 9). LIVE environments are refused until Phase 10/11.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol, runtime_checkable

from kterminal.core.enums import Direction, OrderSide, OrderType, TradingMode
from kterminal.core.registry import Registry
from kterminal.domain.instruments import ContractType, Platform


class OrderStatus(StrEnum):
    PENDING_SUBMIT = "PENDING_SUBMIT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"


class TimeInForce(StrEnum):
    GTC = "GTC"
    DAY = "DAY"
    IOC = "IOC"
    FOK = "FOK"


@dataclass(frozen=True, slots=True)
class BrokerCapabilities:
    """What a venue adapter supports; the execution engine adapts to it."""

    platform: Platform
    modes: frozenset[TradingMode]
    contract_types: frozenset[ContractType]
    native_brackets: bool  # SL/TP attached to the entry order at the venue
    modify_orders: bool
    hedging: bool  # opposite positions on one symbol at once
    partial_closes: bool
    fractional_quantity: bool
    server_timezone: str = "UTC"
    notes: str = ""


@dataclass(frozen=True, slots=True)
class OrderRequest:
    client_order_id: str  # idempotency key at the venue
    venue_symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    price: Decimal | None = None  # limit / stop price
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None
    time_in_force: TimeInForce = TimeInForce.GTC
    reduce_only: bool = False
    tags: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class OrderAck:
    client_order_id: str
    broker_order_id: str | None
    status: OrderStatus
    received_at: datetime
    reject_reason: str | None = None


@dataclass(frozen=True, slots=True)
class BrokerOrder:
    client_order_id: str
    broker_order_id: str
    venue_symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    filled_quantity: Decimal
    status: OrderStatus
    price: Decimal | None = None
    average_fill_price: Decimal | None = None


@dataclass(frozen=True, slots=True)
class BrokerPosition:
    venue_symbol: str
    direction: Direction
    quantity: Decimal
    average_price: Decimal
    unrealized_pnl: Decimal
    position_id: str | None = None
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None


@dataclass(frozen=True, slots=True)
class BrokerAccount:
    account_ref: str  # masked in logs and UI
    currency: str
    balance: Decimal
    equity: Decimal
    margin_used: Decimal
    margin_available: Decimal
    as_of: datetime


@dataclass(frozen=True, slots=True)
class ExecutionStatus:
    connected: bool
    mode: TradingMode
    latency_ms: float | None = None
    last_heartbeat: datetime | None = None
    detail: str = ""


@runtime_checkable
class BrokerAdapter(Protocol):
    """Standard interface for every broker / prop-firm / exchange adapter."""

    name: str
    capabilities: BrokerCapabilities

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def get_account(self) -> BrokerAccount: ...

    async def get_positions(self) -> list[BrokerPosition]: ...

    async def get_orders(self, *, open_only: bool = True) -> list[BrokerOrder]: ...

    async def place_order(self, order: OrderRequest) -> OrderAck: ...

    async def modify_order(
        self,
        client_order_id: str,
        *,
        price: Decimal | None = None,
        stop_loss: Decimal | None = None,
        take_profit: Decimal | None = None,
        quantity: Decimal | None = None,
    ) -> OrderAck: ...

    async def cancel_order(self, client_order_id: str) -> OrderAck: ...

    async def close_position(
        self, venue_symbol: str, *, quantity: Decimal | None = None, position_id: str | None = None
    ) -> OrderAck: ...

    async def close_all(self) -> list[OrderAck]: ...

    async def get_execution_status(self) -> ExecutionStatus: ...


BROKERS: Registry[type[BrokerAdapter]] = Registry("broker adapter")
"""Adapter classes by name (``paper``, ``mt5_bridge``, ``tradelocker``, ``tradovate`` …)."""
