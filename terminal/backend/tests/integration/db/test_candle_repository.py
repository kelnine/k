"""Stored candles: the forward sessions' input log, imported history and warm-up bars."""

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from kterminal.db.models import CandleRow
from kterminal.db.repositories.candles import (
    CandleCoverage,
    candle_coverage,
    insert_candles,
    latest_candle_open,
    load_candles,
    plain_bar,
)
from kterminal.domain.market import Bar
from kterminal.domain.timeframes import M1, Timeframe
from tests.integration.db.helpers import T0

pytestmark = pytest.mark.integration

MIN = timedelta(minutes=1)


def bar(minute: int, close: str = "4000.10", *, source: str = "oanda") -> Bar:
    return Bar.of(
        "XAUUSD",
        M1,
        T0 + minute * MIN,
        Decimal("4000.00"),
        Decimal("4001.000"),
        Decimal("3999.5"),
        Decimal(close),
        volume=Decimal("12"),
        source=source,
    )


async def test_candles_round_trip_exactly_and_existing_rows_are_kept(
    session: AsyncSession,
) -> None:
    bars = [bar(0), bar(1), bar(2)]
    assert await insert_candles(session, bars) == 3
    assert await insert_candles(session, [bar(1, "4000.20"), bar(3)]) == 1  # only 3 is new
    loaded = await load_candles(session, "XAUUSD", source="oanda", start=T0, end=T0 + 3 * MIN)
    assert loaded == bars  # Decimal equality: 4001.000 == 4001.0000000000
    assert [plain_bar(b) for b in loaded] == [plain_bar(b) for b in bars]
    assert str(plain_bar(loaded[0]).high) == "4001"  # canonical text, whatever was stored

    assert await insert_candles(session, [bar(1, "4000.20")], replace=True) == 1
    (replaced,) = await load_candles(
        session, "XAUUSD", source="oanda", start=T0 + MIN, end=T0 + 2 * MIN
    )
    assert replaced.close == Decimal("4000.20")
    assert await load_candles(session, "XAUUSD", source="tv", start=T0, end=T0 + 9 * MIN) == []


async def test_coverage_and_the_newest_bar_per_source(session: AsyncSession) -> None:
    await insert_candles(session, [bar(0), bar(1), bar(5)])
    await insert_candles(session, [bar(2, source="tv-export")])
    assert await latest_candle_open(session, "XAUUSD", source="oanda") == T0 + 5 * MIN
    assert await latest_candle_open(session, "XAUUSD", source="oanda", before=T0 + 5 * MIN) == (
        T0 + MIN
    )
    assert await latest_candle_open(session, "NEARUSD", source="oanda") is None
    assert await candle_coverage(session, "XAUUSD") == [
        CandleCoverage("XAUUSD", "1m", "oanda", 3, T0, T0 + 5 * MIN),
        CandleCoverage("XAUUSD", "1m", "tv-export", 1, T0 + 2 * MIN, T0 + 2 * MIN),
    ]


async def test_large_imports_are_written_in_chunks(session: AsyncSession) -> None:
    bars = [bar(i) for i in range(12_000)]  # more rows than one INSERT may bind
    assert await insert_candles(session, bars) == 12_000
    count = await session.scalar(select(func.count()).select_from(CandleRow))
    assert count == 12_000


async def test_bars_without_a_source_or_of_irregular_length_are_refused(
    session: AsyncSession,
) -> None:
    with pytest.raises(ValueError, match="has no source"):
        await insert_candles(session, [bar(0, source="")])
    odd = Bar(
        instrument="XAUUSD",
        timeframe=Timeframe.parse("1h"),
        open_time=T0,
        close_time=T0 + 30 * MIN,  # a session-shortened hour
        open=Decimal(1),
        high=Decimal(1),
        low=Decimal(1),
        close=Decimal(1),
        source="x",
    )
    with pytest.raises(ValueError, match="fixed-length"):
        await insert_candles(session, [odd])
