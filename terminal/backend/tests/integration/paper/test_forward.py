"""Forward paper trading against PostgreSQL: live bars from fake providers on a fake
clock, every instance in its dedicated account, restart by replay, kill switches."""

from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import func, select, text, update

from kterminal.config.settings import DatabaseSettings
from kterminal.db import models as m
from kterminal.db.session import Database
from kterminal.paper.forward import SessionMismatchError, SessionVerificationError
from kterminal.paper.pg_forward import PostgresForwardStore
from kterminal.paper.runtime import RuntimeLockedError
from tests.fixtures.forward import FakeTime
from tests.integration.paper.conftest import _admin
from tests.integration.paper.forward_helpers import (
    MIN,
    START,
    kill_switch_action,
    lab_config,
    providers,
    run_runtime,
    session_dump,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def second_database(database_url: str) -> AsyncIterator[Database]:
    """Another throwaway database (for comparing two runs of the same session)."""
    from sqlalchemy.engine import make_url

    from kterminal.core.ids import uuid7
    from kterminal.db import migrate

    name = f"kt_lab_{uuid7().hex[-12:]}"
    await _admin(database_url, f'CREATE DATABASE "{name}"')
    url = make_url(database_url).set(database=name).render_as_string(hide_password=False)
    db = Database(DatabaseSettings.model_validate({"url": url}), application_name="kt-tests")
    try:
        await migrate.upgrade(url)
        yield db
    finally:
        await db.dispose()
        await _admin(database_url, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


async def only_session(database: Database) -> Any:
    sessions = await PostgresForwardStore(database).sessions()
    assert len(sessions) == 1
    return sessions[0]


async def scalar(database: Database, query: str, **params: Any) -> Any:
    async with database.session() as session:
        return (await session.execute(text(query), params)).scalar_one()


async def test_a_session_paper_trades_live_bars_in_the_dedicated_accounts(
    database: Database,
) -> None:
    clock = FakeTime(START + timedelta(seconds=5))
    runtime = await run_runtime(database, clock, lab_config(), until=START + 90 * MIN)
    stored = await only_session(database)
    assert stored.status == "RUNNING"  # a forward session stays open between runs
    plan = stored.config["plan"]
    assert set(plan["versions"]) == {"sma_gold", "breakout_near", "scripted_both"}
    assert datetime.fromisoformat(stored.progress["processed_through"]) == START + 89 * MIN

    async with database.session() as session:
        accounts = {
            row.strategy_instance_id: row
            for row in (await session.scalars(select(m.AccountRow))).all()
        }
        assert set(accounts) == {"sma_gold", "breakout_near", "scripted_both"}  # dedicated only
        for instance, account in accounts.items():
            assert account.name == f"Paper 50K · {instance}"
            assert plan["accounts"][instance]["account_id"] == str(account.id)
        trades = (
            await session.scalars(select(m.TradeRow).where(m.TradeRow.run_id == stored.run_id))
        ).all()
        assert {t.strategy_instance_id for t in trades} >= {"sma_gold", "scripted_both"}
        assert all(t.account_id == accounts[t.strategy_instance_id].id for t in trades)
        # every processed bar is in the candles table (the session's input log)
        live = await session.scalar(
            select(func.count()).select_from(m.CandleRow).where(m.CandleRow.ts >= START)
        )
        assert live == stored.progress["input_bars"] > 100
        gold_closed = await session.scalar(
            select(func.count())
            .select_from(m.CandleRow)
            .where(m.CandleRow.instrument == "XAUUSD", m.CandleRow.ts >= START + 60 * MIN)
        )
        assert gold_closed == 0  # the daily break: nothing delivered, nothing waited for
        for account in accounts.values():  # balance = Σ ledger, deposit included
            total = await session.scalar(
                select(func.sum(m.AccountLedgerRow.amount)).where(
                    m.AccountLedgerRow.account_id == account.id
                )
            )
            latest = await session.scalar(
                select(m.AccountLedgerRow.balance_after)
                .where(m.AccountLedgerRow.account_id == account.id)
                .order_by(m.AccountLedgerRow.seq.desc())
                .limit(1)
            )
            assert total == latest

    status = await PostgresForwardStore(database).read_status()
    assert status is not None
    assert status == runtime.status_document(datetime.fromisoformat(status["updated_at"]))
    assert status["status"] == "stopped"
    assert status["run_id"] == str(stored.run_id)
    assert status["last_batch_close"] == (START + 89 * MIN).isoformat()
    assert status["instruments"]["XAUUSD"]["state"] == "closed"
    assert status["instruments"]["NEARUSD"] == {
        "provider": "fake-crypto",
        "last_bar_open": (START + 88 * MIN).isoformat(),
        "lag_seconds": 62.0,  # stopped while waiting for the next minute
        "state": "ok",
        "last_error": None,
    }
    assert status["instances"]["scripted_both"] == {
        "state": "STOPPED",
        "fault": None,
        "account_id": plan["accounts"]["scripted_both"]["account_id"],
    }
    assert status["kill_switch"] == {"global": False, "accounts": [], "strategies": []}


async def test_a_restarted_session_ends_exactly_like_an_uninterrupted_one(
    database: Database, second_database: Database
) -> None:
    """Stop mid-session, restart ten minutes later (replay, verification, catch-up) and
    continue: every row the session wrote is identical to an uninterrupted run — kill
    switch changes (one before the stop, one after), its flattening and a late bar
    included."""
    end = START + 100 * MIN

    def scenario(db: Database) -> tuple[FakeTime, dict[str, Any]]:
        clock = FakeTime(START + timedelta(seconds=5))
        clock.at(START + 20 * MIN, kill_switch_action(db, active=True, close=True))
        clock.at(START + 70 * MIN, kill_switch_action(db, active=False))
        feeds = providers(clock)
        feeds["NEARUSD"].hold("NEARUSD", START + 12 * MIN, START + 14 * MIN)  # a late bar
        return clock, feeds

    clock, feeds = scenario(database)
    await run_runtime(database, clock, lab_config(), until=end, feeds=feeds)

    clock, feeds = scenario(second_database)
    await run_runtime(second_database, clock, lab_config(), until=START + 40 * MIN, feeds=feeds)
    clock.current = START + 50 * MIN  # the engine was down for ten minutes
    resumed = await run_runtime(second_database, clock, lab_config(), until=end, feeds=feeds)
    assert resumed.session is not None and resumed.session.resumed

    uninterrupted = await only_session(database)
    restarted = await only_session(second_database)
    one = await session_dump(database, uninterrupted.run_id)
    two = await session_dump(second_database, restarted.run_id)
    assert one.keys() == two.keys()
    for table in one:
        assert len(one[table]) == len(two[table]), table
        for row_one, row_two in zip(one[table], two[table], strict=True):
            assert row_one == row_two, table
    assert any(d["primary_reason"] == "KILL_SWITCH_ACTIVE" for d in one["risk_decisions"])
    assert any(t["exit_reason"] == "KILL_SWITCH" for t in one["trades"])
    assert {o["purpose"] for o in one["orders"]} >= {"ENTRY", "FLATTEN", "EXIT"}
    assert [a["action"] for a in one["audit"]] == ["killswitch.applied"] * 2


async def test_resuming_with_changed_strategy_settings_is_refused_until_a_new_session(
    database: Database,
) -> None:
    clock = FakeTime(START + timedelta(seconds=5))
    await run_runtime(database, clock, lab_config(), until=START + 88 * MIN)
    old = await only_session(database)
    async with database.session() as session:
        open_before = (
            await session.scalars(
                select(m.TradeRow).where(
                    m.TradeRow.run_id == old.run_id, m.TradeRow.status == "OPEN"
                )
            )
        ).all()
    assert open_before  # the scripted short opened at minute 85 is still open

    changed = lab_config(fast=4)  # a new strategy version of sma_gold
    with pytest.raises(SessionMismatchError, match="sma_gold has a new strategy version") as err:
        await run_runtime(database, clock, changed, until=START + 95 * MIN)
    assert "kterminal paper start --new-session" in str(err.value)
    status = await PostgresForwardStore(database).read_status()
    assert status is not None and status["status"] == "error"
    assert "new strategy version" in status["error"]

    clock.current = START + 95 * MIN
    await run_runtime(database, clock, changed, until=START + 100 * MIN, new_session=True)
    store = PostgresForwardStore(database)
    sessions = {s.status: s for s in await store.sessions()}
    assert set(sessions) == {"COMPLETED", "RUNNING"}
    ended, new = sessions["COMPLETED"], sessions["RUNNING"]
    assert ended.run_id == old.run_id
    last_minute = datetime.fromisoformat(old.progress["processed_through"])
    assert last_minute == START + 87 * MIN
    assert ended.finished_at == last_minute
    assert ended.summary is not None and ended.summary["positions_closed"] == len(open_before)
    async with database.session() as session:
        closed = (
            await session.scalars(
                select(m.TradeRow).where(m.TradeRow.id.in_([t.id for t in open_before]))
            )
        ).all()
        assert {(t.status, t.exit_reason, t.exit_time) for t in closed} == {
            ("CLOSED", "RUN_END", last_minute)
        }
        open_now = await session.scalar(
            select(func.count())
            .select_from(m.TradeRow)
            .where(m.TradeRow.run_id == old.run_id, m.TradeRow.status == "OPEN")
        )
        assert open_now == 0
    # the new session trades the same dedicated accounts, from their ledger balance
    old_accounts = old.config["plan"]["accounts"]
    new_accounts = new.config["plan"]["accounts"]
    assert {k: v["account_id"] for k, v in old_accounts.items()} == {
        k: v["account_id"] for k, v in new_accounts.items()
    }
    async with database.session() as session:
        for account in new_accounts.values():  # opened from the ledger after the closes
            opening = await session.scalar(
                select(m.AccountLedgerRow.balance_after)
                .where(
                    m.AccountLedgerRow.account_id == account["account_id"],
                    m.AccountLedgerRow.run_id.is_distinct_from(new.run_id),
                )
                .order_by(m.AccountLedgerRow.seq.desc())
                .limit(1)
            )
            assert Decimal(account["balance"]) == opening
    assert new.config["plan"]["versions"]["sma_gold"] != old.config["plan"]["versions"]["sma_gold"]


async def test_a_session_whose_records_were_altered_refuses_to_continue(
    database: Database,
) -> None:
    clock = FakeTime(START + timedelta(seconds=5))
    await run_runtime(database, clock, lab_config(), until=START + 30 * MIN)
    stored = await only_session(database)
    async with database.session() as session:
        first_pnl = await session.scalar(
            select(func.min(m.AccountLedgerRow.seq)).where(
                m.AccountLedgerRow.run_id == stored.run_id,
                m.AccountLedgerRow.kind == "REALIZED_PNL",
            )
        )
        await session.execute(
            update(m.AccountLedgerRow)
            .where(m.AccountLedgerRow.seq == first_pnl)
            .values(amount=m.AccountLedgerRow.amount + 1)
        )
    with pytest.raises(SessionVerificationError, match="ledger"):
        await run_runtime(database, clock, lab_config(), until=START + 35 * MIN)


async def test_a_session_whose_input_log_changed_refuses_to_continue(database: Database) -> None:
    clock = FakeTime(START + timedelta(seconds=5))
    await run_runtime(database, clock, lab_config(), until=START + 20 * MIN)
    async with database.session() as session:
        await session.execute(
            text("DELETE FROM candles WHERE instrument = 'NEARUSD' AND ts = :t"),
            {"t": START + 7 * MIN},
        )
    with pytest.raises(SessionVerificationError, match="input log"):
        await run_runtime(database, clock, lab_config(), until=START + 25 * MIN)


async def test_only_one_runtime_runs_against_a_database(database: Database) -> None:
    from kterminal.db.locks import AdvisoryLock
    from kterminal.paper.runtime import PAPER_RUNTIME_LOCK

    lock = AdvisoryLock(database.engine, PAPER_RUNTIME_LOCK)
    assert await lock.try_acquire()
    try:
        with pytest.raises(RuntimeLockedError, match="already running"):
            await run_runtime(database, FakeTime(START), lab_config(), until=START + 5 * MIN)
    finally:
        await lock.release()


async def test_a_subprocess_hosted_instance_survives_a_restart(database: Database) -> None:
    config = lab_config(host="subprocess")
    clock = FakeTime(START + timedelta(seconds=5))
    await run_runtime(database, clock, config, until=START + 25 * MIN)
    clock.current = START + 30 * MIN
    runtime = await run_runtime(database, clock, config, until=START + 45 * MIN)
    assert runtime.session is not None and runtime.session.resumed
    stored = await only_session(database)
    assert datetime.fromisoformat(stored.progress["processed_through"]) == START + 44 * MIN
    trades = await scalar(
        database,
        "SELECT count(*) FROM trades WHERE run_id = :r AND strategy_instance_id = 'sma_gold'",
        r=stored.run_id,
    )
    assert trades > 0
    status = await PostgresForwardStore(database).read_status()
    assert status is not None and status["instances"]["sma_gold"]["fault"] is None
