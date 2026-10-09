"""Module 1 — Strategy Engine (the strategy SDK, registry, runner and hosts).

Strategy authors use :class:`Strategy`, :class:`StrategyMeta`,
:class:`StrategyParams` and :func:`register_strategy`; the lab uses
:func:`resolve_instance` and the hosts. Strategies propose; they never size,
route or place orders. See ``docs/05-strategy-interface.md`` and
``docs/12-strategy-lab.md``.
"""

from kterminal.strategy_engine.base import (
    NoParams,
    SignalOutput,
    Strategy,
    StrategyMeta,
    StrategyParams,
)
from kterminal.strategy_engine.context import StrategyContext
from kterminal.strategy_engine.instances import (
    InstanceConfigError,
    InstanceSpec,
    ResolvedInstance,
    resolve_instance,
)
from kterminal.strategy_engine.model import (
    CloseReason,
    Fault,
    PositionEvent,
    PositionEventKind,
    PositionView,
    RejectedSignal,
    RunnerOutput,
)
from kterminal.strategy_engine.registry import (
    DEFINITIONS,
    StrategyDefinition,
    StrategyDefinitionError,
    discover_strategies,
    register_external,
    register_strategy,
)

__all__ = [
    "DEFINITIONS",
    "CloseReason",
    "Fault",
    "InstanceConfigError",
    "InstanceSpec",
    "NoParams",
    "PositionEvent",
    "PositionEventKind",
    "PositionView",
    "RejectedSignal",
    "ResolvedInstance",
    "RunnerOutput",
    "SignalOutput",
    "Strategy",
    "StrategyContext",
    "StrategyDefinition",
    "StrategyDefinitionError",
    "StrategyMeta",
    "StrategyParams",
    "discover_strategies",
    "register_external",
    "register_strategy",
    "resolve_instance",
]
