"""The migration builds exactly the schema the models describe — including what Alembic misses.

``migrate.check()`` relies on Alembic's autogenerate comparison, which does not
look at CHECK constraints, server defaults, foreign-key options, partitioning,
triggers or functions. Here the migrated schema (``public``) is compared with a
schema built by ``metadata.create_all`` straight from the models, catalog entry
by catalog entry, so any drift between ``models.py`` and the migration fails.
"""

from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from kterminal.db.models import Base
from tests.integration.db.conftest import async_dsn

pytestmark = pytest.mark.integration

MODELS_SCHEMA = "kt_drift_models"

_COLUMNS = text(
    """
    SELECT c.relname, a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull,
           a.attidentity, a.attgenerated, pg_get_expr(d.adbin, d.adrelid)
    FROM pg_attribute a
    JOIN pg_class c ON c.oid = a.attrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
    WHERE n.nspname = :schema AND c.relkind IN ('r', 'p') AND a.attnum > 0
      AND NOT a.attisdropped AND c.relname <> 'alembic_version'
    """
)
_CONSTRAINTS = text(
    """
    SELECT c.relname, k.conname, k.contype::text, pg_get_constraintdef(k.oid, true)
    FROM pg_constraint k
    JOIN pg_class c ON c.oid = k.conrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = :schema AND c.relname <> 'alembic_version'
    """
)
_INDEXES = text(
    """
    SELECT tablename, indexname, indexdef FROM pg_indexes
    WHERE schemaname = :schema AND tablename <> 'alembic_version'
    """
)
_PARTITIONING = text(
    """
    SELECT c.relname, c.relkind::text, pg_get_partkeydef(c.oid),
           pg_get_expr(c.relpartbound, c.oid), p.relname
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    LEFT JOIN pg_inherits i ON i.inhrelid = c.oid
    LEFT JOIN pg_class p ON p.oid = i.inhparent
    WHERE n.nspname = :schema AND c.relkind IN ('r', 'p') AND c.relname <> 'alembic_version'
    """
)
_TRIGGERS = text(
    """
    SELECT c.relname, t.tgname, pg_get_triggerdef(t.oid), t.tgenabled::text
    FROM pg_trigger t
    JOIN pg_class c ON c.oid = t.tgrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = :schema AND NOT t.tgisinternal
    """
)
_FUNCTIONS = text(
    """
    SELECT p.proname, regexp_replace(p.prosrc, '\\s+', ' ', 'g')
    FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = :schema
    """
)


async def _describe(conn: AsyncConnection, schema: str) -> dict[str, set[tuple[Any, ...]]]:
    """Every catalog fact about ``schema``, with the schema name itself removed."""

    def clean(value: Any) -> Any:
        return value.replace(f"{schema}.", "") if isinstance(value, str) else value

    description: dict[str, set[tuple[Any, ...]]] = {}
    for name, query in (
        ("columns", _COLUMNS),
        ("constraints", _CONSTRAINTS),
        ("indexes", _INDEXES),
        ("partitioning", _PARTITIONING),
        ("triggers", _TRIGGERS),
        ("functions", _FUNCTIONS),
    ):
        rows = await conn.execute(query, {"schema": schema})
        description[name] = {tuple(clean(v) for v in row) for row in rows}
    return description


@pytest.fixture
async def models_schema(migrated_url: str) -> AsyncIterator[str]:
    """A second schema built by ``metadata.create_all`` from the models."""
    admin = create_async_engine(async_dsn(migrated_url), poolclass=pool.NullPool)
    scoped = create_async_engine(
        async_dsn(migrated_url),
        poolclass=pool.NullPool,
        connect_args={"server_settings": {"search_path": MODELS_SCHEMA}},
    )
    try:
        async with admin.begin() as conn:
            await conn.execute(text(f"DROP SCHEMA IF EXISTS {MODELS_SCHEMA} CASCADE"))
            await conn.execute(text(f"CREATE SCHEMA {MODELS_SCHEMA}"))
        async with scoped.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield MODELS_SCHEMA
    finally:
        async with admin.begin() as conn:
            await conn.execute(text(f"DROP SCHEMA IF EXISTS {MODELS_SCHEMA} CASCADE"))
        await admin.dispose()
        await scoped.dispose()


@pytest.mark.parametrize(
    "aspect", ["columns", "constraints", "indexes", "partitioning", "triggers", "functions"]
)
async def test_migration_matches_the_models_in_every_catalog_detail(
    migrated_url: str, models_schema: str, aspect: str
) -> None:
    engine = create_async_engine(async_dsn(migrated_url), poolclass=pool.NullPool)
    try:
        async with engine.connect() as conn:
            # Monthly partitions are created at run time, not by the migration.
            migrated = {
                row
                for row in (await _describe(conn, "public"))[aspect]
                if not any(isinstance(v, str) and "_p20" in v for v in row[:2])
            }
            models = (await _describe(conn, models_schema))[aspect]
    finally:
        await engine.dispose()
    only_migration = sorted(migrated - models, key=repr)
    only_models = sorted(models - migrated, key=repr)
    assert not only_migration and not only_models, (
        f"{aspect} differ\n  only in the migration: {only_migration}\n"
        f"  only in the models: {only_models}"
    )
