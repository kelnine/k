"""Monthly range partitions for the high-volume tables.

``webhook_events``, ``equity_snapshots``, ``order_events``, ``candles`` and
``audit_log`` are declared ``PARTITION BY RANGE`` on a timestamp from day one
(see :data:`kterminal.db.models.PARTITION_KEYS`), so retention is a cheap
``DROP TABLE <partition>`` instead of a slow, bloating ``DELETE``.

The migration creates each table with a ``DEFAULT`` partition, which accepts
any row, so a missing monthly partition never loses data. Monthly partitions
named ``<table>_pYYYYMM`` (UTC months, ``[first day, first day of next
month)``) are created ahead of time by :func:`ensure_monthly_partitions`,
which the worker runs at start-up and daily. It is idempotent and serialised
by an advisory lock, so any number of processes may call it.

If the default partition already holds rows that belong to a month being
created (e.g. bars imported for a month before its partition existed),
PostgreSQL would refuse to create the partition. Those rows are moved into the
new partition in the same transaction. Rows of the append-only ``audit_log``
are never moved automatically: that requires an operator decision.
"""

import re
from datetime import UTC, date, datetime
from typing import Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from kterminal.core.errors import KTerminalError
from kterminal.db.locks import lock_key
from kterminal.db.models import (
    PARTITION_KEYS,
    AuditLogRow,
    audit_guard_triggers_ddl,
    default_partition_name,
)
from kterminal.observability.logging import get_logger

_log = get_logger(__name__)

PARTITIONED_TABLES: Final[tuple[str, ...]] = tuple(PARTITION_KEYS)
"""Every range-partitioned table, in a stable order."""

PARTITION_LOCK: Final = "kterminal.db.partitions"

_PARTITION_NAME = re.compile(
    rf"^(?P<table>{'|'.join(map(re.escape, PARTITIONED_TABLES))})_(?:default|p\d{{6}})$"
)


class PartitionError(KTerminalError):
    """A partition could not be created safely."""


def is_partition_name(name: str) -> bool:
    """True for ``<partitioned table>_default`` and ``<partitioned table>_pYYYYMM``.

    Partitions are created at run time and are not part of the declarative
    model, so schema comparison (``migrate.check``, autogenerate) skips them.
    """
    return _PARTITION_NAME.fullmatch(name) is not None


def partition_name(table: str, year: int, month: int) -> str:
    return f"{table}_p{year:04d}{month:02d}"


def _add_months(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def month_range(today: date, months_back: int, months_ahead: int) -> list[tuple[int, int]]:
    """``(year, month)`` from ``months_back`` before ``today``'s month to ``months_ahead`` after."""
    if months_back < 0 or months_ahead < 0:
        raise ValueError("months_back and months_ahead must be >= 0")
    return [
        _add_months(today.year, today.month, offset)
        for offset in range(-months_back, months_ahead + 1)
    ]


def _bound(year: int, month: int) -> str:
    """A UTC month boundary literal, independent of the session's TimeZone setting."""
    return f"{year:04d}-{month:02d}-01 00:00:00+00"


def _instant(year: int, month: int) -> datetime:
    return datetime(year, month, 1, tzinfo=UTC)


async def ensure_monthly_partitions(
    target: AsyncEngine | AsyncConnection | AsyncSession,
    *,
    today: date,
    months_back: int = 1,
    months_ahead: int = 3,
    tables: tuple[str, ...] = PARTITIONED_TABLES,
) -> list[str]:
    """Create any missing ``<table>_pYYYYMM`` partitions; return the names created.

    With an engine, the work runs in its own transaction and is committed. With
    a connection or session, it joins the caller's transaction and the caller
    commits (PostgreSQL DDL is transactional).
    """
    unknown = sorted(set(tables) - set(PARTITIONED_TABLES))
    if unknown:
        raise ValueError(f"not partitioned tables: {', '.join(unknown)}")
    months = month_range(today, months_back, months_ahead)
    if isinstance(target, AsyncEngine):
        async with target.begin() as conn:
            return await _ensure(conn, tables, months)
    conn = await target.connection() if isinstance(target, AsyncSession) else target
    return await _ensure(conn, tables, months)


async def _ensure(
    conn: AsyncConnection, tables: tuple[str, ...], months: list[tuple[int, int]]
) -> list[str]:
    await conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": lock_key(PARTITION_LOCK)})
    created: list[str] = []
    for table in tables:
        for year, month in months:
            name = partition_name(table, year, month)
            if await _exists(conn, name):
                continue
            await _create_partition(conn, table, name, year, month)
            created.append(name)
    if created:
        _log.info("db.partitions_created", partitions=created)
    return created


async def _exists(conn: AsyncConnection, name: str) -> bool:
    found = (await conn.execute(text("SELECT to_regclass(:n)"), {"n": name})).scalar_one()
    return found is not None


async def _create_partition(
    conn: AsyncConnection, table: str, name: str, year: int, month: int
) -> None:
    key = PARTITION_KEYS[table]
    next_year, next_month = _add_months(year, month, 1)
    low, high = _bound(year, month), _bound(next_year, next_month)
    window = {"low": _instant(year, month), "high": _instant(next_year, next_month)}
    default = default_partition_name(table)
    stranded = (
        await conn.execute(
            text(
                f"SELECT count(*) FROM {default} "  # noqa: S608 - identifiers are constants
                f"WHERE {key} >= :low AND {key} < :high"
            ),
            window,
        )
    ).scalar_one()
    bounds = f"FOR VALUES FROM ('{low}') TO ('{high}')"
    if not stranded:
        await conn.execute(text(f"CREATE TABLE {name} PARTITION OF {table} {bounds}"))
    elif table == AuditLogRow.__tablename__:
        raise PartitionError(
            f"{default} holds {stranded} audit row(s) for {year:04d}-{month:02d}; the audit "
            "log is append-only, so moving them into a new partition needs an operator "
            "(table owner) to do it deliberately"
        )
    else:
        # A partition cannot be created over rows sitting in the default partition:
        # build it as a plain table, move the rows, then attach it.
        _log.warning("db.partition_rows_moved", table=table, partition=name, rows=int(stranded))
        await conn.execute(
            text(f"CREATE TABLE {name} (LIKE {table} INCLUDING DEFAULTS INCLUDING CONSTRAINTS)")
        )
        await conn.execute(
            text(
                f"WITH moved AS (DELETE FROM {default} "  # noqa: S608 - constants
                f"WHERE {key} >= :low AND {key} < :high "
                f"RETURNING *) INSERT INTO {name} SELECT * FROM moved"
            ),
            window,
        )
        await conn.execute(text(f"ALTER TABLE {table} ATTACH PARTITION {name} {bounds}"))
    if table == AuditLogRow.__tablename__:
        # Row-level guards are cloned from the parent; TRUNCATE guards are per table.
        for statement in audit_guard_triggers_ddl(name):
            await conn.execute(text(statement))
