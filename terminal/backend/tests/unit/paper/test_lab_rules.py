"""Per-instance position rules through the lab: the instance's theoretical book and its
paper account apply the same overrides and record the same trades."""

from datetime import datetime
from typing import Any

import pytest
from pydantic import ValidationError

from kterminal.core.enums import Direction
from kterminal.core.registry import Registry
from kterminal.paper.config import LabConfig
from kterminal.paper.lab import Lab
from kterminal.paper.records import DecisionRecord, OrderRecord, SignalRecord, TradeRecord
from kterminal.paper.store import InMemoryLabStore
from kterminal.strategy_engine.hosts import InProcessHost
from kterminal.strategy_engine.model import (
    OPEN_BEYOND_STOP,
    OPEN_BEYOND_TARGET,
    PositionEvent,
    PositionEventKind,
)
from kterminal.strategy_engine.registry import StrategyDefinition, definition_from_class
from tests.fixtures.catalog import lab_catalog
from tests.fixtures.engine_strategies import PLANNED_STEPS, Planned, planned_minutes


def registry() -> Registry[StrategyDefinition]:
    reg: Registry[StrategyDefinition] = Registry("strategy definition")
    definition = definition_from_class(Planned)
    reg.register(definition.id, definition)
    return reg


def instance(instance_id: str, **overrides: Any) -> dict[str, Any]:
    return {
        "id": instance_id,
        "strategy": "planned",
        "params": {"steps": PLANNED_STEPS},
        "instruments": ["XAUUSD"],
        "timeframe": "1m",
        **overrides,
    }


def book_events(lab: Lab, instance_id: str) -> list[PositionEvent]:
    member = next(m for m in lab.members if m.resolved.id == instance_id)
    assert isinstance(member.host, InProcessHost)
    strategy = member.host._core.runners[0]._strategy
    assert isinstance(strategy, Planned)
    return strategy.events


def book_outcomes(events: list[PositionEvent]) -> list[tuple[Any, ...]]:
    outcomes: list[tuple[Any, ...]] = []
    entries: dict[Direction, datetime] = {}
    for event in events:
        if event.kind is PositionEventKind.OPENED:
            entries[event.direction] = event.time
        elif event.kind is PositionEventKind.CLOSED and event.reason is not None:
            outcomes.append((entries[event.direction], event.direction, event.time, event.reason))
        elif event.kind is PositionEventKind.ORDER_CANCELLED:
            outcomes.append((event.time, event.detail))
    return outcomes


async def test_instance_overrides_reach_the_book_and_the_account_alike() -> None:
    config = LabConfig.model_validate(
        {
            "instances": [
                instance("planned_guarded", skip_entry_beyond_levels=True),
                instance("planned_ignoring", on_opposite_signal="ignore"),
            ]
        }
    )
    store = InMemoryLabStore()
    lab = Lab(config, lab_catalog(), store, definitions=registry(), discover=False)
    result = await lab.run(planned_minutes())
    guarded, ignoring = (m.resolved for m in lab.members)
    assert guarded.position_rules.skip_entry_beyond_levels
    assert ignoring.position_rules.on_opposite_signal == "ignore"
    assert guarded.version != ignoring.version
    accounts = {a.instance_id: a.account_id for a in result.accounts}

    for instance_id in accounts:
        account_id = accounts[instance_id]
        trades = [
            t
            for t in store.of(TradeRecord)
            if t.account_id == account_id and t.status == "CLOSED" and t.exit_reason != "RUN_END"
        ]
        cancelled = [
            o
            for o in store.of(OrderRecord)
            if o.account_id == account_id
            and o.reject_reason in (OPEN_BEYOND_STOP, OPEN_BEYOND_TARGET)
        ]
        account_outcomes = sorted(
            [(t.entry_time, t.direction, t.exit_time, t.exit_reason) for t in trades]
            + [(o.completed_at, o.reject_reason) for o in cancelled],
            key=lambda item: (item[0], len(item)),
        )
        expected = sorted(
            book_outcomes(book_events(lab, instance_id)), key=lambda item: (item[0], len(item))
        )
        assert account_outcomes == expected, instance_id

    guarded_reasons = [o[-1] for o in book_outcomes(book_events(lab, "planned_guarded"))]
    assert guarded_reasons == [
        "SIGNAL_EXIT",
        "SESSION_CLOSE",
        OPEN_BEYOND_STOP,
        "STOP_LOSS",
        OPEN_BEYOND_TARGET,
        "REVERSAL",
        "TAKE_PROFIT",
    ]
    # Without the guard both market entries fill (and are closed at once by their levels);
    # ignoring opposite entries, the reversal on bar 10 is refused and the long is stopped.
    ignoring_reasons = [o[-1] for o in book_outcomes(book_events(lab, "planned_ignoring"))]
    assert OPEN_BEYOND_STOP not in ignoring_reasons and "REVERSAL" not in ignoring_reasons
    signals = {s.id: s for s in store.of(SignalRecord)}
    refused = [
        d.primary_reason
        for d in store.of(DecisionRecord)
        if d.account_id == accounts["planned_ignoring"] and not d.approved
    ]
    assert "OPPOSITE_POSITION_OPEN" in refused
    assert all(s.instance_id in accounts for s in signals.values())


def test_lab_instances_validate_their_overrides() -> None:
    with pytest.raises(ValidationError, match="on_opposite_signal"):
        LabConfig.model_validate({"instances": [instance("planned_a", on_opposite_signal="flip")]})
    config = LabConfig.model_validate({"instances": [instance("planned_a")]})
    spec = config.instance_spec(config.instances[0])
    assert spec.on_opposite_signal is None and spec.skip_entry_beyond_levels is None
