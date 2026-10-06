"""Shared kernel: the vocabulary and primitives every module uses.

Enums, identifiers, the injected clock, the exception hierarchy, the
in-process event bus and the plug-in registry. ``kterminal.core`` imports
nothing else from ``kterminal`` (enforced by import-linter), so any module can
depend on it without creating cycles.
"""

from kterminal.core.clock import Clock, SimulatedClock, SystemClock, ensure_utc
from kterminal.core.enums import (
    Direction,
    OrderSide,
    SignalAction,
    SignalSource,
    StrategyKind,
    StrategyStatus,
    TradingMode,
)
from kterminal.core.events import DomainEvent, EventBus, InMemoryEventBus, Subscription
from kterminal.core.ids import new_correlation_id, uuid7, uuid7_time
from kterminal.core.registry import Registry

__all__ = [
    "Clock",
    "Direction",
    "DomainEvent",
    "EventBus",
    "InMemoryEventBus",
    "OrderSide",
    "Registry",
    "SignalAction",
    "SignalSource",
    "SimulatedClock",
    "StrategyKind",
    "StrategyStatus",
    "Subscription",
    "SystemClock",
    "TradingMode",
    "ensure_utc",
    "new_correlation_id",
    "uuid7",
    "uuid7_time",
]
