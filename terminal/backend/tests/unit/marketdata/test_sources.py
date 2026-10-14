"""The data source map: the seed file and the strict loader."""

from functools import cache
from pathlib import Path
from typing import Any

import pytest
import yaml

from kterminal.domain.catalog import InstrumentCatalog
from kterminal.marketdata.sources import (
    PROVIDERS,
    DataSource,
    DataSourceError,
    DataSourceMap,
    VolumeKind,
)
from tests.fixtures.catalog import lab_catalog, write_catalog_dir

# tests/unit/marketdata/<this file> -> parents[4] is terminal/
CATALOG_DIR = Path(__file__).resolve().parents[4] / "config" / "catalog"
SEED_FILE = CATALOG_DIR / "data_sources.yaml"

# The defaults asked for: (provider, symbol, volume) per instrument.
DEFAULTS = {
    "XAUUSD": ("oanda", "XAU_USD", "tick"),
    "XAGUSD": ("oanda", "XAG_USD", "tick"),
    "NAS100": ("oanda", "NAS100_USD", "tick"),
    "US30": ("oanda", "US30_USD", "tick"),
    "US500": ("oanda", "SPX500_USD", "tick"),
    "EURUSD": ("oanda", "EUR_USD", "tick"),
    "GBPUSD": ("oanda", "GBP_USD", "tick"),
    "BTCUSD": ("binance_usdm", "BTCUSDT", "exchange"),
    "NEARUSD": ("binance_usdm", "NEARUSDT", "exchange"),
    "SOLUSD": ("bybit_linear", "SOLUSDT", "exchange"),
    "ZECUSD": ("coinbase", "ZEC-USD", "exchange"),
    "HYPEUSD": ("hyperliquid", "HYPE", "exchange"),
    "PUMPUSD": ("binance_spot", "PUMPUSDT", "exchange"),
    "MNQ": ("csv", "CME_MINI:MNQ1!", "exchange"),
}
# TradingView exchange prefix (and perpetual suffix) → the provider serving the same feed
TRADINGVIEW_FEED = {
    ("OANDA", False): "oanda",
    ("BINANCE", True): "binance_usdm",
    ("BINANCE", False): "binance_spot",
    ("BYBIT", True): "bybit_linear",
    ("COINBASE", False): "coinbase",
    ("HYPERLIQUID", True): "hyperliquid",
    ("CME_MINI", False): "csv",
}


@cache
def seed_catalog() -> InstrumentCatalog:
    return InstrumentCatalog.load(CATALOG_DIR)


@cache
def seed_map() -> DataSourceMap:
    return DataSourceMap.load(SEED_FILE, seed_catalog())


# ── the seed map ─────────────────────────────────────────────────────────────
def test_seed_map_has_the_requested_defaults() -> None:
    sources = seed_map()
    for instrument, (provider, symbol, volume) in DEFAULTS.items():
        primary = sources.primary(instrument)
        assert (primary.provider, primary.symbol, primary.volume.value) == (
            provider,
            symbol,
            volume,
        ), instrument
        assert primary.note, f"{instrument} has no note"


def test_seed_map_covers_every_instrument_the_lab_trades() -> None:
    lab_default = seed_catalog().venue_profile("lab_default")
    assert set(lab_default.execution) <= set(seed_map().instruments)


def test_seed_primaries_are_the_feeds_the_venue_profile_charts() -> None:
    """Each primary source is the venue behind the instrument's TradingView data listing."""
    catalog = seed_catalog()
    for instrument, key in catalog.venue_profile("lab_default").data.items():
        feed = catalog.listings[key].venue_symbol  # e.g. BINANCE:BTCUSDT.P
        exchange, _, ticker = feed.partition(":")
        provider = TRADINGVIEW_FEED[(exchange, ticker.endswith(".P"))]
        assert seed_map().primary(instrument).provider == provider, instrument


def test_seed_alternatives_exist_for_the_geo_restricted_venues() -> None:
    sources = seed_map()
    for instrument in ("BTCUSD", "NEARUSD", "SOLUSD"):
        providers = [s.provider for s in sources.chain(instrument)]
        assert "coinbase" in providers, instrument
    assert sources.source("BTCUSD", "coinbase").symbol == "BTC-USD"


def test_the_catalog_loader_ignores_the_data_source_map(tmp_path: Path) -> None:
    write_catalog_dir(tmp_path)
    (tmp_path / "catalog" / "data_sources.yaml").write_text("data_sources: {not: [valid")
    InstrumentCatalog.load(tmp_path / "catalog")  # does not raise


# ── strict loading ───────────────────────────────────────────────────────────
def load(document: Any) -> DataSourceMap:
    return DataSourceMap.from_document(document, lab_catalog())


def entry(**overrides: Any) -> dict[str, Any]:
    return {"provider": "binance_usdm", "symbol": "NEARUSDT", "volume": "exchange", **overrides}


def problems(document: Any) -> list[str]:
    with pytest.raises(DataSourceError) as caught:
        load(document)
    return caught.value.problems


