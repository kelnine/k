"""The seed instrument catalog the terminal ships with (``terminal/config/catalog``).

``test_catalog.py`` exercises the loader on a small fixed fixture; these tests
load the REAL seed configuration and pin what every edit to it must keep: it
loads, the user's instruments exist, lab accounts execute on tradable listings
with costs, unverified specs are never tradable, and the symbols traders,
brokers and TradingView send resolve to the right canonical instrument.
"""

import re
from collections import Counter
from datetime import date
from decimal import Decimal
from functools import cache
from pathlib import Path

import pytest
import yaml

from kterminal.domain.catalog import InstrumentCatalog, read_catalog_document
from kterminal.domain.instruments import AssetClass, ContractType, FuturesSpec, Listing

# tests/unit/domain/<this file> -> parents[4] is terminal/ (tests chdir to a tmp dir).
CATALOG_DIR = Path(__file__).resolve().parents[4] / "config" / "catalog"

INSTRUMENTS = {
    "XAUUSD",
    "XAGUSD",
    "NAS100",
    "MNQ",
    "NQ",
    "US30",
    "US500",
    "EURUSD",
    "GBPUSD",
    "BTCUSD",
    "SOLUSD",
    "NEARUSD",
    "ZECUSD",
    "HYPEUSD",
    "PUMPUSD",
}
DATA_VENUE = "tradingview"
SIM_VENUE = "lab_sim"
UNVERIFIED_NOTE = "spec unverified — enable after syncing from the venue API"
GENERIC_NOTE = "generic simulation spec — not any exchange's contract"
TODAY = date(2026, 10, 6)


@cache
def seed() -> InstrumentCatalog:
    return InstrumentCatalog.load(CATALOG_DIR)


def _text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _venue_listings() -> list[Listing]:
    """Listings at real or simulated venues (everything except data feeds)."""
    return [item for item in seed().listings.values() if item.venue != DATA_VENUE]


# ── loading ──────────────────────────────────────────────────────────────────
def test_the_seed_catalog_loads_with_exactly_the_traded_instruments() -> None:
    assert CATALOG_DIR.is_dir()
    catalog = seed()
    assert set(catalog.instruments) == INSTRUMENTS
    assert "lab_default" in catalog.venue_profiles


def test_fingerprint_is_stable_across_loads_and_round_trips() -> None:
    first = InstrumentCatalog.load(CATALOG_DIR)
    second = InstrumentCatalog.load(CATALOG_DIR)
    assert first.fingerprint == second.fingerprint
    assert InstrumentCatalog.from_document(first.to_document()).fingerprint == first.fingerprint


def test_no_listing_row_is_silently_overwritten() -> None:
    # Listings are keyed venue:instrument and a later duplicate row would replace
    # an earlier one without a validation error, so the raw rows must be unique.
    rows = read_catalog_document(CATALOG_DIR)["listings"]
    keys = Counter(f"{row['venue']}:{row['instrument']}" for row in rows)
    assert [key for key, count in keys.items() if count > 1] == []
    assert len(rows) == len(seed().listings)


def test_each_listings_file_belongs_to_one_venue() -> None:
    files = sorted((CATALOG_DIR / "listings").glob("*.yaml"))
    assert {path.stem for path in files} <= set(seed().venues)
    for path in files:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert data["venue"] == path.stem, path.name
        assert all("venue" not in row for row in data["listings"]), path.name


# ── instruments ──────────────────────────────────────────────────────────────
def test_nasdaq_cfd_and_futures_share_an_underlying_but_not_a_symbol() -> None:
    catalog = seed()
    assert {catalog.instrument(s).underlying for s in ("NAS100", "MNQ", "NQ")} == {"NASDAQ100"}
    assert catalog.instrument("NAS100").futures is None
    for symbol in ("MNQ", "NQ"):
        assert catalog.instrument(symbol).futures == FuturesSpec(
            root=symbol,
            contract_months="HMUZ",
            expiry_rule="third_friday",
            roll_days_before_expiry=8,
        )
        assert catalog.instrument(symbol).trading_hours == "cme_globex_equity"


def test_canonicals_are_usd_and_crypto_listings_keep_their_quote() -> None:
    catalog = seed()
    for instrument in catalog.instruments.values():
        assert instrument.quote_currency == "USD", instrument.symbol
        listings = catalog.listings_for(instrument.symbol)
        if instrument.asset_class is AssetClass.CRYPTO:
            assert instrument.trading_hours == "crypto_24x7"
            assert instrument.trading_day == "utc_midnight"
            assert {item.quote_currency for item in listings} <= {"USD", "USDT", "USDC"}
        else:
            assert instrument.trading_day == "ny_1700", instrument.symbol


