"""The ``worker`` process: notifications, scheduled reports, analytics and backtest jobs.

Phase 1 establishes the lifecycle only. Telegram delivery and the report
scheduler arrive in Phase 7, analytics recomputation in Phase 4. Workers are
safe to run as several replicas: jobs are claimed from the database with
``SELECT … FOR UPDATE SKIP LOCKED`` and reports are de-duplicated per period.
"""

import asyncio

from kterminal.observability.logging import get_logger
from kterminal.runtime.container import Container
from kterminal.runtime.service import sleep_or_stop

_log = get_logger("kterminal.worker")


async def run_worker(container: Container, stop: asyncio.Event) -> None:
    _log.info("worker.active", components="none wired yet (Phase 1 skeleton)")
    while not await sleep_or_stop(stop, container.settings.runtime.heartbeat_interval_s):
        _log.debug("worker.heartbeat")
