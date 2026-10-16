"""The engine's single-active-instance guarantee, against a real PostgreSQL."""

import asyncio
from collections.abc import AsyncIterator, Callable

import pytest
from sqlalchemy import text

from kterminal.config.settings import Settings
from kterminal.core.errors import LeadershipLostError
from kterminal.db.locks import ENGINE_LEADER_LOCK, lock_key
from kterminal.runtime.container import Container
from kterminal.runtime.engine import run_engine

pytestmark = pytest.mark.integration

ContainerFactory = Callable[[str], Container]

TERMINATE_LOCK_HOLDER = (
    "SELECT pg_terminate_backend(pid) FROM pg_locks WHERE locktype = 'advisory' "
    "AND objsubid = 1 AND ((classid::bigint << 32) | objid::bigint) = :k"
)


@pytest.fixture
async def make_container(database_url: str) -> AsyncIterator[ContainerFactory]:
    containers: list[Container] = []

    def build(role: str) -> Container:
        settings = Settings(
            _env_file=None,
            environment="test",
            database={"url": database_url},
            runtime={"heartbeat_interval_s": 0.05, "leader_retry_interval_s": 0.05},
        )
        container = Container.build(settings, role=role)
        containers.append(container)
        return container

    yield build
    for container in containers:
        await container.aclose()


async def _eventually(predicate: Callable[[], bool], within_s: float = 5.0) -> None:
    async with asyncio.timeout(within_s):
        while not predicate():  # noqa: ASYNC110 - polling captured logs, there is no event to await
            await asyncio.sleep(0.02)


async def test_only_one_engine_is_active_and_standby_takes_over(
    make_container: ContainerFactory, caplog: pytest.LogCaptureFixture
) -> None:
    primary_stop, standby_stop = asyncio.Event(), asyncio.Event()
    primary = asyncio.create_task(run_engine(make_container("engine-a"), primary_stop))
    await _eventually(lambda: "engine.active" in caplog.text)

    standby = asyncio.create_task(run_engine(make_container("engine-b"), standby_stop))
    await _eventually(lambda: "engine.standby" in caplog.text)
    await asyncio.sleep(0.2)  # several retry intervals: the standby must stay passive
    assert caplog.text.count("engine.active") == 1

    primary_stop.set()
    await asyncio.wait_for(primary, timeout=5)
    await _eventually(lambda: caplog.text.count("engine.active") == 2)

    standby_stop.set()
    await asyncio.wait_for(standby, timeout=5)


async def test_engine_stops_when_its_database_session_is_killed(
    make_container: ContainerFactory, caplog: pytest.LogCaptureFixture
) -> None:
    """Losing the lock's session (failover, partition, admin kill) must stop the engine at
    once — a standby may already be taking over, and two leaders could duplicate orders."""
    container = make_container("engine-doomed")
    engine = asyncio.create_task(run_engine(container, asyncio.Event()))
    await _eventually(lambda: "engine.active" in caplog.text)

    async with container.db.engine.connect() as admin:
        await admin.execute(text(TERMINATE_LOCK_HOLDER), {"k": lock_key(ENGINE_LEADER_LOCK)})
    with pytest.raises(LeadershipLostError):
        await asyncio.wait_for(engine, timeout=5)
