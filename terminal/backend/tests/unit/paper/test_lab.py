"""The lab's core promise: many strategies, one clock, separate accounts, no interference."""

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

import pytest

from kterminal.core.registry import Registry
from kterminal.domain.market import Bar
from kterminal.marketdata.synthetic import synthetic_bars
from kterminal.paper.account import PaperAccount
from kterminal.paper.config import LabConfig
from kterminal.paper.demo import demo_bars
from kterminal.paper.lab import Lab, LabResult
from kterminal.paper.records import (
    DecisionRecord,
    FaultRecord,
    LedgerRecord,
    SignalRecord,
    TradeRecord,
)
from kterminal.paper.store import InMemoryLabStore
from kterminal.strategy_engine.registry import (
    DEFINITIONS,
    StrategyDefinition,
    definition_from_class,
    discover_strategies,
)
from tests.fixtures.catalog import lab_catalog
from tests.fixtures.instruments import T0
from tests.fixtures.strategies import Crasher

discover_strategies(entry_points=False)


def gold(count: int = 3_000, seed: int = 21) -> list[Bar]:
    calendar = lab_catalog().sessions.calendar("metals_otc")
    return list(
        synthetic_bars(
            "XAUUSD",
            start=T0,
            count=count,
            start_price=Decimal("4000.00"),
            tick_size=Decimal("0.01"),
            seed=seed,
            is_open=calendar.is_open,
        )
    )


SMA = {
    "id": "demo_sma_fast",
    "strategy": "demo_sma_cross",
    "params": {"fast": 9, "slow": 21},
    "instruments": ["XAUUSD"],
    "timeframe": "5m",
    "context_timeframes": ["15m", "1h"],
}
BREAKOUT = {
    "id": "demo_breakout_xau",
    "strategy": "demo_breakout",
    "params": {},
    "instruments": ["XAUUSD"],
    "timeframe": "5m",
}


def config(*instances: dict[str, Any], **defaults: Any) -> LabConfig:
    return LabConfig.model_validate(
        {"instances": list(instances), "defaults": {"account": defaults}}
    )


async def run(
    cfg: LabConfig, bars: Sequence[Bar], definitions: Registry[StrategyDefinition] = DEFINITIONS
) -> tuple[LabResult, InMemoryLabStore]:
    store = InMemoryLabStore()
    lab = Lab(cfg, lab_catalog(), store, definitions=definitions, discover=False)
    result = await lab.run(bars)
    return result, store


def by_account(store: InMemoryLabStore, kind: type, account_id: Any) -> list[Any]:
    return [r for r in store.of(kind) if getattr(r, "account_id", None) == account_id]


async def test_two_strategies_trade_into_two_independent_paper_50k_accounts() -> None:
    result, store = await run(config(SMA, BREAKOUT), gold())
    a, b = result.accounts
    assert (a.instance_id, b.instance_id) == ("demo_sma_fast", "demo_breakout_xau")
    assert a.account_id != b.account_id
    assert a.starting_balance == b.starting_balance == Decimal(50000)
    assert a.account_name == "Paper 50K · demo_sma_fast"
    for acc in (a, b):
        assert acc.signals > 0 and acc.summary.trades > 0, acc
        assert acc.fault is None

    signals = store.of(SignalRecord)
    for acc in (a, b):
        own_signal_ids = {s.id for s in signals if s.instance_id == acc.instance_id}
        decisions = by_account(store, DecisionRecord, acc.account_id)
        trades = by_account(store, TradeRecord, acc.account_id)
        assert decisions and {d.signal_id for d in decisions} <= own_signal_ids
        assert {t.instance_id for t in trades} == {acc.instance_id}
        assert {t.entry_signal_id for t in trades} <= own_signal_ids
        ledger = by_account(store, LedgerRecord, acc.account_id)
        assert acc.balance == acc.starting_balance + sum(e.amount for e in ledger)
        closed = [
            t
            for t in store.trades.values()
            if t.account_id == acc.account_id and t.status == "CLOSED"
        ]
        assert acc.summary.net_pnl == sum(t.net_pnl for t in closed)
        assert acc.balance == acc.starting_balance + acc.summary.net_pnl  # all flat at the end
    assert a.balance != b.balance


