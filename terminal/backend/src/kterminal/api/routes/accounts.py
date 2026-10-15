"""Accounts: the leaderboard, account pages, equity curves and open positions."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from kterminal.api.errors import not_found
from kterminal.api.queries.accounts import (
    AccountFilter,
    SortKey,
    list_accounts,
    sort_accounts,
)
from kterminal.api.queries.system import kill_switch_rows, kill_switches_out
from kterminal.api.queries.trades import TradeFilter, open_positions
from kterminal.api.routes.common import ClockDep, DbSession, Kill, Limit, Offset, Runtime, Scope
from kterminal.api.schemas import (
    AccountDetailOut,
    AccountOut,
    EquityOut,
    EquityPoint,
    Page,
    PositionOut,
)
from kterminal.db import models as m

router = APIRouter(tags=["accounts"])


@router.get("/accounts", response_model=Page[AccountOut])
async def accounts(
    session: DbSession,
    runtime: Runtime,
    kill: Kill,
    scope: Scope = "all",
    run_id: UUID | None = None,
    instance_id: str | None = None,
    strategy: Annotated[str | None, Query(description="Strategy definition id")] = None,
    instrument: str | None = None,
    timeframe: str | None = None,
    status: str | None = None,
    q: Annotated[str | None, Query(max_length=100, description="Search text")] = None,
    sort: SortKey = "average_r",
    order: Literal["asc", "desc"] = "desc",
    limit: Limit = 100,
    offset: Offset = 0,
) -> Page[AccountOut]:
    """Accounts with appendix A metrics. ``scope=forward`` is the leaderboard of the
    dedicated forward-test accounts; the default sort is expectancy (R), ties broken by
    profit factor."""
    found = await list_accounts(
        session,
        AccountFilter(
            scope=scope,
            run_id=run_id,
            instance_id=instance_id,
            definition_id=strategy,
            instrument=instrument,
            timeframe=timeframe,
            status=status,
            query=q,
        ),
        runtime=runtime,
        kill=kill,
    )
    ordered = sort_accounts(found, sort, descending=order == "desc")
    return Page[AccountOut](
        items=ordered[offset : offset + limit], total=len(ordered), limit=limit, offset=offset
    )


@router.get("/accounts/{account_id}", response_model=AccountDetailOut)
async def account(
    account_id: UUID, session: DbSession, runtime: Runtime, kill: Kill
) -> AccountDetailOut:
    found = await list_accounts(
        session, AccountFilter(account_ids=[account_id]), runtime=runtime, kill=kill
    )
    if not found:
        raise not_found("account")
    row = await session.get(m.AccountRow, account_id)
    if row is None:  # pragma: no cover - listed a moment ago
        raise not_found("account")
    config = (
        await session.get(m.AccountConfigVersionRow, row.current_config_version_id)
        if row.current_config_version_id
        else None
    )
    out = found[0]
    switches = [
        s
        for s in await kill_switches_out(session, await kill_switch_rows(session))
        if s.scope == "GLOBAL"
        or (s.scope == "ACCOUNT" and s.scope_id == str(account_id))
        or (s.scope == "STRATEGY" and s.scope_id == out.instance_id)
    ]
    return AccountDetailOut(
        **out.model_dump(),
        config_version=config.version if config else None,
        config=config.config if config else None,
        high_water_mark=row.high_water_mark,
        kill_switches=switches,
    )


@router.get("/accounts/{account_id}/equity", response_model=EquityOut)
async def equity(
    account_id: UUID,
    session: DbSession,
    max_points: Annotated[int, Query(ge=10, le=10_000)] = 1_500,
) -> EquityOut:
    """The mark-to-market equity curve, downsampled to at most ``max_points`` points
    (every k-th snapshot, always including the first and the last)."""
    account_row = await session.get(m.AccountRow, account_id)
    if account_row is None:
        raise not_found("account")
    s = m.EquitySnapshotRow
    total = int(
        (
            await session.execute(
                select(func.count()).select_from(s).where(s.account_id == account_id)
            )
        ).scalar_one()
    )
    step = max(1, -(-total // max_points))
    numbered = (
        select(
            s.ts,
            s.balance,
            s.equity,
            s.open_pnl,
            s.drawdown,
            func.row_number().over(order_by=s.ts).label("n"),
        )
        .where(s.account_id == account_id)
        .subquery()
    )
    rows = await session.execute(
        select(numbered)
        .where(((numbered.c.n - 1) % step == 0) | (numbered.c.n == total))
        .order_by(numbered.c.ts)
    )
    return EquityOut(
        account_id=account_id,
        starting_balance=account_row.starting_balance,
        points=[
            EquityPoint(
                ts=r.ts,
                balance=r.balance,
                equity=r.equity,
                open_pnl=r.open_pnl,
                drawdown=r.drawdown,
            )
            for r in rows
        ],
        total_points=total,
        downsampled=step > 1,
    )


@router.get("/positions", response_model=list[PositionOut])
async def positions(
    session: DbSession,
    clock: ClockDep,
    scope: Scope = "forward",
    account_id: UUID | None = None,
    instance_id: str | None = None,
    instrument: str | None = None,
    run_id: UUID | None = None,
) -> list[PositionOut]:
    """Open trades, marked at the instrument's latest stored candle close."""
    return await open_positions(
        session,
        TradeFilter(
            scope=scope,
            account_id=account_id,
            instance_id=instance_id,
            instrument=instrument,
            run_id=run_id,
        ),
        now=clock.now(),
    )
