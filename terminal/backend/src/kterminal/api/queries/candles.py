"""Candles from the ``candles`` table, aggregated on the fly, with trade markers.

The forward runtime stores the bars that drove its decisions (normally 1m).
A chart asks for any intraday timeframe: a stored timeframe is read as is,
any other is aggregated in SQL from the coarsest stored timeframe that divides
it (``date_bin`` buckets aligned to UTC midnight, like the lab's aggregator).
A bucket only partly covered by stored bars — the forming bar, or bars around
a data gap — is shown as built from the bars that exist; gaps are never filled.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Final, Literal
from uuid import UUID

from sqlalchemy import exists, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from kterminal.api.schemas import CandleOut, CandlesOut, TradeMarker
from kterminal.db import models as m
from kterminal.domain.timeframes import Timeframe

CHART_TIMEFRAMES: Final = ("1m", "5m", "15m", "30m", "1h", "4h")
"""Timeframes a chart can show (intraday only: daily bars need the instrument's session)."""

MAX_CANDLES: Final = 5_000
MAX_MARKERS: Final = 2_000
_ORIGIN: Final = datetime(2000, 1, 3, tzinfo=UTC)  # a Monday 00:00 UTC; any midnight works

_SOURCES = text(
    """
    WITH RECURSIVE s AS (
        (SELECT source FROM candles
         WHERE instrument = :instrument AND timeframe = :timeframe
         ORDER BY source LIMIT 1)
        UNION ALL
        SELECT (SELECT c.source FROM candles c
                WHERE c.instrument = :instrument AND c.timeframe = :timeframe
                  AND c.source > s.source
                ORDER BY c.source LIMIT 1)
        FROM s WHERE s.source IS NOT NULL
    )
    SELECT source FROM s WHERE source IS NOT NULL
    """
)
"""Distinct sources without reading every bar (a loose index scan over the primary key)."""

_AGGREGATE = text(
    """
    SELECT date_bin(:step, ts, :origin) AS bucket,
           (array_agg(open ORDER BY ts))[1] AS o,
           max(high) AS h,
           min(low) AS l,
           (array_agg(close ORDER BY ts DESC))[1] AS c,
           sum(volume) AS v
    FROM candles
    WHERE instrument = :instrument AND timeframe = :timeframe AND source = :source
      AND ts >= :since AND ts < :until
    GROUP BY 1
    ORDER BY 1 DESC
    LIMIT :limit
    """
)

MarkerScope = Literal["forward", "run", "all"]


@dataclass(frozen=True, slots=True)
class MarkerFilter:
    scope: MarkerScope = "forward"
    account_id: UUID | None = None
    run_id: UUID | None = None
    instance_ids: Sequence[str] = ()


def chart_timeframe(code: str) -> Timeframe:
    timeframe = Timeframe.parse(code)
    if timeframe.code not in CHART_TIMEFRAMES:
        raise ValueError(f"timeframe must be one of {', '.join(CHART_TIMEFRAMES)}")
    return timeframe


async def stored_timeframes(session: AsyncSession, instrument: str) -> list[tuple[str, timedelta]]:
    """Chart timeframes the table holds bars of for ``instrument``, finest first."""
    c = m.CandleRow
    present = (
        await session.execute(
            select(
                *(
                    exists()
                    .where(c.instrument == instrument, c.timeframe == code)
                    .label(f"tf_{index}")
                    for index, code in enumerate(CHART_TIMEFRAMES)
                )
            )
        )
    ).one()
    return [
        (code, Timeframe.parse(code).duration)
        for code, there in zip(CHART_TIMEFRAMES, present, strict=True)
        if there
    ]


async def last_candle_at(session: AsyncSession, instrument: str) -> datetime | None:
    stored = await stored_timeframes(session, instrument)
    if not stored:
        return None
    code, duration = stored[0]
    ts = (
        await session.execute(
            select(m.CandleRow.ts)
            .where(m.CandleRow.instrument == instrument, m.CandleRow.timeframe == code)
            .order_by(m.CandleRow.ts.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return None if ts is None else ts + duration


async def chart_candles(
    session: AsyncSession,
    instrument: str,
    timeframe: Timeframe,
    *,
    source: str | None = None,
    until: datetime | None = None,
    limit: int = 500,
    markers: MarkerFilter | None = None,
) -> CandlesOut:
    limit = max(1, min(limit, MAX_CANDLES))
    stored = await stored_timeframes(session, instrument)
    base = _base_timeframe(timeframe, [code for code, _ in stored])
    empty = CandlesOut(
        instrument=instrument,
        timeframe=timeframe.code,
        source=None,
        sources=[],
        built_from=None,
        candles=[],
        markers=[],
    )
    if base is None:
        return empty
    sources = list(
        (await session.execute(_SOURCES, {"instrument": instrument, "timeframe": base.code}))
        .scalars()
        .all()
    )
    chosen = (
        source if source in sources else await _freshest_source(session, instrument, base, sources)
    )
    if chosen is None:
        return empty.model_copy(update={"sources": sources})
    c = m.CandleRow
    if until is None:
        latest = (
            await session.execute(
                select(c.ts)
                .where(c.instrument == instrument, c.timeframe == base.code, c.source == chosen)
                .order_by(c.ts.desc())
                .limit(1)
            )
        ).scalar_one()
        until = latest + base.duration
    if base == timeframe:
        rows = (
            await session.execute(
                select(
                    c.ts.label("bucket"),
                    c.open.label("o"),
                    c.high.label("h"),
                    c.low.label("l"),
                    c.close.label("c"),
                    c.volume.label("v"),
                )
                .where(
                    c.instrument == instrument,
                    c.timeframe == base.code,
                    c.source == chosen,
                    c.ts < until,
                )
                .order_by(c.ts.desc())
                .limit(limit)
            )
        ).all()
    else:
        # Up to ``limit`` buckets: look back three times the span to cover closed markets.
        since = until - timeframe.duration * limit * 3
        rows = (
            await session.execute(
                _AGGREGATE,
                {
                    "step": timeframe.duration,
                    "origin": _ORIGIN,
                    "instrument": instrument,
                    "timeframe": base.code,
                    "source": chosen,
                    "since": since,
                    "until": until,
                    "limit": limit,
                },
            )
        ).all()
    candles = [
        CandleOut(
            t=row.bucket,
            o=Decimal(row.o),
            h=Decimal(row.h),
            l=Decimal(row.l),
            c=Decimal(row.c),
            v=None if row.v is None else Decimal(row.v),
        )
        for row in reversed(rows)
    ]
    found = []
    if markers is not None and candles:
        found = await trade_markers(
            session, instrument, since=candles[0].t, until=until, filters=markers
        )
    return CandlesOut(
        instrument=instrument,
        timeframe=timeframe.code,
        source=chosen,
        sources=sources,
        built_from=None if base == timeframe else base.code,
        candles=candles,
        markers=found,
    )


def _base_timeframe(wanted: Timeframe, stored: list[str]) -> Timeframe | None:
    """The stored timeframe to build ``wanted`` from: itself, else the coarsest divisor."""
    candidates = [Timeframe.parse(code) for code in stored]
    if wanted in candidates:
        return wanted
    divisors = [tf for tf in candidates if tf.divides(wanted)]
    return max(divisors) if divisors else None


async def _freshest_source(
    session: AsyncSession, instrument: str, base: Timeframe, sources: list[str]
) -> str | None:
    c = m.CandleRow
    best: tuple[datetime, str] | None = None
    for name in sources:
        ts = (
            await session.execute(
                select(c.ts)
                .where(c.instrument == instrument, c.timeframe == base.code, c.source == name)
                .order_by(c.ts.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if ts is not None and (best is None or ts > best[0]):
            best = (ts, name)
    return best[1] if best else None


async def trade_markers(
    session: AsyncSession,
    instrument: str,
    *,
    since: datetime,
    until: datetime,
    filters: MarkerFilter,
) -> list[TradeMarker]:
    """Trades on ``instrument`` that overlap ``[since, until)``."""
    t = m.TradeRow
    conditions = [
        t.instrument == instrument,
        t.entry_time < until,
        or_(t.exit_time.is_(None), t.exit_time >= since),
    ]
    if filters.scope == "forward":
        conditions.append(m.AccountRow.strategy_instance_id.is_not(None))
    elif filters.scope == "run":
        conditions.append(m.AccountRow.strategy_instance_id.is_(None))
    if filters.account_id is not None:
        conditions.append(t.account_id == filters.account_id)
    if filters.run_id is not None:
        conditions.append(t.run_id == filters.run_id)
    if filters.instance_ids:
        conditions.append(t.strategy_instance_id.in_(list(filters.instance_ids)))
    rows = await session.execute(
        select(
            t.id.label("trade_id"),
            t.account_id,
            t.strategy_instance_id.label("instance_id"),
            t.timeframe,
            t.direction,
            t.status,
            t.qty,
            t.entry_time,
            t.entry_price,
            t.exit_time,
            t.exit_price,
            t.exit_reason,
            t.initial_stop,
            t.initial_target,
            t.current_stop,
            t.current_target,
            t.net_pnl,
            t.r_multiple,
        )
        .join(m.AccountRow, m.AccountRow.id == t.account_id)
        .where(*conditions)
        .order_by(t.entry_time)
        .limit(MAX_MARKERS)
    )
    return [TradeMarker(**row._mapping) for row in rows]
