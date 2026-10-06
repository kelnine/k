"""The ``engine`` process: the only process that routes signals and talks to brokers.

Phase 1 establishes its lifecycle and the single-active-instance guarantee
(PostgreSQL advisory-lock leader election). Trading components are wired in
from Phase 3 onwards: strategy runner → signal router → risk engine →
execution engine → broker adapters, plus the equity monitor and kill switch.
"""

import asyncio

from kterminal.core.errors import LeadershipLostError
from kterminal.db.locks import ENGINE_LEADER_LOCK, AdvisoryLock
from kterminal.observability.logging import get_logger
from kterminal.runtime.container import Container
from kterminal.runtime.service import sleep_or_stop

_log = get_logger("kterminal.engine")


async def run_engine(container: Container, stop: asyncio.Event) -> None:
    settings = container.settings
    _log.info(
        "engine.configuration",
        default_mode=settings.trading.default_mode.value,
        live_trading_permitted=settings.trading.live_trading_permitted,
    )
    if settings.trading.live_trading_permitted:
        _log.warning("engine.live_trading_globally_enabled")

    lock = AdvisoryLock(container.db.engine, ENGINE_LEADER_LOCK)
    if not await _acquire_leadership(lock, stop, settings.runtime.leader_retry_interval_s):
        return
    try:
        _log.info("engine.active", components="none wired yet (Phase 1 skeleton)")
        while not await sleep_or_stop(stop, settings.runtime.heartbeat_interval_s):
            if not await lock.verify():
                # Another engine may take over now; continuing would risk duplicate orders.
                raise LeadershipLostError("engine leader lock lost — stopping immediately")
            _log.debug("engine.heartbeat")
    finally:
        await lock.release()


async def _acquire_leadership(lock: AdvisoryLock, stop: asyncio.Event, retry_s: float) -> bool:
    """Block (in standby) until this process becomes the leader or a stop is requested."""
    standby_logged = False
    while not stop.is_set():
        try:
            if await lock.try_acquire():
                return True
            if not standby_logged:
                _log.info("engine.standby", reason="another engine instance is active")
                standby_logged = True
        except Exception as exc:
            _log.warning("engine.leader_lock_unavailable", error=type(exc).__name__)
        if await sleep_or_stop(stop, retry_s):
            break
    return False
