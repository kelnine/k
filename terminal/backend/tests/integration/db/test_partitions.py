"""Monthly partitions: idempotent creation, routing by UTC month, the DEFAULT catch-all."""

from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import insert, text
from sqlalchemy.ext.asyncio import AsyncSession

from kterminal.db.models import CandleRow
from kterminal.db.partitions import (
    PARTITIONED_TABLES,
    PartitionError,
    ensure_monthly_partitions,
    month_range,
    partition_name,
)

pytestmark = pytest.mark.integration

TODAY = date(2026, 10, 6)


async def _insert_candle(session: AsyncSession, ts: datetime, instrument: str = "XAUUSD") -> None:
    price = Decimal("2650.00")
    await session.execute(
        insert(CandleRow).values(
            instrument=instrument,
            timeframe="1m",
            source="test",
            ts=ts,
            open=price,
            high=price,
            low=price,
            close=price,
            volume=Decimal(1),
        )
    )


async def _partition_of(session: AsyncSession, ts: datetime) -> str:
    return str(
        (
            await session.execute(
                text("SELECT tableoid::regclass::text FROM candles WHERE ts = :ts"), {"ts": ts}
            )
        ).scalar_one()
    )


async def test_creates_every_month_for_every_table_once(session: AsyncSession) -> None:
    created = await ensure_monthly_partitions(session, today=TODAY)
    months = ["202609", "202610", "202611", "202612", "202701"]
    assert sorted(created) == sorted(f"{t}_p{m}" for t in PARTITIONED_TABLES for m in months)

    assert await ensure_monthly_partitions(session, today=TODAY) == []
    # Later runs only add what is new.
    assert sorted(await ensure_monthly_partitions(session, today=date(2026, 11, 1))) == sorted(
        f"{t}_p202702" for t in PARTITIONED_TABLES
    )


async def test_rows_land_in_the_partition_of_their_utc_month(session: AsyncSession) -> None:
    await ensure_monthly_partitions(session, today=TODAY)
    new_york = timezone(timedelta(hours=-4))
    cases = {
        datetime(2026, 10, 15, 12, tzinfo=UTC): "candles_p202610",
        datetime(2026, 9, 1, 0, 0, tzinfo=UTC): "candles_p202609",  # inclusive lower bound
        datetime(2026, 9, 30, 23, 59, 59, tzinfo=UTC): "candles_p202609",
        # 23:30 on 31 Oct in New York (EDT) is already 1 Nov in UTC.
        datetime(2026, 10, 31, 23, 30, tzinfo=new_york): "candles_p202611",
        datetime(2027, 1, 31, 23, 59, tzinfo=UTC): "candles_p202701",
        # Outside the created range: the DEFAULT partition catches them.
        datetime(2026, 8, 31, 23, 59, tzinfo=UTC): "candles_default",
        datetime(2030, 1, 1, tzinfo=UTC): "candles_default",
    }
    for ts in cases:
        await _insert_candle(session, ts)
    for ts, partition in cases.items():
        assert await _partition_of(session, ts) == partition, ts


async def test_rows_in_the_default_partition_move_into_a_new_partition(
    session: AsyncSession,
) -> None:
    stranded = datetime(2027, 6, 15, 9, 30, tzinfo=UTC)
    await _insert_candle(session, stranded)
    await _insert_candle(session, datetime(2031, 1, 1, tzinfo=UTC))  # stays in default
    assert await _partition_of(session, stranded) == "candles_default"

    created = await ensure_monthly_partitions(
        session, today=date(2027, 6, 1), months_back=0, months_ahead=0, tables=("candles",)
    )
    assert created == ["candles_p202706"]
    assert await _partition_of(session, stranded) == "candles_p202706"
    count = (await session.execute(text("SELECT count(*) FROM candles_default"))).scalar_one()
    assert count == 1
    # The attached partition enforces the parent's constraints and primary key.
    with pytest.raises(Exception, match="duplicate key"):
        async with session.begin_nested():
            await _insert_candle(session, stranded)


async def test_audit_rows_are_never_moved_automatically(session: AsyncSession) -> None:
    await session.execute(
        text(
            "INSERT INTO audit_log (ts, actor, action, entity_type, entity_id, data, "
            "prev_hash, hash) VALUES ('2032-03-01 00:00+00', 'test', 'x', 't', '1', '{}', "
            "'0', '0')"
        )
    )
    with pytest.raises(PartitionError, match="append-only"):
        await ensure_monthly_partitions(
            session, today=date(2032, 3, 1), months_back=0, months_ahead=0, tables=("audit_log",)
        )


async def test_unknown_tables_and_bad_ranges_are_rejected(session: AsyncSession) -> None:
    with pytest.raises(ValueError, match="not partitioned"):
        await ensure_monthly_partitions(session, today=TODAY, tables=("trades",))
    with pytest.raises(ValueError, match=">= 0"):
        month_range(TODAY, -1, 3)


def test_month_range_crosses_year_boundaries() -> None:
    assert month_range(date(2026, 12, 31), 2, 2) == [
        (2026, 10),
        (2026, 11),
        (2026, 12),
        (2027, 1),
        (2027, 2),
    ]
    assert partition_name("audit_log", 2027, 1) == "audit_log_p202701"
