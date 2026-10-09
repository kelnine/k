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
    PositionRules,
    PositionView,
    RejectedSignal,
    RunnerOutput,
)
from kterminal.strategy_engine.periods import Period, PeriodBar, PeriodLevels, period_warmup_bars
from kterminal.strategy_engine.registry import (
    DEFINITIONS,
    StrategyDefinition,
    StrategyDefinitionError,
    discover_strategies,
    register_external,
    register_strategy,
)
from kterminal.strategy_engine.series import BarSeries, SeriesView
from kterminal.strategy_engine.sessions import (
    SessionSpec,
    SessionString,
    TimeZoneName,
    in_session,
    parse_session,
    session_started,
)

__all__ = [
    "DEFINITIONS",
    "BarSeries",
    "CloseReason",
    "Fault",
    "InstanceConfigError",
    "InstanceSpec",
    "NoParams",
    "Period",
    "PeriodBar",
    "PeriodLevels",
    "PositionEvent",
    "PositionEventKind",
    "PositionRules",
    "PositionView",
    "RejectedSignal",
    "ResolvedInstance",
    "RunnerOutput",
    "SeriesView",
    "SessionSpec",
    "SessionString",
    "SignalOutput",
    "Strategy",
    "StrategyContext",
    "StrategyDefinition",
    "StrategyDefinitionError",
    "StrategyMeta",
    "StrategyParams",
    "TimeZoneName",
    "discover_strategies",
    "in_session",
    "parse_session",
    "period_warmup_bars",
    "register_external",
    "register_strategy",
    "resolve_instance",
    "session_started",
]
