"""``kterminal data sources`` and ``kterminal data fetch``."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from kterminal.cli import EXIT_CONFIG_ERROR, app
from kterminal.config.settings import MarketDataSettings
from kterminal.core.clock import SimulatedClock
from kterminal.marketdata import factory
from kterminal.marketdata.base import MarketDataProvider
from kterminal.marketdata.csv_import import read_bars_csv
from tests.fixtures.catalog import write_catalog_dir
from tests.fixtures.marketdata import BinanceFake, CoinbaseFake, FakeVenue, make_candles

runner = CliRunner()
MINUTE = timedelta(minutes=1)
NOW = datetime(2026, 10, 9, 12, 0, 30, tzinfo=UTC)
FORMING = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)

SOURCES = """\
data_sources:
  NEARUSD:
    provider: binance_usdm
    symbol: NEARUSDT
    volume: exchange
    note: The perpetual.
    alternatives:
      - {provider: coinbase, symbol: NEAR-USD, volume: exchange, note: USD spot}
  XAUUSD: {provider: oanda, symbol: XAU_USD, volume: tick, note: Mid prices.}
  MNQ: {provider: csv, symbol: "CME_MINI:MNQ1!", volume: exchange}
"""


@pytest.fixture
def config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    write_catalog_dir(tmp_path)
    (tmp_path / "catalog" / "data_sources.yaml").write_text(SOURCES)
    monkeypatch.setenv("KT_PATHS__CONFIG_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def venues(monkeypatch: pytest.MonkeyPatch) -> dict[str, FakeVenue]:
    """Route the CLI's providers to fake venues on a fixed clock."""
    clock = SimulatedClock(NOW)
    candles = make_candles(FORMING - 90 * MINUTE, FORMING)
    fakes: dict[str, FakeVenue] = {
        "binance_usdm": BinanceFake("NEARUSDT", candles, clock),
        "coinbase": CoinbaseFake("NEAR-USD", candles, clock),
    }
    original = factory.build_provider

    def build(
        provider: str, symbols: dict[str, str], settings: MarketDataSettings, **kwargs: Any
    ) -> MarketDataProvider:
        fake = fakes.get(provider)
        transport = httpx.MockTransport(fake) if fake is not None else None
        return original(provider, symbols, settings, clock=clock, transport=transport)

    monkeypatch.setattr(factory, "build_provider", build)
    return fakes


def test_data_sources_shows_choices_and_reasons(config_dir: Path) -> None:
    result = runner.invoke(app, ["data", "sources", "--notes"])
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    near = next(line for line in lines if line.strip().startswith("NEARUSD"))
    assert near.split()[:5] == ["NEARUSD", "binance_usdm", "NEARUSDT", "exchange", "configured"]
    xau = next(line for line in lines if line.strip().startswith("XAUUSD"))
    assert "skipped: oanda needs an API token" in xau
    assert "skipped: csv needs a directory" in next(
        line for line in lines if line.strip().startswith("MNQ")
    )
    assert "The perpetual." in result.output
    assert "No data source: XAGUSD" in result.output
    assert "oanda         oanda needs an API token" in result.output


