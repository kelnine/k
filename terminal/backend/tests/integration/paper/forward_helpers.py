"""Shared set-up for the forward-runtime integration tests: lab configuration, fake
providers on a fake clock, a runtime runner and a normalised dump of everything a
session wrote (ids that differ between two databases replaced by stable labels)."""

import asyncio
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text

from kterminal.core.registry import Registry
from kterminal.db.repositories.kill_switches import set_kill_switch
from kterminal.db.session import Database
from kterminal.paper.config import LabConfig
from kterminal.paper.feed import FeedConfig
from kterminal.paper.runtime import PaperRuntime, RuntimeOptions
from kterminal.strategy_engine.registry import (
    DEFINITIONS,
    StrategyDefinition,
    definition_from_class,
    discover_strategies,
)
from tests.fixtures.catalog import lab_catalog
from tests.fixtures.forward import FakeProvider, FakeTime, market_bars
from tests.fixtures.strategies import Scripted

discover_strategies(entry_points=False)

# Monday 5 January 2026 21:00 UTC: gold trades until its daily break at 22:00 UTC (17:00
# New York) and reopens at 23:00; NEAR trades around the clock.
START = datetime(2026, 1, 5, 21, 0, tzinfo=UTC)
MIN = timedelta(minutes=1)
METALS = lab_catalog().sessions.calendar("metals_otc")
# NEAR warms up on (40 + 1) one-hour periods of demo_breakout's 1h context: 2460 minutes.
NEAR_WARMUP = 2_460


def minute(k: int) -> int:
    """The scripted strategy's bar number for the k-th live minute (warm-up bars count)."""
    return NEAR_WARMUP + k + 1


def registry() -> Registry[StrategyDefinition]:
    reg: Registry[StrategyDefinition] = Registry("strategy definition")
    for definition_id, definition in DEFINITIONS.items():
        reg.register(definition_id, definition)
    scripted = definition_from_class(Scripted)
    reg.register(scripted.id, scripted)
    return reg


def lab_config(*, host: str = "in_process", fast: int = 3, **scripted: Any) -> LabConfig:
    return LabConfig.model_validate(
        {
            "equity_snapshot_minutes": 5,
            "instances": [
                {
                    "id": "sma_gold",
                    "strategy": "demo_sma_cross",
                    "params": {"fast": fast, "slow": 8},
                    "instruments": ["XAUUSD"],
                    "timeframe": "1m",
                    "context_timeframes": ["5m"],
                    "host": host,
                },
                {
                    "id": "breakout_near",
                    "strategy": "demo_breakout",
                    "params": {"channel_bars": 5, "trend_filter": False},
                    "instruments": ["NEARUSD"],
                    "timeframe": "5m",
                },
                {
                    "id": "scripted_both",
                    "strategy": "scripted",
                    "params": {
                        "long_on": [minute(5), minute(30), minute(75)],
                        "move_sl_on": [minute(80)],
                        "short_on": [minute(85)],
                        "stop_distance": "0.5",
                        "target_distance": "1.5",
                        **scripted,
                    },
                    "instruments": ["NEARUSD"],
                    "timeframe": "1m",
                },
            ],
        }
    )


def providers(clock: Any) -> dict[str, FakeProvider]:
    history = START - timedelta(days=3)
    gold = FakeProvider(
        "fake-fx",
        market_bars(
            "XAUUSD",
            start=history,
            minutes=3 * 1_440 + 300,
            price="4000.00",
            tick="0.01",
            seed=11,
            is_open=METALS.is_open,
            source="fake-fx",
        ),
        clock,
    )
    near = FakeProvider(
        "fake-crypto",
        market_bars(
            "NEARUSD",
            start=history,
            minutes=3 * 1_440 + 300,
            price="3.000",
            tick="0.001",
            seed=12,
            source="fake-crypto",
        ),
        clock,
    )
    return {"XAUUSD": gold, "NEARUSD": near}


