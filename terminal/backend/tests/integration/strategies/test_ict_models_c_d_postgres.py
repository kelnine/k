"""Script 2's Model C and Model D ports (S9 ``ict_model_c``, S11 ``ict_model_d``) in the lab
against PostgreSQL: their market entries, time exits (``FLATTEN``) and the script's
metadata (nested zone, candidate and level objects, nulls for na) are recorded
faithfully, a time exit with nothing to close is recorded ``IGNORED`` with the book's
reason, and every account audits clean.

Model C's hold instance (all 14 instruments) and Model D's flat-at-16:00 instance (MNQ
and the crypto pairs) run on synthetic bars with the real catalog; the rows read back
from the database must equal the same run recorded in memory.
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

INSTANCES = {"ict_model_c": "ict_model_c_main_1m", "ict_model_d": "ict_model_d_flat_1m"}


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
    return await Lab(cfg, catalog, store, discover=False).run(demo_bars(catalog, cfg, days=3))


async def test_models_c_and_d_record_their_signals_and_audit_clean(database: Database) -> None:  # noqa: F811
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
        (r.instance_id, r.signal.symbol, r.signal.bar_time, r.signal.signal.value): r
        for r in memory.of(SignalRecord)
        if r.signal is not None
    }
    async with database.session() as session:
        rows = (
            await session.scalars(select(m.SignalRow).where(m.SignalRow.run_id == result.run_id))
        ).all()
    assert len(rows) == len(recorded)
    seen = set()
    for row in rows:
        key = (row.strategy_instance_id, row.instrument, row.bar_time, row.action)
        record = recorded[key]
        signal = record.signal
        assert signal is not None
        assert row.meta == signal.metadata  # nested zone / candidate / levels, nulls for na
        assert row.reason == signal.reason
        assert row.stop_loss == signal.stop_loss
        assert row.take_profit == signal.take_profit
        assert (row.status, row.reject_code) == (record.status, record.reject_code)
        if signal.entry is not None:
            assert row.entry == signal.entry
        model = row.meta["model"]
        if signal.signal.is_entry:
            assert row.order_type == "MARKET" and row.expires_after_bars is None
            assert isinstance(row.meta["script_entry"], float)
            nested = "zone" if model == "C" else "candidate"
            assert isinstance(row.meta[nested], dict)
        if row.action == "FLATTEN" and row.status == "IGNORED":
            assert row.reject_code == "NOTHING_TO_FLATTEN"
        seen.add((model, row.action))
    for model in ("C", "D"):
        assert {(model, "LONG"), (model, "SHORT")} <= seen, seen
        assert (model, "FLATTEN") in seen
    # the book resolves like the accounts: whatever diverged was an account refusal
    assert result.consistency["checks"] > 0
    assert result.consistency["unexplained_episodes"] == 0, result.consistency["examples"]
