"""Requires PostgreSQL: set KT_TEST_DATABASE_URL (CI provides a service container)."""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text

from kterminal.config.settings import DatabaseSettings
from kterminal.db.locks import AdvisoryLock, lock_key
from kterminal.db.session import Database

pytestmark = pytest.mark.integration


@pytest.fixture
async def db(database_url: str) -> AsyncIterator[Database]:
    database = Database(DatabaseSettings(url=database_url), application_name="kterminal-tests")
    yield database
    await database.dispose()


async def test_ping(db: Database) -> None:
    assert await db.ping() is True


async def test_ping_reports_unreachable_database() -> None:
    unreachable = Database(
        DatabaseSettings(url="postgresql://u:p@127.0.0.1:1/none", connect_timeout_s=1)
    )
    assert await unreachable.ping(timeout_s=2) is False
    await unreachable.dispose()


async def test_session_commits_and_rolls_back(db: Database) -> None:
    async with db.session() as session:
        await session.execute(text("CREATE TEMP TABLE IF NOT EXISTS t (v int)"))
    async with db.session() as session:
        await session.execute(text("INSERT INTO t VALUES (1)"))

    async def failing_unit_of_work() -> None:
        async with db.session() as session:
            await session.execute(text("INSERT INTO t VALUES (2)"))
            raise RuntimeError("rollback")

    with pytest.raises(RuntimeError):
        await failing_unit_of_work()


@pytest.mark.parametrize("name", ["kterminal.engine.leader", "test.lock.negative-key"])
async def test_advisory_lock_is_exclusive_and_verifiable(db: Database, name: str) -> None:
    first = AdvisoryLock(db.engine, name)
    second = AdvisoryLock(db.engine, name)
    try:
        assert await first.try_acquire() is True
        assert await first.try_acquire() is True  # re-entrant for the holder
        assert await first.verify() is True
        assert await second.try_acquire() is False
        assert second.held is False

        await first.release()
        assert first.held is False
        assert await first.verify() is False
        assert await second.try_acquire() is True  # standby takes over
    finally:
        await first.release()
        await second.release()


async def test_lock_key_handles_negative_keys() -> None:
    keys = {lock_key(f"lock-{i}") for i in range(64)}
    assert any(k < 0 for k in keys)
    assert all(-(2**63) <= k < 2**63 for k in keys)


async def test_losing_the_connection_means_losing_leadership(db: Database) -> None:
    lock = AdvisoryLock(db.engine, "test.lock.connection-loss")
    assert await lock.try_acquire()
    # Simulate the database killing our session (failover, network partition, admin action).
    async with db.engine.connect() as admin:
        await admin.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_locks WHERE locktype = 'advisory' "
                "AND objsubid = 1 AND ((classid::bigint << 32) | objid::bigint) = :k"
            ),
            {"k": lock.key},
        )
    assert await lock.verify() is False
    assert lock.held is False
    standby = AdvisoryLock(db.engine, "test.lock.connection-loss")
    assert await standby.try_acquire() is True
    await standby.release()
