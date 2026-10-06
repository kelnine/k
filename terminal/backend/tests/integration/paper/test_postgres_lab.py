"""The lab against PostgreSQL: two strategies, one clock, two Paper 50K accounts.

Everything asserted here is read back from the database — the isolation audit,
balances, trades and versions — and compared with the same run recorded in
memory, so the database is shown to hold exactly what the simulation did.
"""

from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml
from sqlalchemy import func, select
from typer.testing import CliRunner

from kterminal.cli import app
from kterminal.db import models as m
from kterminal.db.session import Database
from kterminal.domain.market import Bar
from kterminal.marketdata.synthetic import synthetic_bars
from kterminal.paper.config import LabConfig
from kterminal.paper.lab import Lab, LabResult
from kterminal.paper.pg_store import PostgresLabStore
from kterminal.paper.store import InMemoryLabStore, LabStore
from kterminal.strategy_engine.registry import discover_strategies
from tests.fixtures.catalog import lab_catalog, write_catalog_dir
from tests.fixtures.instruments import T0

discover_strategies(entry_points=False)

SMA: dict[str, Any] = {
    "id": "demo_sma_fast",
    "strategy": "demo_sma_cross",
    "params": {"fast": 9, "slow": 21},
    "instruments": ["XAUUSD"],
    "timeframe": "5m",
    "context_timeframes": ["15m", "1h"],
}
BREAKOUT: dict[str, Any] = {
    "id": "demo_breakout_xau",
    "strategy": "demo_breakout",
    "instruments": ["XAUUSD"],
    "timeframe": "5m",
}
CONFIG = LabConfig.model_validate(
    {"instances": [SMA, BREAKOUT], "defaults": {"account": {"starting_balance": 50000}}}
)


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


async def run(store: LabStore, bars: Sequence[Bar]) -> LabResult:
    return await Lab(CONFIG, lab_catalog(), store, discover=False).run(bars)


def by_instance(result: LabResult) -> dict[str, Any]:
    return {a.instance_id: a for a in result.accounts}


async def test_two_strategies_record_into_independent_paper_accounts(database: Database) -> None:
    bars = gold()
    store = PostgresLabStore(database)
    result = await run(store, bars)
    reference = await run(InMemoryLabStore(), bars)

    # Two accounts, each Paper 50K, each owned by exactly one instance.
    accounts = by_instance(result)
    assert set(accounts) == {"demo_sma_fast", "demo_breakout_xau"}
    assert len({a.account_id for a in result.accounts}) == 2
    for account in result.accounts:
        assert account.starting_balance == Decimal(50000)
        assert account.account_name.startswith("Paper 50K")
        assert account.signals > 0, f"{account.instance_id} generated no signals"
        assert account.summary.trades > 0, f"{account.instance_id} closed no trades"
    assert accounts["demo_sma_fast"].balance != accounts["demo_breakout_xau"].balance

    # The isolation audit runs over the rows PostgreSQL holds.
    checks = await store.isolation_checks(result.run_id)
    assert {c.instance_id for c in checks} == set(accounts)
    assert all(c.ok for c in checks), checks
    assert all(c.decisions > 0 and c.trades > 0 and c.ledger_entries > 1 for c in checks)

    # The database holds exactly what the in-memory run computed.
    expected = by_instance(reference)
    for instance_id, account in accounts.items():
        assert await store.ledger_balance(account.account_id) == account.balance
        assert account.balance == expected[instance_id].balance
        assert account.summary == expected[instance_id].summary
        trades = await store.closed_trades(account.account_id)
        assert len(trades) == account.summary.trades
        assert {t.instance_id for t in trades} == {instance_id}
        assert sum((t.net_pnl or Decimal(0)) for t in trades) == account.summary.net_pnl


async def test_every_signal_and_trade_carries_its_own_version(database: Database) -> None:
    result = await run(PostgresLabStore(database), gold(1_500))
    async with database.session() as session:
        versions = {
            row.instance_id: row
            for row in (
                await session.scalars(
                    select(m.StrategyVersionRow).where(
                        m.StrategyVersionRow.instance_id.in_(["demo_sma_fast", "demo_breakout_xau"])
                    )
                )
            ).all()
        }
        assert set(versions) == {"demo_sma_fast", "demo_breakout_xau"}
        assert versions["demo_sma_fast"].config_hash != versions["demo_breakout_xau"].config_hash

        for instance_id, version in versions.items():
            foreign_signals = await session.scalar(
                select(func.count())
                .select_from(m.SignalRow)
                .where(
                    m.SignalRow.run_id == result.run_id,
                    m.SignalRow.strategy_instance_id == instance_id,
                    m.SignalRow.strategy_version_id != version.id,
                )
            )
            assert foreign_signals == 0
            foreign_trades = await session.scalar(
                select(func.count())
                .select_from(m.TradeRow)
                .where(
                    m.TradeRow.run_id == result.run_id,
                    m.TradeRow.strategy_instance_id == instance_id,
                    m.TradeRow.strategy_version_id != version.id,
                )
            )
            assert foreign_trades == 0


async def test_dedicated_accounts_persist_and_runs_never_touch_them(database: Database) -> None:
    store = PostgresLabStore(database)
    first = dict(await Lab(CONFIG, lab_catalog(), store, discover=False).provision_dedicated())
    again = dict(await Lab(CONFIG, lab_catalog(), store, discover=False).provision_dedicated())
    assert set(first) == {"demo_sma_fast", "demo_breakout_xau"}
    assert all(a.created for a in first.values())
    assert not any(a.created for a in again.values())
    assert {k: a.account_id for k, a in first.items()} == {
        k: a.account_id for k, a in again.items()
    }

    run_one = await run(store, gold(1_500))
    run_two = await run(store, gold(1_500, seed=22))
    dedicated = {a.account_id for a in first.values()}
    run_accounts = [{a.account_id for a in r.accounts} for r in (run_one, run_two)]
    assert not dedicated & run_accounts[0]
    assert not dedicated & run_accounts[1]
    assert not run_accounts[0] & run_accounts[1]

    # Forward-test history stays clean: only the opening deposit.
    for account in first.values():
        assert await store.ledger_balance(account.account_id) == Decimal(50000)
        assert await store.closed_trades(account.account_id) == []


def test_cli_lab_demo_with_postgres_store(
    fresh_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_catalog_dir(tmp_path)
    (tmp_path / "lab.yaml").write_text(yaml.safe_dump(CONFIG.model_dump(mode="json")))
    monkeypatch.setenv("KT_PATHS__CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("KT_DATABASE__URL", fresh_url)
    result = CliRunner().invoke(app, ["lab", "demo", "--days", "1", "--store", "postgres"])
    assert result.exit_code == 0, result.output
    assert "Isolation audit (from recorded rows):" in result.output
    assert "FAIL" not in result.output
    assert result.output.count("Paper 50K") >= 2
