"""System information, the overview page, runtime status and faults."""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select

from kterminal import __version__
from kterminal.api.deps import get_clock, get_settings
from kterminal.api.queries.accounts import AccountFilter, list_accounts
from kterminal.api.queries.runs import list_runs
from kterminal.api.queries.system import (
    faults,
    faults_since,
    kill_switch_rows,
    kill_switch_state,
    kill_switches_out,
)
from kterminal.api.routes.common import DbSession, Limit, Offset, Runtime
from kterminal.api.schemas import FaultOut, ForwardSummary, OverviewOut, Page, RuntimeView
from kterminal.config.settings import Settings
from kterminal.core.clock import Clock
from kterminal.core.enums import TradingMode
from kterminal.db import models as m

router = APIRouter(tags=["system"])


class SystemInfo(BaseModel):
    name: str
    version: str
    environment: str
    default_mode: TradingMode
    live_trading_permitted: bool
    server_time: datetime


@router.get("/system/info", response_model=SystemInfo)
async def info(
    settings: Annotated[Settings, Depends(get_settings)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> SystemInfo:
    return SystemInfo(
        name=settings.service_name,
        version=__version__,
        environment=settings.environment.value,
        default_mode=settings.trading.default_mode,
        live_trading_permitted=settings.trading.live_trading_permitted,
        server_time=clock.now(),
    )


@router.get("/system/runtime", response_model=RuntimeView)
async def runtime(view: Runtime) -> RuntimeView:
    """The forward paper runtime's last reported status (``system_state`` 'paper.runtime')."""
    return view


@router.get("/system/faults", response_model=Page[FaultOut])
async def system_faults(
    session: DbSession,
    instance_id: str | None = None,
    run_id: UUID | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> Page[FaultOut]:
    """Recorded faults (strategy exceptions and component errors), newest first."""
    items, total = await faults(
        session, limit=limit, offset=offset, instance_id=instance_id, run_id=run_id
    )
    return Page[FaultOut](items=items, total=total, limit=limit, offset=offset)


@router.get("/overview", response_model=OverviewOut)
async def overview(
    session: DbSession,
    view: Runtime,
    settings: Annotated[Settings, Depends(get_settings)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> OverviewOut:
    """Runtime health, active kill switches and the forward accounts in one call."""
    now = clock.now()
    rows = await kill_switch_rows(session)
    kill = kill_switch_state(rows)
    forward = await list_accounts(session, AccountFilter(scope="forward"), runtime=view, kill=kill)
    enabled = (
        await session.execute(
            select(func.count())
            .select_from(m.StrategyInstanceRow)
            .where(m.StrategyInstanceRow.enabled)
        )
    ).scalar_one()
    recent, _ = await list_runs(session, limit=5, offset=0)
    return OverviewOut(
        server_time=now,
        environment=settings.environment.value,
        live_trading_permitted=settings.trading.live_trading_permitted,
        runtime=view,
        global_halt=kill.global_active,
        active_kill_switches=await kill_switches_out(session, [r for r in rows if r.active]),
        forward=ForwardSummary(
            accounts=len(forward),
            instances_enabled=int(enabled),
            open_positions=sum(a.metrics.open_positions for a in forward),
            closed_trades=sum(a.metrics.trades for a in forward),
            net_pnl=sum((a.metrics.net_pnl for a in forward), Decimal(0)),
            equity=sum((a.metrics.equity for a in forward), Decimal(0)),
            starting_balance=sum((a.metrics.starting_balance for a in forward), Decimal(0)),
        ),
        recent_runs=recent,
        faults_24h=await faults_since(session, now - timedelta(hours=24)),
    )
