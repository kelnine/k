"""The Phase 3 engine features behave the same in a subprocess host as in process."""

from kterminal.core.registry import Registry
from kterminal.domain.timeframes import M1, M5
from kterminal.marketdata.aggregator import aggregate_stream
from kterminal.strategy_engine.hosts import InProcessHost, SubprocessHost
from kterminal.strategy_engine.instances import InstanceSpec, resolve_instance
from kterminal.strategy_engine.model import CloseReason, PositionEventKind, RunnerOutput
from kterminal.strategy_engine.registry import StrategyDefinition, definition_from_class
from tests.fixtures.catalog import lab_catalog
from tests.fixtures.engine_strategies import WindowFlat
from tests.fixtures.instruments import INSTRUMENTS, gold_minutes


def outputs(host: InProcessHost | SubprocessHost) -> list[RunnerOutput]:
    collected: list[RunnerOutput] = []
    host.start()
    for batch in aggregate_stream(gold_minutes(1_500, seed=5), M1, [M5]):
        collected.extend(host.on_bars(batch))
    host.stop()
    return collected


def test_session_params_rules_and_exit_reasons_cross_the_process_boundary() -> None:
    registry: Registry[StrategyDefinition] = Registry("strategy definition")
    definition = definition_from_class(WindowFlat)
    registry.register(definition.id, definition)
    spec = InstanceSpec(
        id="window_ny_open",
        strategy="window_flat",
        params={"window": "0930-1000", "timezone": "America/New_York"},
        instruments=("XAUUSD",),
        timeframe="5m",
        on_opposite_signal="ignore",
        skip_entry_beyond_levels=True,
    )
    sessions = lab_catalog().sessions
    resolved = resolve_instance(
        spec, instruments=INSTRUMENTS, sessions=sessions, definitions=registry
    )
    local = outputs(InProcessHost(resolved, INSTRUMENTS, sessions))
    remote = outputs(SubprocessHost(resolved, INSTRUMENTS, sessions))
    signals = [s for o in local for s in o.signals]
    events = [e for o in local for e in o.events]
    assert signals == [s for o in remote for s in o.signals]
    assert events == [e for o in remote for e in o.events]
    # 09:30-10:00 New York on Monday 2026-01-05 is 14:30-15:00 UTC
    assert [s.bar_time.isoformat() for s in signals if s.bar_time] == [
        "2026-01-05T14:30:00+00:00",
        "2026-01-05T14:55:00+00:00",
    ]
    assert [e.kind for e in events] == [PositionEventKind.OPENED, PositionEventKind.CLOSED]
    assert events[-1].reason is CloseReason.SESSION_CLOSE
