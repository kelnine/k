"""Candles: stored bars, keyed by instrument, timeframe, source and open time.

The ``candles`` table holds imported history (``kterminal data import-csv``),
provider history fetched for warm-ups, and every base bar a forward paper
session processed — for a forward session it is the *input log* its state is
rebuilt from after a restart. Rows are keyed by ``(instrument, timeframe,
source, ts)`` with ``ts`` the bar's open time; prices and volume are
``NUMERIC``, so bars read back compare equal to the bars written (their
Decimal exponent may differ: use :func:`plain_bar` where text matters).

Repositories never commit; the caller owns the transaction.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from kterminal.core.canonical import decimal_text
from kterminal.core.clock import ensure_utc
from kterminal.db.models import CandleRow, table_of
from kterminal.domain.market import Bar
from kterminal.domain.timeframes import Timeframe

_candles = table_of(CandleRow)
_BATCH = 3_000  # rows per INSERT: 9 columns each, asyncpg caps bind parameters at 32,767
_PRICE_COLUMNS = ("open", "high", "low", "close", "volume")


@dataclass(frozen=True, slots=True)
class CandleCoverage:
    instrument: str
    timeframe: str
    source: str
    bars: int
    first_open: datetime
    last_open: datetime


def plain_bar(bar: Bar) -> Bar:
    """``bar`` with its numbers in canonical text form (``4000.0100000000`` → ``4000.01``),
    so a bar read from the database is indistinguishable from the one written."""
    values = {name: Decimal(decimal_text(getattr(bar, name))) for name in _PRICE_COLUMNS}
    return Bar(
        instrument=bar.instrument,
        timeframe=bar.timeframe,
        open_time=bar.open_time,
        close_time=bar.close_time,
        source=bar.source,
        **values,
    )


def _row(bar: Bar) -> dict[str, Any]:
    if not bar.source:
        raise ValueError(f"{bar.instrument} bar at {bar.open_time.isoformat()} has no source")
    if bar.close_time - bar.open_time != bar.timeframe.duration:
        raise ValueError(f"{bar.instrument}: only fixed-length bars can be stored as candles")
    return {
        "instrument": bar.instrument,
        "timeframe": bar.timeframe.code,
        "source": bar.source,
        "ts": bar.open_time,
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "volume": bar.volume,
    }


async def insert_candles(
    session: AsyncSession, bars: Sequence[Bar], *, replace: bool = False
) -> int:
    """Store ``bars``. Existing rows (same instrument, timeframe, source and open time)
    are kept unless ``replace``; returns the number of rows inserted or replaced."""
    written = 0
    rows = [_row(bar) for bar in bars]
    for start in range(0, len(rows), _BATCH):
        chunk = rows[start : start + _BATCH]
        stmt = insert(_candles).values(chunk)
        if replace:
            stmt = stmt.on_conflict_do_update(
                index_elements=["instrument", "timeframe", "source", "ts"],
                set_={column: stmt.excluded[column] for column in _PRICE_COLUMNS},
            )
        else:
            stmt = stmt.on_conflict_do_nothing(
                index_elements=["instrument", "timeframe", "source", "ts"]
            )
        result = await session.execute(stmt.returning(_candles.c.ts))
        written += len(result.all())
    return written


async def load_candles(
    session: AsyncSession,
    instrument: str,
    *,
    source: str,
    start: datetime,
    end: datetime,
    timeframe: str = "1m",
) -> list[Bar]:
    """Stored bars with ``start <= open time < end``, oldest first."""
    tf = Timeframe.parse(timeframe)
    rows = (
        await session.execute(
            select(_candles)
            .where(
                _candles.c.instrument == instrument,
                _candles.c.timeframe == tf.code,
                _candles.c.source == source,
                _candles.c.ts >= ensure_utc(start),
                _candles.c.ts < ensure_utc(end),
            )
            .order_by(_candles.c.ts)
        )
    ).all()
    return [
        Bar(
            instrument=row.instrument,
            timeframe=tf,
            open_time=row.ts,
            close_time=row.ts + tf.duration,
            open=row.open,
            high=row.high,
            low=row.low,
            close=row.close,
            volume=row.volume if row.volume is not None else Decimal(0),
            source=row.source,
        )
        for row in rows
    ]


async def latest_candle_open(
    session: AsyncSession,
    instrument: str,
    *,
    source: str,
    before: datetime | None = None,
    timeframe: str = "1m",
) -> datetime | None:
    """Open time of the newest stored bar (before ``before``, if given)."""
    stmt = select(func.max(_candles.c.ts)).where(
        _candles.c.instrument == instrument,
        _candles.c.timeframe == Timeframe.parse(timeframe).code,
        _candles.c.source == source,
    )
    if before is not None:
        stmt = stmt.where(_candles.c.ts < ensure_utc(before))
    value: datetime | None = (await session.execute(stmt)).scalar_one_or_none()
    return value


async def candle_coverage(
    session: AsyncSession, instrument: str | None = None
) -> list[CandleCoverage]:
    """Bars stored per instrument, timeframe and source, with the first and last open."""
    stmt = select(
        _candles.c.instrument,
        _candles.c.timeframe,
        _candles.c.source,
        func.count(),
        func.min(_candles.c.ts),
        func.max(_candles.c.ts),
    ).group_by(_candles.c.instrument, _candles.c.timeframe, _candles.c.source)
    if instrument is not None:
        stmt = stmt.where(_candles.c.instrument == instrument)
    stmt = stmt.order_by(_candles.c.instrument, _candles.c.timeframe, _candles.c.source)
    rows = (await session.execute(stmt)).all()
    return [CandleCoverage(r[0], r[1], r[2], int(r[3]), r[4], r[5]) for r in rows]


__all__ = [
    "CandleCoverage",
    "candle_coverage",
    "insert_candles",
    "latest_candle_open",
    "load_candles",
    "plain_bar",
]
