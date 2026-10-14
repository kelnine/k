"""Choosing sources and building providers from settings and the data source map."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from kterminal.config.settings import MarketDataSettings, OandaEnvironment, Settings
from kterminal.core.clock import SimulatedClock
from kterminal.domain.catalog import InstrumentCatalog
from kterminal.marketdata.base import MarketDataProvider
from kterminal.marketdata.factory import (
    ProviderMap,
    build_provider,
    build_providers,
    load_data_sources,
    select_sources,
    settings_problems,
    unavailable_reason,
)
from kterminal.marketdata.providers import (
    BinanceUsdmProvider,
    CoinbaseProvider,
    CsvProvider,
    OandaProvider,
)
from kterminal.marketdata.sources import DataSourceError, DataSourceMap
from tests.fixtures.catalog import lab_catalog

CATALOG_DIR = Path(__file__).resolve().parents[4] / "config" / "catalog"
NOW = datetime(2026, 10, 9, 12, 0, 30, tzinfo=UTC)


def seed() -> tuple[InstrumentCatalog, DataSourceMap]:
    catalog = InstrumentCatalog.load(CATALOG_DIR)
    return catalog, DataSourceMap.load(CATALOG_DIR / "data_sources.yaml", catalog)


def md(**kwargs: Any) -> MarketDataSettings:
    return MarketDataSettings(**kwargs)


def test_without_a_token_or_csv_dir_oanda_and_csv_instruments_are_skipped() -> None:
    catalog, sources = seed()
    providers = build_providers(md(), sources, catalog)
    assert isinstance(providers, ProviderMap)
    assert isinstance(providers, dict)
    assert set(providers) == {"BTCUSD", "NEARUSD", "SOLUSD", "ZECUSD", "HYPEUSD", "PUMPUSD"}
    assert set(providers.skipped) == {
        "XAUUSD",
        "XAGUSD",
        "NAS100",
        "US30",
        "US500",
        "EURUSD",
        "GBPUSD",
        "MNQ",
        "NQ",
    }
    assert "KT_MARKETDATA__OANDA_TOKEN" in providers.skipped["XAUUSD"]
    assert "KT_MARKETDATA__CSV_DIR" in providers.skipped["MNQ"]
    assert all(isinstance(p, MarketDataProvider) for p in providers.values())
    assert {p.name for p in providers.instances} == {
        "binance_usdm",
        "bybit_linear",
        "coinbase",
        "hyperliquid",
        "binance_spot",
    }


async def test_one_provider_object_serves_all_its_instruments() -> None:
    catalog, sources = seed()
    providers = build_providers(
        md(oanda_token=SecretStr("t0ken"), csv_dir=Path("imports")), sources, catalog
    )
    assert not providers.skipped
    assert providers["BTCUSD"] is providers["NEARUSD"]
    assert providers["XAUUSD"] is providers["GBPUSD"]
    assert isinstance(providers["XAUUSD"], OandaProvider)
    assert isinstance(providers["MNQ"], CsvProvider)
    assert providers["MNQ"].path("MNQ") == Path("imports") / "MNQ.csv"
    oanda = providers["XAUUSD"]
    assert all(oanda.supports(i) for i in ("XAUUSD", "XAGUSD", "NAS100", "US30", "US500"))
    assert not oanda.supports("BTCUSD")
    assert len(providers.instances) == 7
    await providers.aclose()


def test_disabled_providers_fall_back_to_the_alternatives() -> None:
    catalog, sources = seed()
    settings = md(disabled_providers=["binance_usdm", "bybit_linear"])
    choices = select_sources(sources, settings)
    assert choices["BTCUSD"].source is not None
    assert choices["BTCUSD"].source.provider == "coinbase"
    assert choices["BTCUSD"].is_fallback
    assert "binance_usdm is disabled" in choices["BTCUSD"].reason
    assert choices["SOLUSD"].source is not None
    assert choices["SOLUSD"].source.symbol == "SOL-USD"
    assert choices["ZECUSD"].is_fallback is False
    providers = build_providers(settings, sources, catalog)
    assert isinstance(providers["BTCUSD"], CoinbaseProvider)
    assert providers["BTCUSD"] is providers["ZECUSD"]
    assert providers.choices["BTCUSD"].is_fallback


def test_an_instrument_without_any_usable_source_is_skipped_with_every_reason() -> None:
    catalog, sources = seed()
    settings = md(disabled_providers=["coinbase", "binance_usdm", "hyperliquid"])
    providers = build_providers(settings, sources, catalog)
    assert "BTCUSD" not in providers
    assert providers.skipped["BTCUSD"] == (
        "binance_usdm is disabled (KT_MARKETDATA__DISABLED_PROVIDERS); "
        "coinbase is disabled (KT_MARKETDATA__DISABLED_PROVIDERS); "
        "hyperliquid is disabled (KT_MARKETDATA__DISABLED_PROVIDERS)"
    )


def test_only_the_requested_instruments_are_built() -> None:
    catalog, sources = seed()
    providers = build_providers(md(), sources, catalog, instruments=["ZECUSD", "XAUUSD"])
    assert list(providers) == ["ZECUSD"]
    assert list(providers.skipped) == ["XAUUSD"]
    with pytest.raises(DataSourceError, match="no data source for ETHUSD"):
        build_providers(md(), sources, catalog, instruments=["ETHUSD"])


def test_settings_problems_are_reported() -> None:
    assert settings_problems(md(disabled_providers=["kraken"])) == [
        "KT_MARKETDATA__DISABLED_PROVIDERS: unknown provider 'kraken' (known: binance_spot, "
        "binance_usdm, bybit_linear, coinbase, csv, hyperliquid, oanda)"
    ]
    assert settings_problems(md(base_urls={"csv": "https://x", "coinbase": "http://x"})) == [
        "KT_MARKETDATA__BASE_URLS: 'csv' is not an HTTP provider",
        "KT_MARKETDATA__BASE_URLS: coinbase must be an https:// URL",
    ]
    _, sources = seed()
    with pytest.raises(DataSourceError, match="kraken"):
        select_sources(sources, md(disabled_providers=["kraken"]))


def test_a_map_that_does_not_fit_the_catalog_is_refused() -> None:
    _, sources = seed()
    with pytest.raises(DataSourceError, match="unknown instrument"):
        build_providers(md(), sources, lab_catalog())


def test_unavailable_reasons() -> None:
    assert unavailable_reason("coinbase", md()) is None
    assert unavailable_reason("oanda", md(oanda_token=SecretStr("  "))) is not None
    assert unavailable_reason("oanda", md(oanda_token=SecretStr("x"))) is None
    assert unavailable_reason("csv", md(csv_dir=Path("d"))) is None
    with pytest.raises(DataSourceError, match="needs an API token"):
        build_provider("oanda", {"XAUUSD": "XAU_USD"}, md())
    with pytest.raises(DataSourceError, match="must be an https:// URL"):
        build_provider("coinbase", {"ZECUSD": "ZEC-USD"}, md(base_urls={"coinbase": "http://x"}))


async def test_built_providers_use_the_settings() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"instrument": "XAU_USD", "candles": []})

    settings = md(
        oanda_token=SecretStr("live-token"),
        oanda_environment=OandaEnvironment.LIVE,
        request_timeout_s=4,
        close_delay_s=5,
    )
    provider = build_provider(
        "oanda",
        {"XAUUSD": "XAU_USD"},
        settings,
        clock=SimulatedClock(NOW),
        transport=httpx.MockTransport(handler),
    )
    start = NOW - timedelta(minutes=5)
    assert await provider.history("XAUUSD", start, NOW) == []
    (request,) = requests
    assert request.url.host == "api-fxtrade.oanda.com"
    assert request.headers["authorization"] == "Bearer live-token"
    assert request.extensions["timeout"]["connect"] == 4
    await provider.aclose()

    override = build_provider(
        "binance_usdm",
        {"BTCUSD": "BTCUSDT"},
        md(base_urls={"binance_usdm": "https://fapi.example.test"}),
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[])),
    )
    assert isinstance(override, BinanceUsdmProvider)
    assert str(override._client.base_url) == "https://fapi.example.test"


def test_load_data_sources_follows_the_settings(tmp_path: Path) -> None:
    catalog = lab_catalog()
    path = tmp_path / "sources.yaml"
    path.write_text(
        "data_sources:\n  NEARUSD: {provider: coinbase, symbol: NEAR-USD, volume: exchange}\n"
    )
    settings = Settings(_env_file=None, marketdata={"sources_file": path})  # type: ignore[call-arg]
    assert load_data_sources(settings, catalog).instruments == ("NEARUSD",)
    default = Settings(_env_file=None, paths={"config_dir": tmp_path})  # type: ignore[call-arg]
    assert default.paths.data_sources == tmp_path / "catalog" / "data_sources.yaml"
