"""Helpers for testing strategies (golden tests, parity tests).

    result = run_strategy(SmaCross, instrument=xau, bars=bars, timeframe="5m",
                          params={"fast": 9, "slow": 21})
    assert [s.signal for s in result.signals] == [...]

The strategy runs through the real runner (validation, theoretical book,
fault handling) but outside the global registry, so tests never interfere
with registered plug-ins.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from kterminal.core.registry import Registry
from kterminal.domain.instruments import Instrument
from kterminal.domain.market import Bar
from kterminal.domain.signals import Signal
from kterminal.strategy_engine.base import Strategy
from kterminal.strategy_engine.instances import InstanceSpec, resolve_instance
from kterminal.strategy_engine.model import Fault, PositionEvent, RejectedSignal
from kterminal.strategy_engine.registry import StrategyDefinition, definition_from_class
from kterminal.strategy_engine.runner import StrategyRunner


@dataclass
class StrategyTestResult:
    signals: list[Signal] = field(default_factory=list)
    rejected: list[RejectedSignal] = field(default_factory=list)
    events: list[PositionEvent] = field(default_factory=list)
    fault: Fault | None = None
    runner: StrategyRunner | None = None


def group_by_close(bars: Iterable[Bar]) -> list[list[Bar]]:
    """Group bars into batches that closed at the same instant, in time order."""
    batches: dict[Any, list[Bar]] = {}
    for bar in sorted(bars, key=lambda b: b.close_time):
        batches.setdefault(bar.close_time, []).append(bar)
    return list(batches.values())


def run_strategy(
    strategy_cls: type[Strategy[Any]],
    *,
    instrument: Instrument,
    bars: Sequence[Bar],
    timeframe: str,
    params: dict[str, Any] | None = None,
    context_timeframes: Sequence[str] = (),
    sessions: Any | None = None,
    warmup_bars: Sequence[Bar] = (),
    instance_id: str = "test_instance",
) -> StrategyTestResult:
    registry: Registry[StrategyDefinition] = Registry("strategy definition")
    definition = definition_from_class(strategy_cls)
    registry.register(definition.id, definition)
    spec = InstanceSpec(
        id=instance_id,
        strategy=definition.id,
        params=params or {},
        instruments=(instrument.symbol,),
        timeframe=timeframe,
        context_timeframes=tuple(context_timeframes),
    )
    resolved = resolve_instance(
        spec, instruments={instrument.symbol: instrument}, sessions=sessions, definitions=registry
    )
    runner = StrategyRunner(resolved, instrument, sessions=sessions)
    result = StrategyTestResult(runner=runner)
    result.fault = runner.start()
    if warmup_bars:
        runner.warmup(warmup_bars)
    for batch in group_by_close(bars):
        output = runner.process(batch)
        if output is None:
            continue
        result.signals.extend(output.signals)
        result.rejected.extend(output.rejected)
        result.events.extend(output.events)
        if output.fault is not None:
            result.fault = output.fault
    return result
