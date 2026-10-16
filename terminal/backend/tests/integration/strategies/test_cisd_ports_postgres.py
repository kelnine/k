"""Script 1's CISD ports (S6 ``cisd_sweep``, S10 ``cisd_scanner``) in the lab against
PostgreSQL: their LIMIT setups, cancels and replace exits, with the script's metadata
(nested sweep and slot rows, nulls for na), are recorded faithfully and every account
audits clean.

One limit instance of each strategy and the S6 market comparison run on synthetic bars of
all 14 instruments with the real catalog; the rows read back from the database must
equal the same run recorded in memory.
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

INSTANCES = {
    "cisd_sweep": ("cisd_sweep_any_tp2_5m", "cisd_sweep_any_market_5m"),
    "cisd_scanner": ("cisd_scanner_plain_tp1_5m",),
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
    return await Lab(cfg, catalog, store, discover=False).run(demo_bars(catalog, cfg, days=2))


async def test_cisd_ports_record_their_signals_and_audit_clean(database: Database) -> None:  # noqa: F811
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
    }
    async with database.session() as session:
        rows = (
            await session.scalars(select(m.SignalRow).where(m.SignalRow.run_id == result.run_id))
        ).all()
    assert len(rows) == len(recorded)
    seen = set()
    for row in rows:
        key = (row.strategy_instance_id, row.instrument, row.bar_time, row.action)
        signal = recorded[key]
        assert row.meta == signal.metadata  # nested sweep / slot rows, nulls for na
        assert row.reason == signal.reason
        assert row.stop_loss == signal.stop_loss
        assert row.take_profit == signal.take_profit
        if signal.entry is not None:
            assert row.entry == signal.entry
        if signal.signal.is_entry:
            market = row.strategy_instance_id.endswith("market_5m")
            assert row.order_type == ("MARKET" if market else "LIMIT")
            assert row.expires_after_bars == (None if market else 12)
            assert isinstance(row.meta["script_entry"], float)
        seen.add((row.strategy_instance_id.split("_")[1], row.action))
    for model in ("sweep", "scanner"):
        assert {(model, "LONG"), (model, "SHORT")} <= seen
        assert (model, "EXIT_LONG") in seen or (model, "EXIT_SHORT") in seen
