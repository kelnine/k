"""Liveness and readiness probes (internal: not exposed through the public proxy)."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel

from kterminal.api.deps import DatabaseProbe, get_database

router = APIRouter(prefix="/health", tags=["health"])


class LivenessResponse(BaseModel):
    status: Literal["ok"] = "ok"


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: dict[str, Literal["ok", "unavailable"]]


@router.get("/live", response_model=LivenessResponse)
async def live() -> LivenessResponse:
    """The process is up and serving requests."""
    return LivenessResponse()


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse}},
)
async def ready(
    response: Response, database: Annotated[DatabaseProbe, Depends(get_database)]
) -> ReadinessResponse:
    """Dependencies are reachable; returns 503 otherwise so load balancers stop routing here."""
    database_ok = await database.ping()
    if not database_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(
        status="ready" if database_ok else "not_ready",
        checks={"database": "ok" if database_ok else "unavailable"},
    )