async def test_an_instance_behaves_identically_alone_or_alongside_others() -> None:
    bars = gold()
    alone, alone_store = await run(config(SMA), bars)
    together, together_store = await run(config(SMA, BREAKOUT), bars)

    def fingerprint(store: InMemoryLabStore, instance: str) -> list[tuple[Any, ...]]:
        trades = sorted(
            (t for t in store.trades.values() if t.instance_id == instance),
            key=lambda t: t.entry_time,
        )
        return [
            (
                t.direction,
                t.entry_time,
                t.entry_price,
                t.qty,
                t.exit_time,
                t.exit_price,
                t.exit_reason,
                t.net_pnl,
            )
            for t in trades
        ]

    assert fingerprint(alone_store, "demo_sma_fast") == fingerprint(together_store, "demo_sma_fast")
    assert alone.accounts[0].balance == together.accounts[0].balance
    assert alone.accounts[0].summary == together.accounts[0].summary


async def test_multiple_instances_of_one_definition_are_separate_subjects() -> None:
    slow = {
        **SMA,
        "id": "demo_sma_slow",
        "params": {"fast": 20, "slow": 50},
        "account": {"starting_balance": 100000},
    }
    result, store = await run(config(SMA, slow), gold())
    fast_acc, slow_acc = result.accounts
    assert slow_acc.starting_balance == Decimal(100000)
    assert slow_acc.account_name == "Paper 100K · demo_sma_slow"
    versions = set(store.versions)
    assert len({v for _, v in versions}) == 2  # different config hashes → different versions
    fast_versions = {
        s.strategy_version for s in store.of(SignalRecord) if s.instance_id == "demo_sma_fast"
    }
    slow_versions = {
        s.strategy_version for s in store.of(SignalRecord) if s.instance_id == "demo_sma_slow"
    }
    assert len(fast_versions) == len(slow_versions) == 1
    assert fast_versions != slow_versions
    assert fast_acc.summary != slow_acc.summary


async def test_a_crashing_strategy_faults_alone() -> None:
    registry: Registry[StrategyDefinition] = Registry("strategy definition")
    for definition in (DEFINITIONS.get("demo_sma_cross"), definition_from_class(Crasher)):
        registry.register(definition.id, definition)
    crasher = {
        "id": "crasher_xau",
        "strategy": "crasher",
        "params": {"crash_on": 50},
        "instruments": ["XAUUSD"],
        "timeframe": "5m",
    }
    bars = gold(1_500)
    reference, _ = await run(config(SMA), bars, registry)
    result, store = await run(config(SMA, crasher), bars, registry)
    sma, crash = result.accounts
    assert crash.host_state == "FAULTED"
    assert crash.fault is not None and "ZeroDivisionError" in crash.fault
    assert [f.instance_id for f in store.of(FaultRecord)] == ["crasher_xau"]
    assert sma.host_state == "STOPPED" and sma.fault is None
    assert sma.summary == reference.accounts[0].summary


async def test_signals_carry_version_and_market_snapshot() -> None:
    _, store = await run(config(SMA), gold(1_200))
    routed = [s for s in store.of(SignalRecord) if s.status == "ROUTED"]
    assert routed
    first = routed[0]
    assert first.signal is not None
    assert first.strategy_version == first.signal.strategy_version
    assert first.market_snapshot["bar"]["close"] == str(first.signal.entry)
    assert "catalog_fingerprint" in first.market_snapshot


def test_lab_config_validation() -> None:
    with pytest.raises(ValueError, match="duplicate instance ids"):
        config(SMA, SMA)
    with pytest.raises(ValueError, match="not available yet"):
        config({**SMA, "account": {"mode": "LIVE"}})


async def test_no_edge_on_a_random_walk() -> None:
    """Look-ahead / fill-bias regression guard: on a pure random walk the expected R of
    any strategy is ~0. A pipeline that leaked future prices into fills or signals would
    show a large, consistent positive average R here."""
    zero_cost = {"venue_profile": "lab_default"}
    silver = {**SMA, "id": "sma_silver", "instruments": ["XAGUSD"]}  # zero-cost listing
    calendar = lab_catalog().sessions.calendar("metals_otc")
    total_r = Decimal(0)
    trades = 0
    for seed in (101, 102, 103, 104):
        bars = list(
            synthetic_bars(
                "XAGUSD",
                start=T0,
                count=6_000,
                start_price=Decimal("45.000"),
                tick_size=Decimal("0.001"),
                seed=seed,
                is_open=calendar.is_open,
            )
        )
        result, _ = await run(config(silver, **zero_cost), bars)
        summary = result.accounts[0].summary
        total_r += summary.realized_r
        trades += summary.trades
    assert trades > 200
    average_r = total_r / trades
    assert abs(average_r) < Decimal("0.15"), average_r


