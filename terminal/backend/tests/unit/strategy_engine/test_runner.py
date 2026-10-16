import decimal
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from kterminal.core.enums import SignalAction
from kterminal.core.registry import Registry
from kterminal.domain.timeframes import H1, M1, M5
from kterminal.marketdata.aggregator import aggregate_stream
from kterminal.strategy_engine.hosts import InProcessHost
from kterminal.strategy_engine.instances import InstanceSpec, resolve_instance
from kterminal.strategy_engine.model import PositionEventKind
from kterminal.strategy_engine.registry import StrategyDefinition, definition_from_class
from kterminal.strategy_engine.runner import StrategyRunner
from kterminal.strategy_engine.testing import run_strategy
from tests.fixtures.catalog import lab_catalog
from tests.fixtures.instruments import INSTRUMENTS, XAUUSD, bars, gold_minutes
from tests.fixtures.strategies import (
    ContextProbe,
    Crasher,
    LevelHoarder,
    Misbehaving,
    OrbProbe,
    Saboteur,
    Scripted,
    SmaCross,
)

FLAT = [(100.0, 101.0, 99.0, 100.0)] * 10


def test_signals_are_stamped_with_identity_and_rounded() -> None:
    result = run_strategy(
        Scripted,
        instrument=XAUUSD,
        bars=bars("XAUUSD", "5m", FLAT),
        timeframe="5m",
        params={"long_on": [2], "stop_distance": "1.234"},
        instance_id="scripted_a",
    )
    (signal,) = result.signals
    assert signal.strategy_id == "scripted_a"
    assert signal.symbol == "XAUUSD"
    assert signal.timeframe == "5m"
    assert signal.strategy_version == result.runner.resolved.version  # type: ignore[union-attr]
    assert signal.stop_loss == Decimal("98.77")  # rounded to the 0.01 tick
    assert signal.timestamp == bars("XAUUSD", "5m", FLAT)[1].close_time
    assert signal.bar_time == bars("XAUUSD", "5m", FLAT)[1].open_time
    assert [e.kind for e in result.events] == [PositionEventKind.OPENED]


def test_invalid_outputs_are_rejected_not_routed() -> None:
    result = run_strategy(
        Misbehaving, instrument=XAUUSD, bars=bars("XAUUSD", "5m", FLAT[:1]), timeframe="5m"
    )
    assert len(result.signals) == 1
    codes = sorted(r.code for r in result.rejected)
    assert codes == ["IDENTITY_MISMATCH", "NOT_A_SIGNAL", "STOP_WRONG_SIDE"]
    assert result.fault is None


def test_exception_faults_the_instance_and_stops_signals() -> None:
    result = run_strategy(
        Crasher,
        instrument=XAUUSD,
        bars=bars("XAUUSD", "5m", FLAT),
        timeframe="5m",
        params={"crash_on": 3},
    )
    assert result.fault is not None
    assert result.fault.error_type == "ZeroDivisionError"
    assert result.fault.stage == "on_bar"
    assert "strategy bug" in result.fault.traceback
    assert [s.signal for s in result.signals] == [SignalAction.LONG]  # nothing after the fault
    assert result.runner is not None and result.runner.bars_evaluated == 3


def test_warmup_primes_state_but_emits_nothing() -> None:
    history = bars("XAUUSD", "5m", FLAT[:5])
    live = bars("XAUUSD", "5m", FLAT[:3], start=history[-1].close_time)
    result = run_strategy(
        Scripted,
        instrument=XAUUSD,
        bars=live,
        timeframe="5m",
        params={"long_on": [2, 6]},
        warmup_bars=history,
    )
    # bar 2 happened during warm-up → discarded; bar 6 is the first live bar
    assert len(result.signals) == 1
    assert result.signals[0].timestamp == live[0].close_time


def test_context_timeframe_has_no_look_ahead() -> None:
    minutes = gold_minutes(180)
    stream = [
        bar
        for batch in aggregate_stream(minutes, M1, [M5, H1])
        for bar in batch
        if bar.timeframe in (M5, H1)
    ]
    result = run_strategy(ContextProbe, instrument=XAUUSD, bars=stream, timeframe="5m")
    assert result.fault is None
    probe = result.runner._strategy  # type: ignore[union-attr]
    seen = probe.seen  # type: ignore[union-attr]
    assert len(seen) == 36
    # at 01:00 the first hourly bar has just closed and is visible; before that none is
    by_time = {t: (n, latest) for t, n, latest in seen}
    assert by_time["2026-01-05T00:55:00+00:00"] == (0, None)
    assert by_time["2026-01-05T01:00:00+00:00"] == (1, "2026-01-05T01:00:00+00:00")
    assert by_time["2026-01-05T01:55:00+00:00"][0] == 1


