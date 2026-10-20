import asyncio
from datetime import date
from typing import Any

import pytest

from kterminal.config.settings import Settings
from kterminal.runtime.container import Container
from kterminal.runtime.worker import run_worker


async def test_worker_maintains_partitions_and_heartbeats_until_stopped(
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = Settings(_env_file=None, environment="test", runtime={"heartbeat_interval_s": 0.01})
    container = Container.build(settings, role="worker")  # no connection is opened
    calls: list[date] = []

    async def partitions(engine: Any, *, today: date) -> list[str]:
        calls.append(today)
        return ["candles_p209912"]

    stop = asyncio.Event()
    asyncio.get_running_loop().call_later(0.1, stop.set)
    await asyncio.wait_for(run_worker(container, stop, partitions=partitions), timeout=5)
    await container.aclose()
    assert "worker.active" in caplog.text
    assert "worker.heartbeat" in caplog.text
    assert len(calls) == 1  # at start-up, then once per UTC day — not every heartbeat
    assert "worker.partitions_created" in caplog.text


async def test_a_failing_maintenance_run_never_stops_the_worker(
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = Settings(_env_file=None, environment="test", runtime={"heartbeat_interval_s": 0.01})
    container = Container.build(settings, role="worker")

    async def partitions(engine: Any, *, today: date) -> list[str]:
        raise ConnectionError("database unavailable")

    stop = asyncio.Event()
    asyncio.get_running_loop().call_later(0.1, stop.set)
    await asyncio.wait_for(run_worker(container, stop, partitions=partitions), timeout=5)
    await container.aclose()
    assert "worker.partitions_failed" in caplog.text
    assert "worker.heartbeat" in caplog.text