def test_experiment_members_must_share_identical_conditions() -> None:
    other = {**SMA, "id": "demo_sma_other", "params": {"fast": 5, "slow": 30}}
    members = [
        {"instance": "demo_sma_fast", "label": "A"},
        {"instance": "demo_sma_other", "label": "A'"},
    ]
    ok = LabConfig.model_validate(
        {
            "instances": [SMA, other],
            "experiments": [{"id": "sma_lengths", "name": "SMA lengths", "members": members}],
        }
    )
    assert ok.experiments[0].members[1].label == "A'"
    with pytest.raises(ValueError, match="identical account settings"):
        LabConfig.model_validate(
            {
                "instances": [SMA, {**other, "account": {"starting_balance": 100000}}],
                "experiments": [{"id": "unfair", "name": "x", "members": members}],
            }
        )
    with pytest.raises(ValueError, match="unknown instances"):
        LabConfig.model_validate(
            {
                "instances": [SMA],
                "experiments": [{"id": "x", "name": "x", "members": members}],
            }
        )


# ── failure containment & run bookkeeping (review findings) ─────────────────
async def test_a_signal_that_breaks_its_own_account_faults_only_that_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bars = gold(1_500)
    reference, _ = await run(config(SMA), bars)
    original = PaperAccount.handle_signal

    def explode_for_breakout(self: PaperAccount, signal: Any, *args: Any) -> Any:
        if self.instance_id == "demo_breakout_xau":
            raise RuntimeError("account cannot process this signal")
        return original(self, signal, *args)

    monkeypatch.setattr(PaperAccount, "handle_signal", explode_for_breakout)
    result, store = await run(config(SMA, BREAKOUT), bars)
    accounts = {a.instance_id: a for a in result.accounts}
    assert accounts["demo_breakout_xau"].host_state == "FAULTED"
    assert accounts["demo_breakout_xau"].fault is not None
    assert "account cannot process" in accounts["demo_breakout_xau"].fault
    (healthy,) = reference.accounts
    assert accounts["demo_sma_fast"].summary == healthy.summary
    assert accounts["demo_sma_fast"].balance == healthy.balance
    assert [f.instance_id for f in store.of(FaultRecord)] == ["demo_breakout_xau"]


class FailingStore(InMemoryLabStore):
    def __init__(self, fail_after: int) -> None:
        super().__init__()
        self.fail_after = fail_after

    async def write(self, records: Sequence[Any], *, run_id: Any) -> None:
        self.fail_after -= 1
        if self.fail_after < 0:
            raise ConnectionError("database went away")
        await super().write(records, run_id=run_id)


async def test_a_failed_run_is_recorded_and_every_host_is_stopped() -> None:
    store = FailingStore(fail_after=50)
    cfg = config({**SMA, "host": "subprocess"}, BREAKOUT)
    lab = Lab(cfg, lab_catalog(), store, discover=False)
    with pytest.raises(ConnectionError):
        await lab.run(gold(1_500))
    (run_state,) = store.runs.values()
    assert run_state["status"] == "FAILED"
    assert "database went away" in run_state["summary"]["error"]
    assert all(m.host.state.value in {"STOPPED", "FAULTED"} for m in lab.members)
    sub = lab.members[0].host
    assert getattr(sub, "pid", None) is None  # the child process was terminated


async def test_every_run_trades_in_fresh_accounts_never_the_dedicated_one() -> None:
    store = InMemoryLabStore()
    cfg = config(SMA)
    dedicated = dict(await Lab(cfg, lab_catalog(), store, discover=False).provision_dedicated())
    first = await Lab(cfg, lab_catalog(), store, discover=False).run(gold(1_500))
    second = await Lab(cfg, lab_catalog(), store, discover=False).run(gold(1_500))
    ids = {
        dedicated["demo_sma_fast"].account_id,
        first.accounts[0].account_id,
        second.accounts[0].account_id,
    }
    assert len(ids) == 3
    assert first.accounts[0].summary == second.accounts[0].summary  # same bars, fresh account
    for result in (first, second):
        (check,) = await store.isolation_checks(result.run_id)
        assert check.ok and check.account_id == str(result.accounts[0].account_id)
    assert await store.closed_trades(dedicated["demo_sma_fast"].account_id) == []


def test_demo_data_of_a_symbol_does_not_depend_on_other_instances() -> None:
    catalog = lab_catalog()
    alone = demo_bars(catalog, config(SMA), days=1)
    mnq = {
        "id": "mnq_probe",
        "strategy": "demo_sma_cross",
        "instruments": ["MNQ"],
        "timeframe": "5m",
    }
    together = demo_bars(catalog, config(SMA, mnq), days=1)
    assert [b for b in together if b.instrument == "XAUUSD"] == alone
