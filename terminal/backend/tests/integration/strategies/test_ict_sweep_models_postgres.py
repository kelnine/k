"""Script 2's Model A and Model B ports (S5, S4) in the lab against PostgreSQL: their LIMIT
setups, cancels and window exits, with the script's metadata, are recorded faithfully and
every account audits clean.

The flat-at-window-end instance of each model runs on synthetic bars of all 14 instruments
with the real catalog; the rows read back from the database must equal the same run
recorded in memory.
"""

from typing import Any

import pytest
from sqlalchemy import select

from kterminal.db import models as m
from kterminal.db.session import Database
from kterminal.paper.config import LabConfig
from kterminal.paper.demo import demo_bars
from kterminal.paper.lab import Lab, LabResult
from kterminal.paper.pg_store import PostgresLabStore
from kterminal.paper.records import SignalRecord
from kterminal.paper.store import InMemoryLabStore, LabStore
from kterminal.strategy_engine.registry import discover_strategies
from tests.integration.paper.conftest import database, fresh_url  # noqa: F401 - fixtures
from tests.unit.strategies.pine_port_support import forward_config, instance_entries, real_catalog

pytestmark = pytest.mark.integration

INSTANCES = {"ict_model_a": "ict_model_a_flat_1m", "ict_model_b": "ict_model_b_flat_1m"}


def config() -> LabConfig:
    entries: list[dict[str, Any]] = []
    for strategy, instance_id in INSTANCES.items():
        entries += [e for e in instance_entries(strategy) if e["id"] == instance_id]
    defaults = forward_config().defaults.model_dump(mode="json")
    return LabConfig.model_validate({"defaults": defaults, "instances": entries})


async def run(store: LabStore) -> LabResult:
    discover_strategies(entry_points=False)
    cfg = config()
    catalog = real_catalog()
    return await Lab(cfg, catalog, store, discover=False).run(demo_bars(catalog, cfg, days=2))


async def test_sweep_models_record_their_signals_and_audit_clean(database: Database) -> None:  # noqa: F811
    store = PostgresLabStore(database)
    result = await run(store)
    memory = InMemoryLabStore()
    reference = await run(memory)

    assert [a.instance_id for a in result.accounts] == list(INSTANCES.values())
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
    }
    async with database.session() as session:
        rows = (
            await session.scalars(select(m.SignalRow).where(m.SignalRow.run_id == result.run_id))
        ).all()
    assert len(rows) == len(recorded)
    actions = set()
    for row in rows:
        key = (row.strategy_instance_id, row.instrument, row.bar_time, row.action)
        signal = recorded[key]
        assert row.meta == signal.metadata  # nested levels, nulls for na, ISO times
        assert row.reason == signal.reason
        assert row.stop_loss == signal.stop_loss
        assert row.take_profit == signal.take_profit
        if signal.entry is not None:
            assert row.entry == signal.entry
        if signal.signal.is_entry:
            assert row.order_type == "LIMIT"
            assert row.expires_after_bars == signal.expires_after_bars
            assert isinstance(row.meta["script_entry"], float)
        actions.add(row.action)
    assert {"LONG", "SHORT"} <= actions
    assert actions & {"EXIT_LONG", "EXIT_SHORT"}