def test_a_valid_map_with_alternatives() -> None:
    sources = load(
        {
            "data_sources": {
                "NEARUSD": entry(
                    note="perp",
                    alternatives=[
                        {"provider": "coinbase", "symbol": "NEAR-USD", "volume": "exchange"}
                    ],
                ),
                "MNQ": {"provider": "csv", "symbol": "CME_MINI:MNQ1!", "volume": "exchange"},
                "XAUUSD": {"provider": "oanda", "symbol": "XAU_USD", "volume": "tick"},
            }
        }
    )
    assert sources.instruments == ("NEARUSD", "MNQ", "XAUUSD")
    assert len(sources) == 3
    assert sources.chain("NEARUSD") == (
        DataSource("NEARUSD", "binance_usdm", "NEARUSDT", VolumeKind.EXCHANGE, "perp"),
        DataSource("NEARUSD", "coinbase", "NEAR-USD", VolumeKind.EXCHANGE, ""),
    )
    with pytest.raises(KeyError, match="no data source for 'XAGUSD'"):
        sources.chain("XAGUSD")
    with pytest.raises(KeyError, match="has no bybit_linear source"):
        sources.source("NEARUSD", "bybit_linear")


@pytest.mark.parametrize(
    ("document", "problem"),
    [
        ([], "expected a mapping"),
        ({"data_sources": {}, "extra": 1}, "unknown top-level key(s) extra"),
        ({"data_sources": []}, "must be a mapping of instrument"),
        ({"data_sources": {"NEARUSD": entry(feed="x")}}, "unknown key(s) feed"),
        ({"data_sources": {"NEARUSD": {"provider": "coinbase"}}}, "missing symbol, volume"),
        ({"data_sources": {"NEARUSD": entry(provider="kraken")}}, "unknown provider 'kraken'"),
        ({"data_sources": {"NEARUSD": entry(volume="trades")}}, "volume must be one of"),
        ({"data_sources": {"NEARUSD": entry(volume="tick")}}, "delivers exchange volume, not tick"),
        ({"data_sources": {"NEARUSD": entry(symbol="near-usdt")}}, "is not a binance_usdm symbol"),
        ({"data_sources": {"NEARUSD": entry(symbol=True)}}, "symbol must be a string"),
        ({"data_sources": {"NEARUSD": "binance_usdm"}}, "expected a mapping, got str"),
        ({"data_sources": {"NEARUSD": entry(alternatives="coinbase")}}, "must be a list"),
        (
            {"data_sources": {"NEARUSD": entry(alternatives=[entry()])}},
            "provider binance_usdm listed more than once",
        ),
        (
            {"data_sources": {"NEARUSD": entry(alternatives=[entry(alternatives=[])])}},
            "alternative 1: unknown key(s) alternatives",
        ),
        ({"data_sources": {"XAUUSD": entry(provider="oanda", symbol="XAU_USD")}}, "not exchange"),
        ({"data_sources": {"XAUUSDX": entry()}}, "unknown instrument (did you mean XAUUSD"),
        ({"data_sources": {1: entry()}}, "instrument keys must be strings"),
        (
            {"data_sources": {"NEARUSD": entry(symbol="NEARUSDC")}},
            "symbol 'NEARUSDC' differs from the catalog listing binance_usdm:NEARUSD ('NEARUSDT')",
        ),
    ],
)
def test_invalid_maps_are_rejected(document: Any, problem: str) -> None:
    found = problems(document)
    assert any(problem in p for p in found), found


def test_every_problem_is_reported_at_once() -> None:
    found = problems(
        {
            "data_sources": {
                "NEARUSD": entry(provider="kraken"),
                "XAUUSD": entry(volume="none"),
                "MNQ": {"provider": "csv", "symbol": "x"},
            }
        }
    )
    assert len(found) == 3


def test_duplicate_yaml_keys_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "data_sources.yaml"
    path.write_text(
        "data_sources:\n"
        "  NEARUSD: {provider: binance_usdm, symbol: NEARUSDT, volume: exchange}\n"
        "  NEARUSD: {provider: coinbase, symbol: NEAR-USD, volume: exchange}\n"
    )
    with pytest.raises(DataSourceError, match="found duplicate key 'NEARUSD'"):
        DataSourceMap.load(path, lab_catalog())


def test_unreadable_and_invalid_files(tmp_path: Path) -> None:
    with pytest.raises(DataSourceError, match="cannot read"):
        DataSourceMap.load(tmp_path / "missing.yaml", lab_catalog())
    bad = tmp_path / "bad.yaml"
    bad.write_text("data_sources: {NEARUSD: [")
    with pytest.raises(DataSourceError, match="invalid YAML"):
        DataSourceMap.load(bad, lab_catalog())


def test_a_map_is_checked_against_another_catalog() -> None:
    sources = seed_map()
    found = sources.problems(lab_catalog())  # the small test catalog lacks most instruments
    assert any("data source BTCUSD: unknown instrument" in p for p in found)


def test_provider_registry_is_consistent() -> None:
    assert set(PROVIDERS) == {
        "binance_usdm",
        "binance_spot",
        "bybit_linear",
        "coinbase",
        "hyperliquid",
        "oanda",
        "csv",
    }
    for info in PROVIDERS.values():
        assert info.symbol_pattern.fullmatch(info.symbol_example), info.name
        assert info.venue in (None, info.name)


def test_seed_file_is_plain_yaml_with_one_top_level_key() -> None:
    document = yaml.safe_load(SEED_FILE.read_text(encoding="utf-8"))
    assert list(document) == ["data_sources"]
