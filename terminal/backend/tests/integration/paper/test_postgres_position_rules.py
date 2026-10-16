"""Position rules recorded in PostgreSQL: skipped entries, session-close exits, replace and
stop moves are rows the schema accepts, and match the same run recorded in memory."""

from typing import Any

from sqlalchemy import select

from kterminal.core.registry import Registry
from kterminal.db import models as m
from kterminal.db.session import Database
from kterminal.paper.config import LabConfig
from kterminal.paper.lab import Lab, LabResult
from kterminal.paper.pg_store import PostgresLabStore
from kterminal.paper.store import InMemoryLabStore, LabStore
from kterminal.strategy_engine.model import OPEN_BEYOND_STOP, OPEN_BEYOND_TARGET
from kterminal.strategy_engine.registry import StrategyDefinition, definition_from_class
from tests.fixtures.catalog import lab_catalog
from tests.fixtures.engine_strategies import PLANNED_STEPS, Planned, planned_minutes

MOVES: list[dict[str, Any]] = [
    {"bar": 1, "action": "long", "stop": "3990", "target": "4030"},
    {"bar": 2, "action": "move_sl", "stop": "3990"},  # the same stop: no STOP_MOVED row
    {"bar": 3, "action": "move_sl", "stop": "3995", "target": "4030"},  # a real move
    {"bar": 4, "action": "exit_long", "session_close": True},
]
CONFIG = LabConfig.model_validate(
    {
        "instances": [
            {
                "id": "planned_guarded",
                "strategy": "planned",
                "params": {"steps": PLANNED_STEPS},
                "instruments": ["XAUUSD"],
                "timeframe": "1m",
                "skip_entry_beyond_levels": True,
            },
            {
                "id": "planned_moves",
                "strategy": "planned",
                "params": {"steps": MOVES},
                "instruments": ["XAUUSD"],
                "timeframe": "1m",
                "on_opposite_signal": "ignore",
            },
        ]
    }
)


def registry() -> Registry[StrategyDefinition]:
    reg: Registry[StrategyDefinition] = Registry("strategy definition")
    definition = definition_from_class(Planned)
    reg.register(definition.id, definition)
    return reg


async def run(store: LabStore) -> LabResult:
    lab = Lab(CONFIG, lab_catalog(), store, definitions=registry(), discover=False)
    return await lab.run(planned_minutes())


async def test_position_rules_are_recorded_in_postgres(database: Database) -> None:
    store = PostgresLabStore(database)
    result = await run(store)
    reference = await run(InMemoryLabStore())
    accounts = {a.instance_id: a for a in result.accounts}
    expected = {a.instance_id: a for a in reference.accounts}
    assert set(accounts) == {"planned_guarded", "planned_moves"}
    for instance_id, account in accounts.items():
        assert await store.ledger_balance(account.account_id) == account.balance
        assert account.balance == expected[instance_id].balance
        assert account.summary == expected[instance_id].summary
    checks = await store.isolation_checks(result.run_id)
    assert all(c.ok for c in checks), checks

    guarded = accounts["planned_guarded"].account_id
    moves = accounts["planned_moves"].account_id
    async with database.session() as session:
        reasons = (
            await session.scalars(
                select(m.TradeRow.exit_reason)
                .where(m.TradeRow.account_id == guarded)
                .order_by(m.TradeRow.entry_time)
            )
        ).all()
        assert list(reasons) == [
            "SIGNAL_EXIT",
            "SESSION_CLOSE",
            "STOP_LOSS",
            "REVERSAL",
            "TAKE_PROFIT",
        ]
        cancelled = (
            await session.execute(
                select(m.OrderRow.status, m.OrderRow.reject_reason, m.OrderRow.risk_decision_id)
                .where(m.OrderRow.account_id == guarded, m.OrderRow.status == "CANCELLED")
                .order_by(m.OrderRow.completed_at)
            )
        ).all()
        assert [(row.status, row.reject_reason) for row in cancelled] == [
            ("CANCELLED", OPEN_BEYOND_STOP),
            ("CANCELLED", OPEN_BEYOND_TARGET),
        ]
        approvals = (
            await session.scalars(
                select(m.RiskDecisionRow.approved).where(
                    m.RiskDecisionRow.id.in_([row.risk_decision_id for row in cancelled])
                )
            )
        ).all()
        assert approvals == [True, True]  # approved on the signal bar, skipped at the open

        (trade,) = (
            await session.scalars(select(m.TradeRow).where(m.TradeRow.account_id == moves))
        ).all()
        assert trade.exit_reason == "SESSION_CLOSE"
        events = (
            await session.execute(
                select(m.TradeEventRow.kind, m.TradeEventRow.new_value).where(
                    m.TradeEventRow.trade_id == trade.id
                )
            )
        ).all()
        assert [(row.kind, str(row.new_value)) for row in events] == [
            ("STOP_MOVED", "3995.0000000000")
        ]