async def run_runtime(
    database: Database,
    clock: FakeTime,
    config: LabConfig,
    *,
    until: datetime,
    feeds: dict[str, FakeProvider] | None = None,
    new_session: bool = False,
) -> PaperRuntime:
    clock.stop_at = until
    runtime = PaperRuntime(
        config=config,
        catalog=lab_catalog(),
        database=database,
        providers=feeds if feeds is not None else providers(clock),
        clock=clock,
        options=RuntimeOptions(
            new_session=new_session, warmup_days=2, feed=FeedConfig(batch_timeout_s=20)
        ),
        definitions=registry(),
        discover=False,
        wait=clock.wait,
    )
    await runtime.run(asyncio.Event())
    return runtime


def kill_switch_action(database: Database, *, active: bool, close: bool = False) -> Any:
    async def action() -> None:
        async with database.session() as session:
            await set_kill_switch(
                session,
                scope="GLOBAL",
                active=active,
                reason="drill",
                changed_by="test",
                ts=datetime(2026, 1, 5, tzinfo=UTC),
                close_positions=close,
            )

    return action


# ── a database-independent dump of a session ─────────────────────────────────
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_DROP = {"created_at", "updated_at", "seq", "catalog_snapshot_id", "ts_hash"}


async def session_dump(database: Database, run_id: UUID) -> dict[str, list[dict[str, Any]]]:
    queries = {
        "signals": "SELECT * FROM signals WHERE run_id = :r ORDER BY id",
        "risk_decisions": "SELECT * FROM risk_decisions WHERE run_id = :r ORDER BY id",
        "orders": "SELECT * FROM orders WHERE run_id = :r ORDER BY id",
        "fills": "SELECT * FROM fills WHERE run_id = :r ORDER BY id",
        "trades": "SELECT * FROM trades WHERE run_id = :r ORDER BY id",
        "trade_events": "SELECT e.* FROM trade_events e JOIN trades t ON t.id = e.trade_id "
        "WHERE t.run_id = :r ORDER BY e.id",
        "account_ledger": "SELECT * FROM account_ledger WHERE run_id = :r ORDER BY seq",
        "equity_snapshots": "SELECT e.*, a.name AS account FROM equity_snapshots e "
        "JOIN accounts a ON a.id = e.account_id WHERE e.run_id = :r ORDER BY e.ts, a.name",
        "candles": "SELECT * FROM candles ORDER BY instrument, source, ts",
        "audit": "SELECT action, entity_type, entity_id, data FROM audit_log "
        "WHERE entity_type = 'run' ORDER BY seq",
        "progress": "SELECT data_fingerprint, status FROM runs WHERE id = :r",
    }
    async with database.session() as session:
        names = {
            row[0]: f"ACC:{row[1]}"
            for row in (await session.execute(text("SELECT id, name FROM accounts"))).all()
        }
        names |= {
            row[0]: f"VER:{row[1]}"
            for row in (
                await session.execute(text("SELECT id, instance_id FROM strategy_versions"))
            ).all()
        }
        names |= {
            row[0]: f"CFG:{row[1]}:v{row[2]}"
            for row in (
                await session.execute(
                    text(
                        "SELECT v.id, a.name, v.version FROM account_config_versions v "
                        "JOIN accounts a ON a.id = v.account_id"
                    )
                )
            ).all()
        }
        names[run_id] = "RUN"
        dump: dict[str, list[dict[str, Any]]] = {}
        for table, query in queries.items():
            rows = (await session.execute(text(query), {"r": run_id})).mappings().all()
            dump[table] = [
                {k: _norm(v, names, run_id) for k, v in row.items() if k not in _DROP}
                for row in rows
            ]
    return dump


def _norm(value: Any, names: dict[UUID, str], run_id: UUID) -> Any:
    namespace = run_id.int & ((1 << 48) - 1)
    if isinstance(value, UUID):
        if value in names:
            return names[value]
        if value.int & ((1 << 48) - 1) == namespace:
            return f"ID:{value.int >> 48:x}"  # a session id without its namespace
        return f"OTHER:{value}"
    if isinstance(value, str):
        return _UUID.sub(lambda m: str(_norm(UUID(m.group(0)), names, run_id)), value)
    if isinstance(value, dict):
        return {k: _norm(v, names, run_id) for k, v in value.items()}
    if isinstance(value, list):
        return [_norm(v, names, run_id) for v in value]
    if isinstance(value, Decimal):
        return value.normalize()
    return value