def test_data_sources_with_a_disabled_provider_uses_the_alternative(
    config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KT_MARKETDATA__DISABLED_PROVIDERS", "binance_usdm")
    monkeypatch.setenv("KT_MARKETDATA__OANDA_TOKEN", "secret-oanda-token")
    result = runner.invoke(app, ["data", "sources"])
    assert result.exit_code == 0, result.output
    near = next(line for line in result.output.splitlines() if "NEARUSD" in line)
    assert "coinbase" in near
    assert "NEAR-USD" in near
    assert "configured (alternative: binance_usdm is disabled" in near
    xau = next(line for line in result.output.splitlines() if "XAUUSD" in line)
    assert xau.rstrip().endswith("configured")
    assert "secret-oanda-token" not in result.output


def test_data_sources_reports_an_invalid_map(config_dir: Path) -> None:
    (config_dir / "catalog" / "data_sources.yaml").write_text(
        "data_sources:\n  NEARUSD: {provider: kraken, symbol: X, volume: exchange}\n"
        "  GOLD: {provider: oanda, symbol: XAU_USD, volume: tick}\n"
    )
    result = runner.invoke(app, ["data", "sources"])
    assert result.exit_code == EXIT_CONFIG_ERROR
    assert "unknown provider 'kraken'" in result.output
    assert "data source GOLD: unknown instrument" in result.output


def test_data_sources_reports_invalid_settings(
    config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KT_MARKETDATA__DISABLED_PROVIDERS", "binance")
    result = runner.invoke(app, ["data", "sources"])
    assert result.exit_code == EXIT_CONFIG_ERROR
    assert "unknown provider 'binance'" in result.output


def test_data_fetch_writes_closed_bars_to_csv(
    config_dir: Path, venues: dict[str, FakeVenue], tmp_path: Path
) -> None:
    out = tmp_path / "near.csv"
    result = runner.invoke(
        app,
        ["data", "fetch", "NEAR", "--start", "2026-10-09T11:00", "--end", "2026-10-09T13:00Z",
         "--out", str(out)],
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    assert "60 bars of NEARUSD from binance_usdm NEARUSDT (exchange volume)" in result.output
    assert "2026-10-09 11:00 → 2026-10-09 11:59 UTC" in result.output
    bars = read_bars_csv(out, "NEARUSD", source="binance_usdm")
    expected = [c.bar("NEARUSD", "binance_usdm") for c in venues["binance_usdm"].candles]
    assert bars == [b for b in expected if b.open_time >= FORMING - 60 * MINUTE][:60]
    assert len(venues["binance_usdm"].requests) == 1


def test_data_fetch_from_a_chosen_alternative(
    config_dir: Path, venues: dict[str, FakeVenue], tmp_path: Path
) -> None:
    out = tmp_path / "near.csv"
    args = ["data", "fetch", "NEARUSD", "--start", "2026-10-09T11:50", "--end", "2026-10-09T12:00"]
    result = runner.invoke(app, [*args, "--out", str(out), "--provider", "coinbase"])
    assert result.exit_code == 0, result.output
    assert "10 bars of NEARUSD from coinbase NEAR-USD" in result.output
    assert venues["binance_usdm"].requests == []
    missing = runner.invoke(app, [*args, "--out", str(out), "--provider", "bybit_linear"])
    assert missing.exit_code == 1
    assert "NEARUSD has no bybit_linear source (configured: binance_usdm, coinbase)" in (
        missing.output
    )


def test_data_fetch_from_imported_files(
    config_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    imports = tmp_path / "imports"
    imports.mkdir()
    start = int(datetime(2026, 10, 5, 13, 30, tzinfo=UTC).timestamp())
    rows = "".join(f"{start + i * 60},20100,20101,20099,20100.5,{i}\n" for i in range(30))
    (imports / "MNQ.csv").write_text("time,open,high,low,close,Volume\n" + rows)
    monkeypatch.setenv("KT_MARKETDATA__CSV_DIR", str(imports))
    out = tmp_path / "slice.csv"
    result = runner.invoke(
        app,
        ["data", "fetch", "MNQ1!", "--start", "2026-10-05T09:40-04:00", "--end",
         "2026-10-05T09:45-04:00", "--out", str(out)],
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    assert "5 bars of MNQ from csv CME_MINI:MNQ1!" in result.output
    assert len(read_bars_csv(out, "MNQ", source="csv")) == 5


def test_data_fetch_refusals(
    config_dir: Path, venues: dict[str, FakeVenue], tmp_path: Path
) -> None:
    out = str(tmp_path / "x.csv")
    window = ["--start", "2026-10-09T11:00", "--end", "2026-10-09T12:00", "--out", out]
    no_token = runner.invoke(app, ["data", "fetch", "XAUUSD", *window])
    assert no_token.exit_code == EXIT_CONFIG_ERROR
    assert "XAUUSD: no usable data source: oanda needs an API token" in no_token.output
    chosen = runner.invoke(app, ["data", "fetch", "XAUUSD", *window, "--provider", "oanda"])
    assert chosen.exit_code == EXIT_CONFIG_ERROR
    no_source = runner.invoke(app, ["data", "fetch", "XAGUSD", *window])
    assert no_source.exit_code == 1
    assert "XAGUSD has no data source" in no_source.output
    unknown = runner.invoke(app, ["data", "fetch", "DOGE", *window])
    assert unknown.exit_code == 1
    bad_date = runner.invoke(app, ["data", "fetch", "NEARUSD", *window[:4], "--end", "soon"])
    assert bad_date.exit_code == 2
    backwards = runner.invoke(
        app,
        ["data", "fetch", "NEARUSD", "--start", "2026-10-09", "--end", "2026-10-08", "--out", out],
    )
    assert backwards.exit_code == 2
    assert not Path(out).exists()


def test_data_fetch_reports_venue_failures(
    config_dir: Path, venues: dict[str, FakeVenue], tmp_path: Path
) -> None:
    venues["binance_usdm"].script.append(
        httpx.Response(
            451, json={"code": 0, "msg": "Service unavailable from a restricted location"}
        )
    )
    out = tmp_path / "x.csv"
    result = runner.invoke(
        app,
        ["data", "fetch", "NEARUSD", "--start", "2026-10-09T11:00", "--end", "2026-10-09T12:00",
         "--out", str(out)],
    )  # fmt: skip
    assert result.exit_code == 1
    assert "fetch failed: binance_usdm GET /fapi/v1/klines: HTTP 451" in result.output
    assert not out.exists()