def test_canonical_tick_is_the_finest_verified_tradable_venue_tick() -> None:
    catalog = seed()
    for symbol, instrument in catalog.instruments.items():
        listings = [item for item in _venue_listings() if item.instrument == symbol]
        tradable = [item.tick_size for item in listings if item.tradable]
        verified = [item.tick_size for item in listings if item.tradable and item.verified_on]
        # Rounding strategy prices must never be coarser than a tradable venue.
        assert instrument.tick_size <= min(tradable), symbol
        # Without any verified venue spec the lab_sim generic tick is the only one.
        expected = min(verified) if verified else min(tradable)
        assert instrument.tick_size == expected, symbol


# ── listings ─────────────────────────────────────────────────────────────────
def test_every_tradable_listing_has_costs_and_positive_specs() -> None:
    catalog = seed()
    tradable = [item for item in catalog.listings.values() if item.tradable]
    assert tradable
    for item in tradable:
        assert item.cost_profile, item.key
        for value in (item.tick_size, item.contract_size, item.min_qty, item.qty_step):
            assert value > 0, item.key
        assert item.min_qty % item.qty_step == 0, item.key  # min is a whole number of steps
        catalog.cost_calculator(item)  # the profile fits the contract type
        if item.venue == SIM_VENUE:
            assert GENERIC_NOTE in _text(item.notes), item.key
            assert item.verified_on is None, item.key
        else:
            assert item.verified_on == TODAY, item.key
            assert item.source.startswith("https://"), item.key


def test_unverified_specs_are_never_tradable_and_say_why() -> None:
    for item in _venue_listings():
        if item.verified_on is None and item.venue != SIM_VENUE:
            assert not item.tradable, item.key
            assert UNVERIFIED_NOTE in _text(item.notes), item.key
        elif not item.tradable:
            # A verified spec is held back only when no cost profile fits yet.
            assert "cost profile" in _text(item.notes), item.key


def test_tradingview_listings_are_data_only() -> None:
    listings = [item for item in seed().listings.values() if item.venue == DATA_VENUE]
    assert {item.instrument for item in listings} == INSTRUMENTS
    for item in listings:
        assert not item.tradable, item.key
        assert item.cost_profile is None, item.key
        assert ":" in item.venue_symbol, item.key  # EXCHANGE:SYMBOL


def test_lab_sim_covers_only_instruments_without_a_verified_crypto_venue() -> None:
    catalog = seed()
    simulated = {item.instrument for item in catalog.listings.values() if item.venue == SIM_VENUE}
    assert simulated == {"NEARUSD", "ZECUSD", "PUMPUSD"}
    for symbol in simulated:
        assert not [
            item for item in _venue_listings() if item.instrument == symbol and item.verified_on
        ], symbol
        listing = catalog.listing(SIM_VENUE, symbol)
        assert listing.quote_currency == "USD"
        assert listing.contract_size == 1
        assert listing.contract_type is ContractType.PERPETUAL


def test_listing_names_never_collide_within_a_venue() -> None:
    names: dict[tuple[str, str], set[str]] = {}
    for item in seed().listings.values():
        for name in (item.venue_symbol, *item.aliases):
            names.setdefault((item.venue, name.upper()), set()).add(item.instrument)
    assert {key: found for key, found in names.items() if len(found) > 1} == {}


@pytest.mark.parametrize(
    ("key", "tick", "contract_size", "step"),
    [
        ("generic_mt5_cfd:XAUUSD", "0.01", "100", "0.01"),
        ("generic_mt5_cfd:XAGUSD", "0.001", "5000", "0.01"),
        ("generic_mt5_cfd:EURUSD", "0.00001", "100000", "0.01"),
        ("generic_mt5_cfd:NAS100", "0.01", "1", "0.01"),
        ("generic_mt5_cfd:US30", "0.01", "1", "0.01"),
        ("cme:MNQ", "0.25", "2", "1"),
        ("cme:NQ", "0.25", "20", "1"),
        ("binance_usdm:BTCUSD", "0.1", "1", "0.001"),
        ("okx_swap:BTCUSD", "0.1", "0.01", "0.01"),
        ("oanda:NAS100", "0.1", "1", "0.1"),
        ("hyperliquid:HYPEUSD", "0.001", "1", "0.01"),
    ],
)
def test_key_contract_specs(key: str, tick: str, contract_size: str, step: str) -> None:
    listing = seed().listings[key]
    assert (listing.tick_size, listing.contract_size, listing.qty_step) == (
        Decimal(tick),
        Decimal(contract_size),
        Decimal(step),
    )


