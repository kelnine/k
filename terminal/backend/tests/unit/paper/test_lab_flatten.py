"""FLATTEN, the books' reasons and the consistency report through the lab."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from kterminal.core.registry import Registry
from kterminal.domain.market import Bar
from kterminal.paper.config import LabConfig
from kterminal.paper.ids import SessionIds
from kterminal.paper.kill_switch import ActiveSwitch, KillSwitchState
from kterminal.paper.lab import Lab
from kterminal.paper.records import DecisionRecord, OrderRecord, SignalRecord, TradeRecord
from kterminal.paper.store import InMemoryLabStore
from kterminal.strategy_engine import NOTHING_TO_FLATTEN
from kterminal.strategy_engine.hosts import InProcessHost
from kterminal.strategy_engine.registry import StrategyDefinition, definition_from_class
from kterminal.strategy_engine.runner import StrategyRunner
from tests.fixtures.catalog import lab_catalog
from tests.fixtures.engine_strategies import Probe

START = datetime(2026, 1, 5, 14, 0, tzinfo=UTC)  # Monday 09:00 New York
MIN = timedelta(minutes=1)
RUN_ID = UUID(int=7)


def registry() -> Registry[StrategyDefinition]:
    reg: Registry[StrategyDefinition] = Registry("strategy definition")
    definition = definition_from_class(Probe)
    reg.register(definition.id, definition)
    return reg


def config(steps: list[dict[str, Any]], **instance: Any) -> LabConfig:
    return LabConfig.model_validate(
        {
            "instances": [
                {
                    "id": "probe_gold",
                    "strategy": "probe",
                    "params": {"steps": steps},
                    "instruments": ["XAUUSD"],
                    "timeframe": "1m",
                    **instance,
                }
            ]
        }
    )


def minutes(count: int) -> list[Bar]:
    return [
        Bar.of("XAUUSD", "1m", START + i * MIN, "4000.00", "4000.50", "3999.50", "4000.00")
        for i in range(count)
    ]


async def begin(lab_config: LabConfig) -> tuple[Lab, InMemoryLabStore]:
    store = InMemoryLabStore()
    lab = Lab(lab_config, lab_catalog(), store, definitions=registry(), ids=SessionIds(4))
    await lab.setup()
    await lab.begin(RUN_ID, started_at=START)
    return lab, store


def runner_of(lab: Lab) -> StrategyRunner:
    host = lab.members[0].host
    assert isinstance(host, InProcessHost)
    return host._core.runners[0]


async def feed(lab: Lab, bars: list[Bar]) -> None:
    for bar in bars:
        await lab.process_bars([bar], through=bar.close_time)


def signal_rows(store: InMemoryLabStore) -> list[tuple[str, str, str | None]]:
    return [
        (r.signal.signal.value, r.status, r.reject_code)
        for r in store.of(SignalRecord)
        if r.signal is not None
    ]


async def test_flatten_closes_what_the_account_holds_when_the_book_is_flat() -> None:
    """The ports' bug: the book closed (e.g. on a mid-price touch), the account did not,
    and a time exit built from ``ctx.position`` never reached the account."""
    steps = [
        {"bar": 1, "action": "long", "stop": "3990"},
        {"bar": 5, "action": "flatten"},
        {"bar": 8, "action": "flatten"},
    ]
    lab, store = await begin(config(steps))
    bars = minutes(12)
    await feed(lab, bars[:3])
    account = lab.accounts[0]
    assert "XAUUSD" in account.positions and runner_of(lab).book.position is not None
    runner_of(lab).book._position = None  # the book alone closed it (the old divergence)
    await feed(lab, bars[3:])

    trades = {t.id: t for t in store.of(TradeRecord)}
    (trade,) = trades.values()
    assert trade.status == "CLOSED" and trade.exit_reason == "SESSION_CLOSE"
    assert trade.exit_time == bars[5].open_time  # at the next base bar's open
    assert signal_rows(store) == [
        ("LONG", "ROUTED", None),
        ("FLATTEN", "ROUTED", None),  # the book had nothing, the account did: it acted
        ("FLATTEN", "IGNORED", NOTHING_TO_FLATTEN),  # nothing anywhere: no effect
    ]
    flatten_ids = [
        r.id for r in store.of(SignalRecord) if r.signal and r.signal.signal.value == "FLATTEN"
    ]
    decided = [d for d in store.of(DecisionRecord) if d.signal_id in flatten_ids]
    assert [(d.signal_id, d.approved) for d in decided] == [(flatten_ids[0], True)]  # no 2nd row
    report = lab.consistency.summary()
    assert report["episodes"] == 1 and report["unexplained_episodes"] == 1
    assert report["open_episodes"] == 0  # the flatten ended it
    assert report["examples"][0]["kinds"] == ["POSITION"]


async def test_flatten_cancels_the_resting_entry_under_a_kill_switch_too() -> None:
    steps = [
        {"bar": 1, "action": "long", "stop": "3990"},
        {"bar": 3, "action": "short", "entry": "4010", "stop": "4020", "order_type": "LIMIT"},
        {"bar": 5, "action": "flatten"},
    ]
    lab, store = await begin(config(steps))
    bars = minutes(10)
    await feed(lab, bars[:4])
    drill = ActiveSwitch("GLOBAL", "*", "drill", cancel_orders=False)  # orders keep resting
    lab.set_kill_switches(KillSwitchState((drill,)))
    await feed(lab, bars[4:])
    account = lab.accounts[0]
    assert account.entry_halt is not None
    assert not account.positions and not account.pending_entries
    (trade,) = {t.id: t for t in store.of(TradeRecord)}.values()
    assert trade.exit_reason == "SESSION_CLOSE"
    cancelled = [o for o in store.of(OrderRecord) if o.reject_reason == "CANCELLED_BY_FLATTEN"]
    assert len(cancelled) == 1  # the resting reversal was cancelled with the flatten …
    report = lab.consistency.summary()
    assert report["divergent"] == 0  # … in the book as well


async def test_a_signal_without_effect_is_ignored_with_the_books_reason() -> None:
    steps = [
        {"bar": 1, "action": "long", "stop": "3990"},
        {"bar": 2, "action": "long", "stop": "3990"},
        {"bar": 3, "action": "exit_short"},
        {"bar": 4, "action": "exit_long"},
    ]
    lab, store = await begin(config(steps))
    await feed(lab, minutes(8))
    result = await lab.end()
    assert signal_rows(store) == [
        ("LONG", "ROUTED", None),
        ("LONG", "IGNORED", "POSITION_EXISTS"),
        ("EXIT_SHORT", "IGNORED", "NO_MATCHING_POSITION"),
        ("EXIT_LONG", "ROUTED", None),
    ]
    ignored = [r for r in store.of(SignalRecord) if r.status == "IGNORED"]
    assert ignored[0].reject_detail == (
        "ignored by the theoretical book: a position in this direction is already open"
    )
    # the account still decided (and refused) them: exits always reach it
    refused = {d.primary_reason for d in store.of(DecisionRecord) if not d.approved}
    assert refused == {"POSITION_EXISTS", "NO_MATCHING_POSITION"}
    assert result.consistency["divergent"] == 0
    assert result.consistency["checks"] == 8


async def test_the_run_summary_keeps_the_consistency_report() -> None:
    steps = [{"bar": 2, "action": "long", "stop": "3990", "target": "4010"}]
    store = InMemoryLabStore()
    lab = Lab(config(steps), lab_catalog(), store, definitions=registry())
    result = await lab.run(minutes(10))
    (run,) = store.runs.values()
    assert run["summary"]["consistency"] == result.consistency
    assert result.consistency["checks"] == 10 and result.consistency["divergent"] == 0
    assert result.consistency["examples"] == []
