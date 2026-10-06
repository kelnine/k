import asyncio

import pytest

from kterminal.config.settings import Settings
from kterminal.runtime.container import Container
from kterminal.runtime.worker import run_worker


async def test_worker_heartbeats_until_stopped(caplog: pytest.LogCaptureFixture) -> None:
    settings = Settings(_env_file=None, environment="test", runtime={"heartbeat_interval_s": 0.01})
    container = Container.build(settings, role="worker")  # no connection is opened
    stop = asyncio.Event()
    asyncio.get_running_loop().call_later(0.1, stop.set)
    await asyncio.wait_for(run_worker(container, stop), timeout=5)
    await container.aclose()
    assert "worker.active" in caplog.text
    assert "worker.heartbeat" in caplog.text
