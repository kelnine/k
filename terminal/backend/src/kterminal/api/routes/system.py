"""System information for the dashboard header and operators."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from kterminal import __version__
from kterminal.api.deps import get_clock, get_settings
from kterminal.config.settings import Settings
from kterminal.core.clock import Clock
from kterminal.core.enums import TradingMode

router = APIRouter(prefix="/system", tags=["system"])


class SystemInfo(BaseModel):
    name: str
    version: str
    environment: str
    default_mode: TradingMode
    live_trading_permitted: bool
    server_time: datetime


@router.get("/info", response_model=SystemInfo)
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
