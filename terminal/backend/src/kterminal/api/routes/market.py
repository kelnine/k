"""Candles with trade markers, and the per-instrument view."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query

from kterminal.api.errors import ApiError, not_found
from kterminal.api.queries.accounts import AccountFilter, list_accounts, sort_accounts
from kterminal.api.queries.candles import (
    CHART_TIMEFRAMES,
    MAX_CANDLES,
    MarkerFilter,
    chart_candles,
    chart_timeframe,
)
from kterminal.api.queries.instruments import list_instruments
from kterminal.api.queries.trades import TradeFilter, open_positions
from kterminal.api.routes.common import ClockDep, DbSession, Kill, Runtime
from kterminal.api.schemas import CandlesOut, InstrumentDetailOut, InstrumentSummary

router = APIRouter(tags=["market"])

Symbol = Annotated[str, Query(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9._:!-]+$")]


@router.get("/candles", response_model=CandlesOut)
async def candles(
    session: DbSession,
    instrument: Symbol,
    timeframe: Annotated[str, Query(description=f"One of {', '.join(CHART_TIMEFRAMES)}")] = "5m",
    source: str | None = None,
    until: Annotated[
        datetime | None, Query(description="Exclusive end (bar open time); default: latest")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_CANDLES)] = 500,
    markers: Literal["forward", "run", "all", "none"] = "forward",
    account_id: UUID | None = None,
    run_id: UUID | None = None,
    instance: Annotated[list[str] | None, Query(description="Only these instances")] = None,
) -> CandlesOut:
    """Bars from the ``candles`` table (aggregated when the timeframe is not stored) with
    the trades of every strategy on the instrument as markers (filterable)."""
    try:
        tf = chart_timeframe(timeframe)
    except ValueError as exc:
        raise ApiError(422, "INVALID_TIMEFRAME", str(exc)) from None
    return await chart_candles(
        session,
        instrument,
        tf,
        source=source,
        until=until,
        limit=limit,
        markers=None
        if markers == "none"
        else MarkerFilter(
            scope=markers, account_id=account_id, run_id=run_id, instance_ids=instance or ()
        ),
    )


@router.get("/instruments", response_model=list[InstrumentSummary])
async def instruments(session: DbSession, runtime: Runtime) -> list[InstrumentSummary]:
    """Every instrument a configured strategy trades, with its feed and open positions."""
    return await list_instruments(session, runtime)


@router.get("/instruments/{symbol}", response_model=InstrumentDetailOut)
async def instrument(
    symbol: str, session: DbSession, runtime: Runtime, kill: Kill, clock: ClockDep
) -> InstrumentDetailOut:
    """The forward accounts trading ``symbol`` and their open positions on it."""
    found = await list_instruments(session, runtime, symbol=symbol)
    if not found:
        raise not_found("instrument")
    accounts = await list_accounts(
        session, AccountFilter(scope="forward", instrument=symbol), runtime=runtime, kill=kill
    )
    positions = await open_positions(
        session, TradeFilter(scope="forward", instrument=symbol), now=clock.now()
    )
    return InstrumentDetailOut(
        **found[0].model_dump(),
        accounts=sort_accounts(accounts, "average_r", descending=True),
        positions=positions,
    )