@pytest.mark.parametrize(
    ("symbol", "tick"),
    [
        ("XAUUSD", "0.01"),  # not OANDA's 0.001: OANDA metals are not tradable yet
        ("XAGUSD", "0.001"),
        ("NAS100", "0.01"),
        ("EURUSD", "0.00001"),
        ("MNQ", "0.25"),
        ("BTCUSD", "0.01"),
        ("SOLUSD", "0.001"),
        ("HYPEUSD", "0.001"),
    ],
)
def test_key_canonical_ticks(symbol: str, tick: str) -> None:
    assert seed().instrument(symbol).tick_size == Decimal(tick)


@pytest.mark.parametrize(
    "key",
    [
        "oanda:XAUUSD",
        "oanda:XAGUSD",
        "oanda:EURUSD",
        "oanda:GBPUSD",
        "coinbase:BTCUSD",
    ],
)
def test_verified_specs_without_a_fitting_cost_profile_are_held_back(key: str) -> None:
    # OANDA sizes in units (a per-lot commission would be 100-100,000x too high);
    # Coinbase's entry-tier fees are 6-12x the only spot profile's 0.10 %.
    listing = seed().listings[key]
    assert listing.verified_on == TODAY
    assert not listing.tradable
    assert listing.cost_profile is None


def test_futures_listings_use_the_cost_profile_of_their_contract_size() -> None:
    expected = {"MNQ": "cme_micro_equity", "NQ": "cme_emini_equity"}
    futures = [item for item in _venue_listings() if item.instrument in expected]
    assert {item.venue for item in futures} == {"cme", "tradovate", "rithmic", "projectx", "ibkr"}
    for item in futures:
        assert item.cost_profile == expected[item.instrument], item.key


# ── venue profiles ───────────────────────────────────────────────────────────
def test_lab_default_executes_every_instrument_on_a_tradable_listing() -> None:
    catalog = seed()
    profile = catalog.venue_profile("lab_default")
    assert set(profile.execution) == INSTRUMENTS
    for symbol in INSTRUMENTS:
        listing = catalog.execution_listing("lab_default", symbol)
        assert listing.instrument == symbol
        assert listing.tradable and listing.cost_profile, listing.key
        catalog.cost_calculator(listing)
    assert set(profile.data) == INSTRUMENTS
    assert all(key.startswith(f"{DATA_VENUE}:") for key in profile.data.values())


@pytest.mark.parametrize(
    ("instrument", "venue"),
    [
        ("XAUUSD", "generic_mt5_cfd"),
        ("NAS100", "generic_mt5_cfd"),
        ("EURUSD", "generic_mt5_cfd"),
        ("MNQ", "cme"),
        ("NQ", "cme"),
        ("BTCUSD", "binance_usdm"),
        ("SOLUSD", "bybit_linear"),
        ("HYPEUSD", "hyperliquid"),
        ("NEARUSD", SIM_VENUE),
        ("ZECUSD", SIM_VENUE),
        ("PUMPUSD", SIM_VENUE),
    ],
)
def test_lab_default_venue_choices(instrument: str, venue: str) -> None:
    assert seed().execution_listing("lab_default", instrument).venue == venue


@pytest.mark.parametrize(
    ("profile_id", "venue"),
    [
        ("prop_cfd_mt5", "generic_mt5_cfd"),
        ("prop_cfd_tradelocker", "generic_tradelocker_cfd"),
        ("futures_cme", "cme"),
        ("crypto_binance_usdm", "binance_usdm"),
        ("crypto_bybit_linear", "bybit_linear"),
        ("crypto_hyperliquid", "hyperliquid"),
    ],
)
def test_family_profiles_hold_every_tradable_listing_of_their_venue(
    profile_id: str, venue: str
) -> None:
    catalog = seed()
    profile = catalog.venue_profile(profile_id)
    assert profile.description
    tradable = {
        item.instrument
        for item in catalog.listings.values()
        if item.venue == venue and item.tradable
    }
    assert set(profile.execution) == tradable
    assert all(key == f"{venue}:{symbol}" for symbol, key in profile.execution.items())


