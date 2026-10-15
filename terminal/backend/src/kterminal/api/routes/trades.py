"""Trades, "explain this trade" and the signal log."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter

from kterminal.api.errors import not_found
from kterminal.api.queries.signals import (
    Outcome,
    SignalFilter,
    UnknownAccountError,
    list_signals,
)
from kterminal.api.queries.trades import TradeFilter, explain_trade, list_trades
from kterminal.api.routes.common import DbSession, Limit, Offset, Scope
from kterminal.api.schemas import Page, SignalLogItem, TradeExplainOut, TradeOut

router = APIRouter(tags=["trades"])


@router.get("/trades", response_model=Page[TradeOut])
async def trades(
    session: DbSession,
    scope: Scope = "all",
    account_id: UUID | None = None,
    instance_id: str | None = None,
    run_id: UUID | None = None,
    instrument: str | None = None,
    status: Literal["OPEN", "CLOSED"] | None = None,
    direction: Literal["LONG", "SHORT"] | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> Page[TradeOut]:
    """Trades, newest first (by exit, or entry while open)."""
    items, total = await list_trades(
        session,
        TradeFilter(
            scope=scope,
            account_id=account_id,
            instance_id=instance_id,
            run_id=run_id,
            instrument=instrument,
            status=status,
            direction=direction,
            since=since,
            until=until,
        ),
        limit=limit,
        offset=offset,
    )
    return Page[TradeOut](items=items, total=total, limit=limit, offset=offset)


@router.get("/trades/{trade_id}", response_model=TradeExplainOut)
async def trade(trade_id: UUID, session: DbSession) -> TradeExplainOut:
    """Everything recorded about one trade: strategy version and parameters, account
    configuration, entry/exit signals, the risk decision with every rule, orders, fills,
    stop moves and ledger entries."""
    found = await explain_trade(session, trade_id)
    if found is None:
        raise not_found("trade")
    return found


@router.get("/signals", response_model=Page[SignalLogItem])
async def signals(
    session: DbSession,
    scope: Scope = "all",
    account_id: UUID | None = None,
    instance_id: str | None = None,
    run_id: UUID | None = None,
    instrument: str | None = None,
    action: str | None = None,
    outcome: Outcome | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> Page[SignalLogItem]:
    """Signals, newest first, with the risk decision and the reason for any rejection."""
    try:
        items, total = await list_signals(
            session,
            SignalFilter(
                scope=scope,
                account_id=account_id,
                instance_id=instance_id,
                run_id=run_id,
                instrument=instrument,
                action=action,
                outcome=outcome,
                since=since,
                until=until,
            ),
            limit=limit,
            offset=offset,
        )
    except UnknownAccountError:
        raise not_found("account") from None
    return Page[SignalLogItem](items=items, total=total, limit=limit, offset=offset)
