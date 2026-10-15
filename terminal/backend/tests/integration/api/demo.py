"""A database that looks like a terminal in use, built with the real lab code.

* a **lab simulation** run (``kterminal lab demo --store postgres`` code path):
  run-scoped Paper 50K accounts, everything closed at the end;
* the instances' **dedicated forward accounts** (``kterminal lab provision``),
  then a **forward run** traded into them — the rows the forward paper runtime
  writes — with positions left open;
* the forward run's 1m bars in ``candles``, a ``paper.runtime`` status, one
  risk-rejected and one invalid signal, and dashboard users of every role.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from argon2 import PasswordHasher
from argon2.profiles import CHEAPEST
from sqlalchemy import insert, select

from kterminal.api.auth.passwords import Passwords
from kterminal.api.auth.users import Role, create_user, set_disabled
from kterminal.api.queries.system import RUNTIME_STATE_KEY
from kterminal.config.settings import DatabaseSettings
from kterminal.core.ids import new_correlation_id, uuid7
from kterminal.db import models as m
from kterminal.db.session import Database
from kterminal.domain.accounts import AccountSettings
from kterminal.domain.market import Bar
from kterminal.marketdata.synthetic import synthetic_bars
from kterminal.paper.config import LabConfig
from kterminal.paper.lab import Lab, LabResult
from kterminal.paper.pg_store import PostgresLabStore
from kterminal.paper.store import ProvisionedAccount
from kterminal.strategy_engine.registry import discover_strategies
from tests.fixtures.catalog import lab_catalog
from tests.fixtures.instruments import T0

discover_strategies(entry_points=False)

PASSWORD = "correct horse battery staple"  # every demo user's password
USERS = {
    "ada": Role.ADMIN,
    "otto": Role.OPERATOR,
    "vera": Role.VIEWER,
    "dora": Role.VIEWER,  # disabled
}

CONFIG = LabConfig.model_validate(
    {
        "instances": [
            {
                "id": "demo_sma_fast",
                "strategy": "demo_sma_cross",
                "params": {"fast": 9, "slow": 21},
                "instruments": ["XAUUSD"],
                "timeframe": "5m",
                "context_timeframes": ["15m", "1h"],
            },
            {
                "id": "demo_breakout_xau",
                "strategy": "demo_breakout",
                "instruments": ["XAUUSD"],
                "timeframe": "5m",
            },
        ],
        "defaults": {"account": {"starting_balance": 50000}},
    }
)

FORWARD_START = T0 + timedelta(days=7)


def cheap_passwords() -> Passwords:
    """argon2id with the cheapest parameters: tests need speed, not strength."""
    return Passwords(PasswordHasher.from_parameters(CHEAPEST))


def gold(start: datetime, count: int, seed: int) -> list[Bar]:
    calendar = lab_catalog().sessions.calendar("metals_otc")
    return list(
        synthetic_bars(
            "XAUUSD",
            start=start,
            count=count,
            start_price=Decimal("4000.00"),
            tick_size=Decimal("0.01"),
            seed=seed,
            is_open=calendar.is_open,
        )
    )


class ForwardStore(PostgresLabStore):
    """Records a run into the instances' dedicated accounts, as the forward runtime does."""

    async def provision_account(
        self,
        *,
        instance_id: str,
        name: str,
        settings: AccountSettings,
        run_id: UUID | None = None,
        opened_at: datetime | None = None,
    ) -> ProvisionedAccount:
        return await super().provision_account(
            instance_id=instance_id, name=name, settings=settings, opened_at=opened_at
        )


@dataclass
class DemoData:
    url: str
    lab_run_id: UUID
    forward_run_id: UUID
    lab: LabResult  # what the lab computed in memory for its run-scoped accounts
    forward: LabResult
    lab_accounts: dict[str, UUID]  # instance id → run-scoped account
    forward_accounts: dict[str, UUID]  # instance id → dedicated account
    forward_bars: list[Bar]
    now: datetime  # the API clock: one minute after the forward run's last bar
    rejected_signal_id: UUID
    invalid_signal_id: UUID
    user_ids: dict[str, UUID] = field(default_factory=dict)


async def populate(url: str) -> DemoData:
    database = Database(DatabaseSettings.model_validate({"url": url}), application_name="kt-demo")
    try:
        return await _populate(url, database)
    finally:
        await database.dispose()