# ── symbol resolution ────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("raw", "source", "expected"),
    [
        ("MNQ1!", None, "MNQ"),
        ("CME_MINI:MNQ1!", "tradingview", "MNQ"),
        ("CME_MINI:NQ1!", "tradingview", "NQ"),
        ("NQ1!", None, "NQ"),
        ("US100", None, "NAS100"),
        ("USTEC", None, "NAS100"),
        ("NDX", None, "NAS100"),
        ("NASDAQ:NDX", "tradingview", "NAS100"),
        ("CAPITALCOM:US100", "tradingview", "NAS100"),
        ("TVC:NDQ", "tradingview", "NAS100"),
        ("US100.cash", "generic_mt5_cfd", "NAS100"),
        ("SPX500", None, "US500"),
        ("SPX", None, "US500"),
        ("SP:SPX", "tradingview", "US500"),
        ("DJ30", None, "US30"),
        ("WS30", None, "US30"),
        ("DOW", None, "US30"),
        ("GOLD", None, "XAUUSD"),
        ("XAU", None, "XAUUSD"),
        ("TVC:GOLD", "tradingview", "XAUUSD"),
        ("XAUUSD.r", "generic_mt5_cfd", "XAUUSD"),
        ("XAUUSDm", "generic_mt5_cfd", "XAUUSD"),
        ("XAU_USD", "oanda", "XAUUSD"),
        ("SILVER", None, "XAGUSD"),
        ("XAG", None, "XAGUSD"),
        ("EUR/USD", None, "EURUSD"),
        ("BTC", None, "BTCUSD"),
        ("BTCUSDT", None, "BTCUSD"),
        ("BINANCE:BTCUSDT.P", "tradingview", "BTCUSD"),
        ("BTC-USD", None, "BTCUSD"),
        ("SOL", None, "SOLUSD"),
        ("SOLUSDT", None, "SOLUSD"),
        ("NEAR", None, "NEARUSD"),
        ("NEARUSDT", None, "NEARUSD"),
        ("BINANCE:NEARUSDT.P", None, "NEARUSD"),
        ("BINANCE:NEARUSDT.P", "tradingview", "NEARUSD"),
        ("ZEC", None, "ZECUSD"),
        ("ZECUSDT", None, "ZECUSD"),
        ("HYPE", None, "HYPEUSD"),
        ("HYPEUSDT", None, "HYPEUSD"),
        ("HYPE", "hyperliquid", "HYPEUSD"),
        ("PUMP", None, "PUMPUSD"),
        ("PUMPUSDT", None, "PUMPUSD"),
        ("PUMPFUNUSDT", "bybit_linear", "PUMPUSD"),
        ("F.US.ENQ", "projectx", "NQ"),
        # ccxt linear-perp symbols (the part after ':' is the settle currency)
        ("BTC/USDT:USDT", None, "BTCUSD"),
        ("SOL/USDC:USDC", None, "SOLUSD"),
        ("ZEC/USDC:USDC", None, "ZECUSD"),
        ("HYPE/USDC:USDC", None, "HYPEUSD"),
        ("BTC-PERP-INTX", "coinbase_intx", "BTCUSD"),
        ("xyz:GOLD", "hyperliquid", "XAUUSD"),
        ("EURUSDUSDT", "bybit_linear", "EURUSD"),
        ("XAU-USDT-SWAP", "okx_swap", "XAUUSD"),
    ],
)
def test_key_symbols_resolve(raw: str, source: str | None, expected: str) -> None:
    assert seed().resolve_symbol(raw, source).symbol == expected


def test_aliases_never_shadow_a_canonical_symbol() -> None:
    catalog = seed()
    for alias in catalog.aliases:
        assert alias.alias.strip().upper() not in catalog.instruments, alias


# ── dated futures symbols ────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("instrument", "venue", "on", "expected"),
    [
        ("MNQ", "cme", TODAY, "MNQZ6"),
        ("MNQ", "tradovate", TODAY, "MNQZ6"),
        ("MNQ", "rithmic", TODAY, "MNQZ6"),
        ("MNQ", "projectx", TODAY, "CON.F.US.MNQ.Z26"),
        ("MNQ", "tradingview", TODAY, "CME_MINI:MNQZ2026"),
        ("MNQ", "ibkr", TODAY, "MNQ 202612"),
        ("NQ", "cme", TODAY, "NQZ6"),
        ("NQ", "projectx", TODAY, "CON.F.US.ENQ.Z26"),  # ProjectX names the NQ root ENQ
        ("NQ", "tradingview", TODAY, "CME_MINI:NQZ2026"),
        # Roll = 3rd Friday (2026-12-18) minus 8 days: from 2026-12-10 the front is H27.
        ("MNQ", "cme", date(2026, 12, 9), "MNQZ6"),
        ("MNQ", "cme", date(2026, 12, 10), "MNQH7"),
        ("MNQ", "projectx", date(2026, 12, 10), "CON.F.US.MNQ.H27"),
    ],
)
def test_dated_futures_symbols(instrument: str, venue: str, on: date, expected: str) -> None:
    assert seed().venue_symbol(instrument, venue, on) == expected
