"""The Alembic migration and the declarative models describe the same schema."""

import pytest
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from kterminal.brokers.base import OrderStatus, TimeInForce
from kterminal.db import migrate
from kterminal.db.models import (
    ORDER_STATUSES,
    PARTITION_KEYS,
    TIME_IN_FORCE,
    Base,
)
from kterminal.db.partitions import PARTITIONED_TABLES, is_partition_name
from tests.integration.db.conftest import async_dsn

pytestmark = pytest.mark.integration

POSTGRES_MAX_IDENTIFIER = 63


async def _tables(engine: AsyncEngine) -> dict[str, str]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT c.relname, c.relkind::text FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')"
            )
        )
        return dict(rows.all())


async def test_upgrade_downgrade_upgrade_round_trip(migrated_url: str, engine: AsyncEngine) -> None:
    head = migrate.head_revision()
    assert head == "0001"
    assert await migrate.current(migrated_url) == head

    tables = await _tables(engine)
    model_tables = set(Base.metadata.tables)
    assert model_tables <= set(tables)
    for table in PARTITIONED_TABLES:
        assert tables[table] == "p", f"{table} must be a partitioned table"
        assert f"{table}_default" in tables

    await migrate.downgrade(migrated_url, "base")
    try:
        assert await migrate.current(migrated_url) is None
        assert set(await _tables(engine)) == {"alembic_version"}
        async with engine.connect() as conn:
            functions = (
                await conn.execute(
                    text("SELECT count(*) FROM pg_proc WHERE proname = 'kt_audit_log_append_only'")
                )
            ).scalar_one()
        assert functions == 0
    finally:
        await migrate.upgrade(migrated_url)

    assert await migrate.current(migrated_url) == head
    assert await migrate.check(migrated_url) == []


async def test_check_reports_no_differences_after_upgrade(migrated_url: str) -> None:
    assert await migrate.check(migrated_url) == []


async def test_check_reports_drift(migrated_url: str, engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE venues ADD COLUMN surprise integer"))
    try:
        differences = await migrate.check(migrated_url)
        assert any("remove_column" in d and "surprise" in d for d in differences), differences
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("ALTER TABLE venues DROP COLUMN surprise"))
    assert await migrate.check(migrated_url) == []


async def test_check_reports_a_revision_mismatch(migrated_url: str, engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE alembic_version SET version_num = '0000'"))
    try:
        differences = await migrate.check(migrated_url)
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("UPDATE alembic_version SET version_num = '0001'"))
    assert differences == ["revision: database is at '0000', code expects '0001'"]


async def test_metadata_create_all_builds_the_same_partitions_and_guards(
    migrated_url: str,
) -> None:
    """``metadata.create_all`` (used by tools and tests) adds DEFAULT partitions and guards."""
    schema = "kt_create_all_test"
    admin = create_async_engine(async_dsn(migrated_url), poolclass=pool.NullPool)
    scoped = create_async_engine(
        async_dsn(migrated_url),
        poolclass=pool.NullPool,
        connect_args={"server_settings": {"search_path": schema}},
    )
    try:
        async with admin.begin() as conn:
            await conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
            await conn.execute(text(f"CREATE SCHEMA {schema}"))
        async with scoped.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            names = {
                row[0]
                for row in await conn.execute(
                    text(
                        "SELECT c.relname FROM pg_class c JOIN pg_namespace n "
                        "ON n.oid = c.relnamespace WHERE n.nspname = :s AND c.relkind IN ('r','p')"
                    ),
                    {"s": schema},
                )
            }
            triggers = {
                row[0]
                for row in await conn.execute(
                    text(
                        "SELECT t.tgname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
                        "JOIN pg_namespace n ON n.oid = c.relnamespace "
                        "WHERE n.nspname = :s AND NOT t.tgisinternal"
                    ),
                    {"s": schema},
                )
            }
        assert {f"{t}_default" for t in PARTITIONED_TABLES} <= names
        assert {"audit_log_append_only", "audit_log_no_truncate"} <= triggers
        assert "audit_log_default_no_truncate" in triggers
        async with scoped.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
    finally:
        async with admin.begin() as conn:
            await conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        await admin.dispose()
        await scoped.dispose()


def test_constraint_and_index_names_fit_postgres_identifiers() -> None:
    names: list[str] = []
    for table in Base.metadata.tables.values():
        names.extend(str(c.name) for c in table.constraints)
        names.extend(str(i.name) for i in table.indexes)
    assert all(name and name != "None" for name in names)
    too_long = [n for n in names if len(n) > POSTGRES_MAX_IDENTIFIER]
    assert not too_long
    assert len(names) == len(set(names)), "constraint/index names must be unique"


def test_enumerations_mirror_their_owners() -> None:
    assert tuple(s.value for s in OrderStatus) == ORDER_STATUSES
    assert tuple(t.value for t in TimeInForce) == TIME_IN_FORCE


def test_partitioned_tables_are_declared_consistently() -> None:
    assert set(PARTITIONED_TABLES) == set(PARTITION_KEYS)
    for table, key in PARTITION_KEYS.items():
        metadata_table = Base.metadata.tables[table]
        assert metadata_table.dialect_options["postgresql"]["partition_by"] == f"RANGE ({key})"
        # A partitioned table's primary key must contain its partition key.
        assert key in metadata_table.primary_key.columns
        # Nothing may reference a partitioned table (PostgreSQL cannot enforce it cheaply).
        for other in Base.metadata.tables.values():
            for fk in other.foreign_keys:
                assert fk.column.table.name != table, f"{other.name} references {table}"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("candles_default", True),
        ("audit_log_p202610", True),
        ("webhook_events_p202701", True),
        ("candles", False),
        ("candles_p2026", False),
        ("trades_default", False),
        ("signals_p202610", False),
    ],
)
def test_partition_names_are_recognised(name: str, expected: bool) -> None:
    assert is_partition_name(name) is expected