async def _populate(url: str, database: Database) -> DemoData:
    catalog = lab_catalog()
    store = PostgresLabStore(database)
    lab = await Lab(CONFIG, catalog, store, discover=False, run_name="lab-demo").run(
        gold(T0, 3_000, seed=21)
    )
    await Lab(CONFIG, catalog, store, discover=False).provision_dedicated()
    forward_bars = gold(FORWARD_START, 3_000, seed=22)
    forward = await Lab(
        CONFIG,
        catalog,
        ForwardStore(database),
        discover=False,
        run_kind="FORWARD",
        run_name="forward-session",
    ).run(forward_bars, close_at_end=False)
    now = forward_bars[-1].close_time + timedelta(minutes=1)

    async with database.session() as session:
        await session.execute(
            insert(m.CandleRow),
            [
                {
                    "instrument": bar.instrument,
                    "timeframe": "1m",
                    "source": "oanda",
                    "ts": bar.open_time,
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                }
                for bar in forward_bars
            ],
        )
        forward_accounts = dict(
            (
                await session.execute(
                    select(m.AccountRow.strategy_instance_id, m.AccountRow.id).where(
                        m.AccountRow.strategy_instance_id.is_not(None)
                    )
                )
            ).all()
        )
        session.add(
            m.SystemStateRow(
                key=RUNTIME_STATE_KEY,
                value=runtime_status(forward.run_id, forward_bars[-1], forward_accounts, now),
                updated_at=now - timedelta(seconds=5),
            )
        )
        rejected, invalid = await _rejections(
            session, forward.run_id, forward_accounts, forward_bars[-1], now
        )
        passwords = cheap_passwords()
        user_ids = {}
        for name, role in USERS.items():
            user = await create_user(
                session,
                username=name,
                password_hash=passwords.hash(PASSWORD),
                role=role,
                actor="test",
                now=now,
            )
            user_ids[name] = user.id
        await set_disabled(session, "dora", disabled=True, actor="test", now=now)

    return DemoData(
        url=url,
        lab=lab,
        forward=forward,
        lab_run_id=lab.run_id,
        forward_run_id=forward.run_id,
        lab_accounts={a.instance_id: a.account_id for a in lab.accounts},
        forward_accounts={str(k): v for k, v in forward_accounts.items()},
        forward_bars=forward_bars,
        now=now,
        rejected_signal_id=rejected,
        invalid_signal_id=invalid,
        user_ids=user_ids,
    )


def runtime_status(
    run_id: UUID, last_bar: Bar, accounts: dict[Any, UUID], now: datetime
) -> dict[str, Any]:
    """A ``paper.runtime`` document shaped exactly as the forward runtime writes it
    (``PaperRuntime.status_document``, docs/12 §12.7)."""
    return {
        "session_id": str(uuid7()),
        "run_id": str(run_id),
        "status": "running",
        "started_at": FORWARD_START.isoformat(),
        "updated_at": (now - timedelta(seconds=5)).isoformat(),
        "last_batch_close": last_bar.close_time.isoformat(),
        "instruments": {
            "XAUUSD": {
                "provider": "oanda",
                "last_bar_open": last_bar.open_time.isoformat(),
                "lag_seconds": 4.2,
                "state": "ok",
                "last_error": None,
            },
        },
        "instances": {
            "demo_sma_fast": {
                "state": "RUNNING",
                "fault": None,
                "account_id": str(accounts["demo_sma_fast"]),
            },
            "demo_breakout_xau": {
                "state": "FAULTED",
                "fault": "ValueError: synthetic fault for the dashboard",
                "account_id": str(accounts["demo_breakout_xau"]),
            },
        },
        "kill_switch": {"global": False, "accounts": [], "strategies": []},
        "error": None,
    }


async def _rejections(
    session: Any, run_id: UUID, accounts: dict[Any, UUID], last: Bar, now: datetime
) -> tuple[UUID, UUID]:
    """A signal the risk layer rejected and one the framework refused, on demo_sma_fast."""
    instance = await session.get(m.StrategyInstanceRow, "demo_sma_fast")
    account = await session.get(m.AccountRow, accounts["demo_sma_fast"])
    rejected, invalid = uuid7(), uuid7()
    common = {
        "strategy_instance_id": "demo_sma_fast",
        "definition_id": "demo_sma_cross",
        "source": "INTERNAL",
        "run_id": run_id,
        "instrument": "XAUUSD",
        "timeframe": "5m",
        "correlation_id": new_correlation_id(),
    }
    await session.execute(
        insert(m.SignalRow),
        [
            {
                **common,
                "id": rejected,
                "strategy_version_id": instance.current_version_id,
                "bar_time": now - timedelta(minutes=6),
                "signal_time": now - timedelta(minutes=1),
                "received_at": now - timedelta(minutes=1),
                "action": "LONG",
                "entry": last.close,
                "stop_loss": last.close - 10,
                "take_profit": last.close + 20,
                "idempotency_key": f"test:{rejected}",
                "status": "ROUTED",
            },
            {
                **common,
                "id": invalid,
                "strategy_version_id": instance.current_version_id,
                "signal_time": now - timedelta(minutes=2),
                "received_at": now - timedelta(minutes=2),
                "idempotency_key": f"test:{invalid}",
                "status": "INVALID",
                "reject_code": "INVALID_SIGNAL",
                "reject_detail": "stop_loss must be below entry for a LONG",
                "raw_payload": {"signal": "LONG", "entry": str(last.close), "stop_loss": "9999"},
            },
        ],
    )
    session.add(
        m.RiskDecisionRow(
            id=uuid7(),
            signal_id=rejected,
            account_id=account.id,
            strategy_instance_id="demo_sma_fast",
            account_config_version_id=account.current_config_version_id,
            decided_at=now - timedelta(minutes=1),
            approved=False,
            primary_reason="MAX_OPEN_POSITIONS",
            rule_results=[{"rule": "max_open_positions", "passed": False, "limit": 1}],
            account_state={"open_positions": 1},
            run_id=run_id,
            correlation_id=new_correlation_id(),
        )
    )
    await session.flush()
    return rejected, invalid
