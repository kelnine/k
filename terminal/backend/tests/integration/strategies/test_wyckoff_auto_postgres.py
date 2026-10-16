"""Script 6's Wyckoff port (S12 ``wyckoff_auto``) in the lab against PostgreSQL: its
entries with the D5 stop, the 2R variant's target and the structure exits, with the
script's metadata (the nested campaign, nulls for na, ISO times), are recorded faithfully
and every account audits clean.

Three 15m instances of ``config/instances.d/wyckoff_auto.yaml`` trade the scenario tapes
of the unit tests (complete accumulation and distribution campaigns back to back) as
1-minute bars of BTCUSD with the real catalog; the rows read back from the database must
equal the same run recorded in memory.
"""

import pytest
from sqlalchemy import select

from kterminal.db import models as m
from kterminal.db.session import Database
from kterminal.paper.lab import Lab, LabResult
from kterminal.paper.pg_store import PostgresLabStore
from kterminal.paper.records import SignalRecord
from kterminal.paper.store import InMemoryLabStore, LabStore
from kterminal.strategy_engine.registry import discover_strategies
from tests.integration.paper.conftest import database, fresh_url  # noqa: F401 - fixtures
from tests.unit.strategies.pine_port_support import real_catalog
from tests.unit.strategies.wyckoff_auto.scenario import minute_bars, stitched
from tests.unit.strategies.wyckoff_auto.test_instances import LAB_IDS, tape_lab_config

pytestmark = pytest.mark.integration


async def run(store: LabStore) -> LabResult:
    discover_strategies(entry_points=False)
    return await Lab(tape_lab_config(), real_catalog(), store, discover=False).run(
        minute_bars(stitched(), instrument="BTCUSD")
    )


async def test_wyckoff_records_its_campaign_trades_and_audits_clean(database: Database) -> None:  # noqa: F811
    store = PostgresLabStore(database)
    result = await run(store)
    memory = InMemoryLabStore()
    reference = await run(memory)

    assert [a.instance_id for a in result.accounts] == LAB_IDS
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
        if r.signal is not None
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
        assert row.meta == signal.metadata  # the nested campaign, nulls for na, ISO times
        assert row.reason == signal.reason
        assert row.stop_loss == signal.stop_loss
        assert row.take_profit == signal.take_profit
        if signal.signal.is_entry:
            assert row.order_type == "MARKET"
            campaign = row.meta["campaign"]
            assert isinstance(campaign, dict) and campaign["phase"] in ("C", "D")
            assert row.meta["trigger"] in ("Wyckoff: long entry", "Wyckoff: short entry")
            if row.strategy_instance_id.endswith("_2r_15m"):
                assert row.take_profit is not None
        if row.action == "FLATTEN":
            assert row.meta["exit_event"] in (
                "INVALIDATION",
                "DEMOTION",
                "PHASE_E_FAILURE",
                "PHASE_E_TIMEOUT",
                "REPLACED_BY_CLIMAX",
            )
        actions.add(row.action)
    assert {"LONG", "SHORT", "FLATTEN"} <= actions
    # the book resolves like the accounts: nothing diverged that a refusal does not explain
    assert result.consistency["checks"] > 0
    assert result.consistency["unexplained_episodes"] == 0, result.consistency["examples"]
