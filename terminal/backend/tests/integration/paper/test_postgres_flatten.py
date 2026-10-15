"""FLATTEN signals, signals the theoretical book ignored and the consistency report are
rows the schema accepts (migration 0003), identical to the same run recorded in memory."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from kterminal.core.registry import Registry
from kterminal.db import models as m
from kterminal.db.session import Database
from kterminal.domain.market import Bar
from kterminal.paper.config import LabConfig
from kterminal.paper.lab import Lab, LabResult
from kterminal.paper.pg_store import PostgresLabStore
from kterminal.paper.store import InMemoryLabStore, LabStore
from kterminal.strategy_engine import NOTHING_TO_FLATTEN
from kterminal.strategy_engine.registry import StrategyDefinition, definition_from_class
from tests.fixtures.catalog import lab_catalog
from tests.fixtures.engine_strategies import Probe

START = datetime(2026, 1, 5, 14, 0, tzinfo=UTC)
STEPS: list[dict[str, Any]] = [
    {"bar": 1, "action": "long", "stop": "3990"},
    {"bar": 2, "action": "long", "stop": "3990"},  # POSITION_EXISTS
    {"bar": 4, "action": "flatten"},  # closes the long (SESSION_CLOSE)
    {"bar": 6, "action": "short", "entry": "4010", "stop": "4020", "order_type": "LIMIT"},
    {"bar": 8, "action": "flatten", "reason": "window end"},  # cancels the resting short
    {"bar": 10, "action": "flatten"},  # nothing left: NOTHING_TO_FLATTEN
]
CONFIG = LabConfig.model_validate(
    {
        "instances": [
            {
                "id": "probe_flat",
                "strategy": "probe",
                "params": {"steps": STEPS},
                "instruments": ["XAUUSD"],
                "timeframe": "1m",
            }
        ]
    }
)


def registry() -> Registry[StrategyDefinition]:
    reg: Registry[StrategyDefinition] = Registry("strategy definition")
    definition = definition_from_class(Probe)
    reg.register(definition.id, definition)
    return reg


def minutes() -> list[Bar]:
    return [
        Bar.of("XAUUSD", "1m", START + i * timedelta(minutes=1), "4000", "4000.5", "3999.5", "4000")
        for i in range(14)
    ]


async def run(store: LabStore) -> LabResult:
    lab = Lab(CONFIG, lab_catalog(), store, definitions=registry(), discover=False)
    return await lab.run(minutes())


async def test_flatten_and_ignored_signals_are_recorded_in_postgres(database: Database) -> None:
    store = PostgresLabStore(database)
    result = await run(store)
    reference = await run(InMemoryLabStore())
    (account,) = result.accounts
    assert account.balance == reference.accounts[0].balance
    assert account.summary == reference.accounts[0].summary
    assert result.consistency == reference.consistency
    assert result.consistency["divergent"] == 0
    checks = await store.isolation_checks(result.run_id)
    assert all(c.ok for c in checks), checks

    async with database.session() as session:
        signals = (
            await session.execute(
                select(m.SignalRow.action, m.SignalRow.status, m.SignalRow.reject_code)
                .where(m.SignalRow.run_id == result.run_id)
                .order_by(m.SignalRow.signal_time)
            )
        ).all()
        trades = (
            await session.scalars(
                select(m.TradeRow.exit_reason).where(m.TradeRow.account_id == account.account_id)
            )
        ).all()
        cancels = (
            await session.scalars(
                select(m.OrderRow.reject_reason).where(
                    m.OrderRow.account_id == account.account_id, m.OrderRow.status == "CANCELLED"
                )
            )
        ).all()
        summary = await session.scalar(select(m.RunRow.summary).where(m.RunRow.id == result.run_id))
    assert [tuple(row) for row in signals] == [
        ("LONG", "ROUTED", None),
        ("LONG", "IGNORED", "POSITION_EXISTS"),
        ("FLATTEN", "ROUTED", None),
        ("SHORT", "ROUTED", None),
        ("FLATTEN", "ROUTED", None),
        ("FLATTEN", "IGNORED", NOTHING_TO_FLATTEN),
    ]
    assert list(trades) == ["SESSION_CLOSE"]
    assert list(cancels) == ["CANCELLED_BY_FLATTEN"]
    assert summary is not None and summary["consistency"]["checks"] == 14
