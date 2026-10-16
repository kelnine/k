"""Dependencies and parameters shared by the dashboard read endpoints."""

from typing import Annotated, Literal

from fastapi import Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from kterminal.api.deps import get_clock, get_session
from kterminal.api.queries.common import MAX_PAGE_SIZE
from kterminal.api.queries.system import (
    KillSwitchState,
    kill_switch_rows,
    kill_switch_state,
    runtime_view,
)
from kterminal.api.schemas import RuntimeView
from kterminal.core.clock import Clock

DbSession = Annotated[AsyncSession, Depends(get_session)]
ClockDep = Annotated[Clock, Depends(get_clock)]
Limit = Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE, description="Page size")]
Offset = Annotated[int, Query(ge=0, le=10_000_000)]
Scope = Literal["forward", "run", "all"]


async def current_runtime(session: DbSession, clock: ClockDep) -> RuntimeView:
    return await runtime_view(session, clock.now())


async def current_kill_switches(session: DbSession) -> KillSwitchState:
    return kill_switch_state(await kill_switch_rows(session))


Runtime = Annotated[RuntimeView, Depends(current_runtime)]
Kill = Annotated[KillSwitchState, Depends(current_kill_switches)]
