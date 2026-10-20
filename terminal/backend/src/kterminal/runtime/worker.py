"""The ``worker`` process: notifications, scheduled reports, analytics and backtest jobs.

Phase 1 establishes the lifecycle only. Telegram delivery and the report
scheduler arrive in Phase 7, analytics recomputation in Phase 4. Workers are
safe to run as several replicas: jobs are claimed from the database with
``SELECT … FOR UPDATE SKIP LOCKED`` and reports are de-duplicated per period.

Database housekeeping runs here from Phase 2: monthly partitions are created
at start-up and again each UTC day (one replica at a time, under an advisory
lock), so partitioned tables never fall back to their DEFAULT partition.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime

from sqlalchemy.ext.asyncio import AsyncEngine

from kterminal.db.partitions import maintain_partitions
from kterminal.observability.logging import get_logger
from kterminal.runtime.container import Container
from kterminal.runtime.service import sleep_or_stop

_log = get_logger("kterminal.worker")

RETRY_AFTER_S = 3_600.0  # a failed partition run is retried hourly, not every heartbeat

type PartitionMaintenance = Callable[..., Awaitable[list[str] | None]]


async def run_worker(
    container: Container,
    stop: asyncio.Event,
    *,
    partitions: PartitionMaintenance = maintain_partitions,
) -> None:
    _log.info("worker.active", components="partition maintenance")
    done_for: date | None = None
    retry_at = 0.0
    while True:
        today = datetime.now(UTC).date()
        if done_for != today and time.monotonic() >= retry_at:
            if await _maintain(partitions, container.db.engine, today):
                done_for = today
            else:
                retry_at = time.monotonic() + RETRY_AFTER_S
        if await sleep_or_stop(stop, container.settings.runtime.heartbeat_interval_s):
            return
        _log.debug("worker.heartbeat")


async def _maintain(partitions: PartitionMaintenance, engine: AsyncEngine, today: date) -> bool:
    try:
        created = await partitions(engine, today=today)
    except Exception as exc:  # housekeeping must never stop the worker
        _log.error("worker.partitions_failed", error=type(exc).__name__, detail=str(exc)[:500])
        return False
    if created is None:
        _log.debug("worker.partitions_skipped", reason="another process holds the lock")
    elif created:
        _log.info("worker.partitions_created", partitions=created)
    return True