def test_sma_strategy_is_deterministic() -> None:
    minutes = gold_minutes(2_000, seed=11)
    five = [b for batch in aggregate_stream(minutes, M1, [M5]) for b in batch if b.timeframe == M5]
    first = run_strategy(SmaCross, instrument=XAUUSD, bars=five, timeframe="5m")
    second = run_strategy(SmaCross, instrument=XAUUSD, bars=five, timeframe="5m")
    assert first.signals == second.signals
    assert len(first.signals) > 2


# ── containment: nothing a strategy returns or raises escapes the runner ─────
def test_system_exit_is_contained_as_a_fault() -> None:
    result = run_strategy(
        Crasher,
        instrument=XAUUSD,
        bars=bars("XAUUSD", "5m", FLAT),
        timeframe="5m",
        params={"crash_on": 2, "mode": "sysexit"},
    )
    assert result.fault is not None
    assert result.fault.error_type == "SystemExit"


def sabotage(mode: str) -> Any:
    return run_strategy(
        Saboteur,
        instrument=XAUUSD,
        bars=bars("XAUUSD", "5m", FLAT[:1]),
        timeframe="5m",
        params={"mode": mode},
    )


def test_returned_signals_are_revalidated_from_scratch() -> None:
    result = sabotage("float_stop")  # model_copy(update=...) let a float in
    (signal,) = result.signals
    assert isinstance(signal.stop_loss, Decimal)  # the routed copy is fully validated
    assert result.fault is None


@pytest.mark.parametrize(
    ("mode", "code"),
    [
        ("nan_meta", "METADATA_NOT_JSON"),
        ("numpy_meta", "INVALID_SIGNAL"),  # not a JSON value: fails re-validation
        ("spoof_time", "IDENTITY_MISMATCH"),
    ],
)
def test_unstorable_or_spoofed_signals_are_rejected(mode: str, code: str) -> None:
    result = sabotage(mode)
    assert result.signals == []
    (rejected,) = result.rejected
    assert rejected.code == code
    json.dumps(rejected.payload, allow_nan=False)  # what gets recorded is always storable
    assert result.fault is None


def test_runaway_output_faults_the_instance() -> None:
    result = sabotage("flood")
    assert result.fault is not None
    assert result.fault.stage == "output"
    assert result.signals == []


def test_a_strategy_cannot_change_the_callers_decimal_context() -> None:
    before = decimal.getcontext().copy()
    result = sabotage("decimal")
    assert len(result.signals) == 1
    after = decimal.getcontext()
    assert (after.prec, after.rounding) == (before.prec, before.rounding)


def test_runners_of_one_instance_never_share_params() -> None:
    registry: Registry[StrategyDefinition] = Registry("strategy definition")
    definition = definition_from_class(LevelHoarder)
    registry.register(definition.id, definition)
    resolved = resolve_instance(
        InstanceSpec(
            id="hoarder", strategy=definition.id, instruments=("XAUUSD", "XAGUSD"), timeframe="5m"
        ),
        instruments=INSTRUMENTS,
        definitions=registry,
    )
    host = InProcessHost(resolved, INSTRUMENTS)
    host.start()
    for symbol, price in (("XAUUSD", 2650), ("XAGUSD", 30)):
        host.on_bars(bars(symbol, "5m", [(price, price, price, price)]))
    levels = {
        runner.instrument.symbol: runner._strategy.params.levels  # type: ignore[union-attr,attr-defined]
        for runner in host._core.runners
    }
    assert levels == {"XAUUSD": [Decimal(1), Decimal(2650)], "XAGUSD": [Decimal(1), Decimal(30)]}
    assert resolved.params.levels == [Decimal(1)]  # type: ignore[attr-defined]


def test_session_helpers_look_at_the_bars_open_like_pine() -> None:
    sessions = lab_catalog().sessions  # ny_orb_15: 09:30-09:45 New York = 14:30-14:45 UTC
    five = bars(
        "XAUUSD", "5m", [(100, 101, 99, 100)] * 4, start=datetime(2026, 1, 6, 14, 25, tzinfo=UTC)
    )
    runner = StrategyRunner(
        resolve_instance(
            InstanceSpec(id="probe", strategy="orb_probe", instruments=("XAUUSD",), timeframe="5m"),
            instruments=INSTRUMENTS,
            sessions=sessions,
            definitions=_registry(OrbProbe),
        ),
        XAUUSD,
        sessions=sessions,
    )
    seen = []
    for bar in five:
        runner.ctx._set_bar(bar)
        seen.append((bar.open_time.strftime("%H:%M"), runner.ctx.in_window("ny_orb_15")))
    assert seen == [("14:25", False), ("14:30", True), ("14:35", True), ("14:40", True)]
    assert runner.ctx.session() == "ny_session"
    with pytest.raises(KeyError, match="not declared"):
        runner.ctx.in_window("london_open_15")  # not in meta.sessions nor the classification


def _registry(*classes: type) -> Registry[StrategyDefinition]:
    registry: Registry[StrategyDefinition] = Registry("strategy definition")
    for cls in classes:
        definition = definition_from_class(cls)  # type: ignore[arg-type]
        registry.register(definition.id, definition)
    return registry
