"""The forward runtime on the real provider wiring: the data source map, the factory's
providers (Binance USD-M here, answering through a fake venue shaped like its documented
API on the fake clock) and an instrument skipped for want of an OANDA token."""

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select

from kterminal.config.settings import MarketDataSettings, Settings
from kterminal.db import models as m
from kterminal.db.session import Database
from kterminal.marketdata import factory
from kterminal.marketdata.base import MarketDataProvider
from kterminal.paper.feed import FeedConfig
from kterminal.paper.pg_forward import PostgresForwardStore
from kterminal.paper.runtime import PaperRuntime, RuntimeOptions
from kterminal.runtime.engine import NO_DATA_SOURCE, configured_providers, unavailable_reasons
from tests.fixtures.catalog import lab_catalog, write_catalog_dir
from tests.fixtures.forward import FakeTime
from tests.fixtures.marketdata import BinanceFake, make_candles
from tests.integration.paper.forward_helpers import MIN, START, lab_config, registry

pytestmark = pytest.mark.integration

SOURCES = """\
data_sources:
  NEARUSD: {provider: binance_usdm, symbol: NEARUSDT, volume: exchange}
  XAUUSD: {provider: oanda, symbol: XAU_USD, volume: tick}
"""


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    write_catalog_dir(tmp_path)
    (tmp_path / "catalog" / "data_sources.yaml").write_text(SOURCES)
    return Settings(_env_file=None, environment="test", paths={"config_dir": str(tmp_path)})


def fake_binance(monkeypatch: pytest.MonkeyPatch, clock: FakeTime) -> BinanceFake:
    venue = BinanceFake(
        "NEARUSDT", make_candles(START - timedelta(days=3), START + 120 * MIN), clock
    )
    original = factory.build_provider

    def build(
        provider: str, symbols: dict[str, str], md: MarketDataSettings, **kwargs: Any
    ) -> MarketDataProvider:
        assert provider == "binance_usdm"  # the only usable source in the map here
        return original(provider, symbols, md, clock=clock, transport=httpx.MockTransport(venue))

    monkeypatch.setattr(factory, "build_provider", build)
    return venue


async def test_the_runtime_trades_on_factory_providers_and_reports_skipped_instruments(
    settings: Settings, database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = FakeTime(START + timedelta(seconds=5))
    venue = fake_binance(monkeypatch, clock)
    providers = configured_providers(settings, lab_catalog(), ["NEARUSD", "XAUUSD", "MNQ"])
    assert set(providers) == {"NEARUSD"}
    assert providers["NEARUSD"].name == "binance_usdm"
    reasons = unavailable_reasons(providers)
    assert "OANDA_TOKEN" in reasons["XAUUSD"] and reasons["MNQ"] == NO_DATA_SOURCE

    clock.stop_at = START + 30 * MIN
    runtime = PaperRuntime(
        config=lab_config(),
        catalog=lab_catalog(),
        database=database,
        providers=providers,
        clock=clock,
        options=RuntimeOptions(warmup_days=2, feed=FeedConfig()),
        definitions=registry(),
        discover=False,
        wait=clock.wait,
        unavailable=reasons,
    )
    try:
        await runtime.run(asyncio.Event())
    finally:
        await providers.aclose()
    assert venue.requests  # every bar came through the provider's HTTP client

    store = PostgresForwardStore(database)
    (session,) = await store.open_sessions()
    progress = session.progress
    assert progress["inputs"]["XAUUSD"] == []  # no provider: no warm-up, no live segment
    assert [s["source"] for s in progress["inputs"]["NEARUSD"]] == ["binance_usdm"] * 2
    assert datetime.fromisoformat(progress["processed_through"]) == START + 29 * MIN
    async with database.session() as db:
        stored = (
            await db.scalars(
                select(m.CandleRow)
                .where(m.CandleRow.ts >= START, m.CandleRow.source == "binance_usdm")
                .order_by(m.CandleRow.ts)
            )
        ).all()
        warm = await db.scalar(
            select(func.count()).select_from(m.CandleRow).where(m.CandleRow.ts < START)
        )
        gold_trades = await db.scalar(
            select(func.count())
            .select_from(m.TradeRow)
            .where(m.TradeRow.strategy_instance_id == "sma_gold")
        )
    assert warm == progress["warmup_bars"] == 2_460  # fetched from the venue's history
    assert len(stored) == 29 == progress["input_bars"]
    first = next(c for c in venue.candles if c.t == START)
    assert (stored[0].open, stored[0].close, stored[0].volume) == (
        first.bar("NEARUSD", "binance_usdm").open,
        first.bar("NEARUSD", "binance_usdm").close,
        first.bar("NEARUSD", "binance_usdm").volume,
    )
    assert gold_trades == 0

    status = await store.read_status()
    assert status is not None
    assert status["instruments"]["XAUUSD"] == {
        "provider": None,
        "last_bar_open": None,
        "lag_seconds": None,
        "state": "no_provider",
        "last_error": reasons["XAUUSD"],
    }
    assert status["instruments"]["NEARUSD"]["provider"] == "binance_usdm"
    assert status["instruments"]["NEARUSD"]["state"] == "ok"
