"""``kterminal engine`` paper-trades: once it leads, it runs the forward paper runtime."""

import asyncio
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml

from kterminal.config.settings import Settings
from kterminal.domain.catalog import InstrumentCatalog
from kterminal.domain.timeframes import M1
from kterminal.marketdata.base import MarketDataProvider
from kterminal.paper.pg_forward import PostgresForwardStore
from kterminal.runtime.container import Container
from kterminal.runtime.engine import run_engine
from tests.fixtures.catalog import write_catalog_dir
from tests.fixtures.forward import FakeProvider, market_bars

pytestmark = pytest.mark.integration

LAB = {
    "instances": [
        {
            "id": "breakout_near",
            "strategy": "demo_breakout",
            "params": {"channel_bars": 5, "trend_filter": False},
            "instruments": ["NEARUSD"],
            "timeframe": "5m",
        }
    ]
}


class WallClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


async def test_the_engine_runs_the_paper_runtime(fresh_url: str, tmp_path: Path) -> None:
    write_catalog_dir(tmp_path)
    (tmp_path / "lab.yaml").write_text(yaml.safe_dump(LAB))
    settings = Settings(
        _env_file=None,
        environment="test",
        database={"url": fresh_url},
        runtime={"heartbeat_interval_s": 0.05, "leader_retry_interval_s": 0.05},
        paths={"config_dir": str(tmp_path)},
    )
    built: list[FakeProvider] = []

    def factory(
        _: Settings, catalog: InstrumentCatalog, instruments: Sequence[str]
    ) -> Mapping[str, MarketDataProvider]:
        assert list(instruments) == ["NEARUSD"]
        now = M1.floor(datetime.now(UTC))
        provider = FakeProvider(
            "fake-crypto",
            market_bars(
                "NEARUSD",
                start=now - timedelta(days=2),
                minutes=2 * 1_440 + 10,
                price="3.000",
                tick="0.001",
                seed=3,
                source="fake-crypto",
            ),
            WallClock(),
        )
        built.append(provider)
        return {"NEARUSD": provider}

    container = Container.build(settings, role="engine-paper")
    stop = asyncio.Event()
    engine = asyncio.create_task(run_engine(container, stop, providers=factory))
    store = PostgresForwardStore(container.db)
    try:
        status: dict[str, Any] | None = None
        async with asyncio.timeout(30):
            while status is None or status.get("status") != "running":
                await asyncio.sleep(0.1)
                status = await store.read_status()
        assert status["instances"]["breakout_near"]["state"] == "RUNNING"
        assert status["instruments"]["NEARUSD"]["provider"] == "fake-crypto"
        (session,) = await store.open_sessions()
        assert session.progress["warmup_bars"] == 41 * 60  # (40 + 1) 1h periods of 1m bars
        stop.set()
        await asyncio.wait_for(engine, timeout=15)
        final = await store.read_status()
        assert final is not None and final["status"] == "stopped"
        assert built and built[0].closed  # providers are released on shutdown
    finally:
        stop.set()
        if not engine.done():
            engine.cancel()
        await container.aclose()
