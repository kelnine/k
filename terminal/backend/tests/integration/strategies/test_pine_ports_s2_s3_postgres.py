"""The Pine ports S2 (orb_breakout) and S3 (smc_sniper) in the lab against PostgreSQL:
their signals — entries, the ORB's SESSION_CLOSE exits and persisted NO_TRADEs — are
recorded with the script's metadata exactly as computed, trades closed at the flatten
time keep their exit reason, and every account audits clean.

The New York ORB instance (MNQ, NAS100, US30, US500), the London ORB instance and the
5m Min Score 3 sniper (all 14 instruments) run on synthetic bars with the real
catalog; the rows read back from the database must equal the same run recorded in
memory.
"""

from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select

from kterminal.db import models as m
from kterminal.db.session import Database
from kterminal.paper.config import LabConfig
from kterminal.paper.demo import demo_bars
from kterminal.paper.lab import Lab, LabResult
from kterminal.paper.pg_store import PostgresLabStore
from kterminal.paper.records import SignalRecord, TradeRecord
from kterminal.paper.store import InMemoryLabStore, LabStore
from kterminal.strategy_engine.registry import discover_strategies
from tests.integration.paper.conftest import database, fresh_url  # noqa: F401 - fixtures
from tests.unit.strategies.pine_port_support import forward_config, instance_entries, real_catalog

pytestmark = pytest.mark.integration

INSTANCES = {
    "orb_breakout": ("orb_breakout_ny_mideod_5m", "orb_breakout_london_5m"),
    "smc_sniper": ("smc_sniper_min3_5m",),
}
IDS = [i for ids in INSTANCES.values() for i in ids]


def config() -> LabConfig:
    entries: list[dict[str, Any]] = []
    for strategy, ids in INSTANCES.items():
        entries += [e for e in instance_entries(strategy) if e["id"] in ids]
    defaults = forward_config().defaults.model_dump(mode="json")
    return LabConfig.model_validate({"defaults": defaults, "instances": entries})


async def run(store: LabStore) -> LabResult:
    discover_strategies(entry_points=False)
    cfg = config()
    catalog = real_catalog()
    return await Lab(cfg, catalog, store, discover=False).run(demo_bars(catalog, cfg, days=3))


async def test_s2_s3_record_their_signals_and_audit_clean(database: Database) -> None:  # noqa: F811
    store = PostgresLabStore(database)
    result = await run(store)
    memory = InMemoryLabStore()
    reference = await run(memory)

    assert [a.instance_id for a in result.accounts] == IDS
    expected = {a.instance_id: a for a in reference.accounts}
    for account in result.accounts:
        assert account.fault is None and account.signals > 0, account
        assert account.balance == expected[account.instance_id].balance
        assert account.summary == expected[account.instance_id].summary
        assert await store.ledger_balance(account.account_id) == account.balance
    checks = await store.isolation_checks(result.run_id)
    assert checks and all(c.ok for c in checks), checks

    recorded = {
        (r.instance_id, r.signal.symbol, r.signal.bar_time, r.signal.signal.value): r.signal
        for r in memory.of(SignalRecord)
        if r.signal.signal.value != "NO_TRADE" or r.signal.persist
    }
    async with database.session() as session:
        rows = (
            await session.scalars(select(m.SignalRow).where(m.SignalRow.run_id == result.run_id))
        ).all()
        trades = (
            await session.scalars(select(m.TradeRow).where(m.TradeRow.run_id == result.run_id))
        ).all()
    stored = {(r.strategy_instance_id, r.instrument, r.bar_time, r.action): r for r in rows}
    assert set(stored) == set(recorded)
    for key, row in stored.items():
        signal = recorded[key]
        assert row.meta == signal.metadata  # nested points/zones, nulls for na
        assert row.reason == signal.reason
        assert row.stop_loss == signal.stop_loss
        assert row.take_profit == signal.take_profit
    actions = {(r.strategy_instance_id.split("_")[0], r.action) for r in rows}
    assert {("orb", "LONG"), ("orb", "SHORT"), ("smc", "LONG"), ("smc", "SHORT")} <= actions
    # every ORB instance flattens daily at its flatten time (ctx.flatten, SESSION_CLOSE);
    # only the no-target variant still holds a trade then (or it was stopped out): the
    # other flattens change nothing in the book nor the account (IGNORED, no decision)
    assert not [r for r in rows if r.action.startswith("EXIT_")]
    flattens = [r for r in rows if r.action == "FLATTEN"]
    assert flattens and all(r.reason == "SESSION_CLOSE" for r in flattens)
    assert all(r.strategy_instance_id.startswith("orb_breakout_") for r in flattens)
    acted = [r for r in flattens if r.reject_code is None]
    assert acted and all(r.strategy_instance_id == "orb_breakout_ny_mideod_5m" for r in acted)
    idle = [r for r in flattens if r.reject_code is not None]
    assert idle
    assert all((r.status, r.reject_code) == ("IGNORED", "NOTHING_TO_FLATTEN") for r in idle)
    assert result.consistency["unexplained_episodes"] == 0

    closed = [t for t in memory.of(TradeRecord) if t.status == "CLOSED"]
    eod = [t for t in closed if t.instance_id == "orb_breakout_ny_mideod_5m"]
    assert {t.exit_reason for t in eod} <= {"SESSION_CLOSE", "STOP_LOSS"}
    assert any(t.exit_reason == "SESSION_CLOSE" for t in eod)

    def trade_key(instance: str, instrument: str, entry_time: Any, reason: Any, stop: Any) -> tuple:
        return (instance, instrument, entry_time, reason, stop)

    stored_trades = sorted(
        trade_key(t.strategy_instance_id, t.instrument, t.entry_time, t.exit_reason, t.initial_stop)
        for t in trades
        if t.status == "CLOSED"
    )
    assert stored_trades == sorted(
        trade_key(t.instance_id, t.instrument, t.entry_time, t.exit_reason, t.initial_stop)
        for t in closed
    )
    assert all(isinstance(t.initial_stop, Decimal) for t in trades)
