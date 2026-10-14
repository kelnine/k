"""Strategy instances and runs."""

from uuid import UUID

from fastapi import APIRouter

from kterminal.api.errors import not_found
from kterminal.api.queries.runs import list_runs
from kterminal.api.queries.strategies import instance_detail, list_instances
from kterminal.api.routes.common import DbSession, Limit, Offset, Runtime
from kterminal.api.schemas import InstanceDetailOut, InstanceOut, Page, RunOut

router = APIRouter(tags=["strategies"])


@router.get("/instances", response_model=list[InstanceOut])
async def instances(session: DbSession, runtime: Runtime) -> list[InstanceOut]:
    """Strategy instances with their current version (parameters, timeframe, instruments),
    dedicated account and the state the forward runtime reports for them."""
    return await list_instances(session, runtime)


@router.get("/instances/{instance_id}", response_model=InstanceDetailOut)
async def instance(instance_id: str, session: DbSession, runtime: Runtime) -> InstanceDetailOut:
    found = await instance_detail(session, instance_id, runtime)
    if found is None:
        raise not_found("strategy instance")
    return found


@router.get("/runs", response_model=Page[RunOut])
async def runs(
    session: DbSession,
    kind: str | None = None,
    status: str | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> Page[RunOut]:
    """Lab simulations, backtests, forward sessions and replays, newest first."""
    items, total = await list_runs(session, kind=kind, status=status, limit=limit, offset=offset)
    return Page[RunOut](items=items, total=total, limit=limit, offset=offset)


@router.get("/runs/{run_id}", response_model=RunOut)
async def run(run_id: UUID, session: DbSession) -> RunOut:
    items, _ = await list_runs(session, run_id=run_id, limit=1, offset=0)
    if not items:
        raise not_found("run")
    return items[0]
