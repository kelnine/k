"""A small, self-contained catalog for tests: the real sessions.yaml and costs.yaml
plus a fixed set of instruments, venues, listings and venue profiles (so tests do not
depend on the seed instrument data, which is configuration and will change)."""

from functools import cache
from pathlib import Path
from typing import Any

import yaml

from kterminal.domain.catalog import InstrumentCatalog

CATALOG_DIR = Path(__file__).resolve().parents[3] / "config" / "catalog"


def _yaml(name: str) -> dict[str, Any]:
    return yaml.safe_load((CATALOG_DIR / name).read_text(encoding="utf-8"))


def catalog_document() -> dict[str, Any]:
    sessions = _yaml("sessions.yaml")
    costs = _yaml("costs.yaml")
    return {
        "venues": [
            {
                "id": "generic_mt5_cfd",
                "name": "Generic MT5 CFD server",
                "kind": "PROP_FIRM",
                "platform": "MT5",
                "timezone": "UTC",
                "symbol_suffixes": [".r", "m"],
            },
            {
                "id": "cme",
                "name": "CME Globex",
                "kind": "EXCHANGE",
                "platform": "CME_GLOBEX",
                "timezone": "America/Chicago",
            },
            {
                "id": "binance_usdm",
                "name": "Binance USD-M futures",
                "kind": "EXCHANGE",
                "platform": "BINANCE",
            },
            {
                "id": "tradingview",
                "name": "TradingView",
                "kind": "SIGNAL_SOURCE",
                "platform": "TRADINGVIEW",
            },
        ],
        "instruments": [
            {
                "symbol": "XAUUSD",
                "name": "Gold / US Dollar",
                "asset_class": "METAL",
                "base": "XAU",
                "quote_currency": "USD",
                "tick_size": "0.01",
                "trading_hours": "metals_otc",
                "trading_day": "ny_1700",
                "underlying": "GOLD",
            },
            {
                "symbol": "XAGUSD",
                "name": "Silver / US Dollar",
                "asset_class": "METAL",
                "base": "XAG",
                "quote_currency": "USD",
                "tick_size": "0.001",
                "trading_hours": "metals_otc",
                "trading_day": "ny_1700",
                "underlying": "SILVER",
            },
            {
                "symbol": "MNQ",
                "name": "Micro E-mini Nasdaq-100",
                "asset_class": "INDEX",
                "base": "NDX",
                "quote_currency": "USD",
                "tick_size": "0.25",
                "trading_hours": "cme_globex_equity",
                "trading_day": "ny_1700",
                "underlying": "NASDAQ100",
                "futures": {
                    "root": "MNQ",
                    "contract_months": "HMUZ",
                    "expiry_rule": "third_friday",
                    "roll_days_before_expiry": 8,
                },
            },
            {
                "symbol": "NEARUSD",
                "name": "NEAR Protocol / US Dollar",
                "asset_class": "CRYPTO",
                "base": "NEAR",
                "quote_currency": "USD",
                "tick_size": "0.001",
                "trading_hours": "crypto_24x7",
                "trading_day": "utc_midnight",
            },
        ],
        "aliases": [
            {"source": "*", "alias": "GOLD", "instrument": "XAUUSD"},
            {"source": "*", "alias": "NEAR", "instrument": "NEARUSD"},
            {"source": "tradingview", "alias": "CME_MINI:MNQ1!", "instrument": "MNQ"},
            {"source": "tradingview", "alias": "MNQ1!", "instrument": "MNQ"},
        ],
        "listings": [
            {
                "venue": "generic_mt5_cfd",
                "instrument": "XAUUSD",
                "venue_symbol": "XAUUSD",
                "contract_type": "CFD",
                "tick_size": "0.01",
                "contract_size": "100",
                "quantity_unit": "LOTS",
                "min_qty": "0.01",
                "qty_step": "0.01",
                "quote_currency": "USD",
                "cost_profile": "cfd_metals",
            },
            {
                "venue": "generic_mt5_cfd",
                "instrument": "XAGUSD",
                "venue_symbol": "XAGUSD",
                "contract_type": "CFD",
                "tick_size": "0.001",
                "contract_size": "5000",
                "quantity_unit": "LOTS",
                "min_qty": "0.01",
                "qty_step": "0.01",
                "quote_currency": "USD",
                "cost_profile": "zero_cost",
            },
            {
                "venue": "cme",
                "instrument": "MNQ",
                "venue_symbol": "MNQ",
                "contract_type": "FUTURE",
                "tick_size": "0.25",
                "contract_size": "2",
                "quantity_unit": "CONTRACTS",
                "min_qty": "1",
                "qty_step": "1",
                "quote_currency": "USD",
                "cost_profile": "zero_cost",
                "symbol_format": "{root}{code}{y1}",
            },
            {
                "venue": "binance_usdm",
                "instrument": "NEARUSD",
                "venue_symbol": "NEARUSDT",
                "contract_type": "PERPETUAL",
                "tick_size": "0.001",
                "contract_size": "1",
                "quantity_unit": "BASE_UNITS",
                "min_qty": "1",
                "qty_step": "1",
                "quote_currency": "USDT",
                "min_notional": "5",
                "cost_profile": "zero_cost",
            },
            {
                "venue": "tradingview",
                "instrument": "XAUUSD",
                "venue_symbol": "OANDA:XAUUSD",
                "contract_type": "INDEX_DATA",
                "tick_size": "0.01",
                "contract_size": "1",
                "quantity_unit": "BASE_UNITS",
                "min_qty": "1",
                "qty_step": "1",
                "quote_currency": "USD",
                "tradable": False,
            },
        ],
        **{
            k: sessions.get(k, [])
            for k in ("trading_day_rules", "calendars", "session_windows", "session_classification")
        },
        "cost_profiles": costs["cost_profiles"],
        "venue_profiles": [
            {
                "id": "lab_default",
                "description": "test profile",
                "execution": {
                    "XAUUSD": "generic_mt5_cfd:XAUUSD",
                    "XAGUSD": "generic_mt5_cfd:XAGUSD",
                    "MNQ": "cme:MNQ",
                    "NEARUSD": "binance_usdm:NEARUSD",
                },
                "data": {"XAUUSD": "tradingview:XAUUSD"},
            },
        ],
    }


@cache
def lab_catalog() -> InstrumentCatalog:
    return InstrumentCatalog.from_document(catalog_document())


def write_catalog_dir(root: Path) -> Path:
    """Write the test catalog as a config directory (catalog/*.yaml) and return it."""
    doc = catalog_document()
    catalog_dir = root / "catalog"
    (catalog_dir / "listings").mkdir(parents=True, exist_ok=True)

    def dump(name: str, data: dict[str, Any]) -> None:
        (catalog_dir / name).write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    dump("venues.yaml", {"venues": doc["venues"]})
    dump("instruments.yaml", {"instruments": doc["instruments"], "aliases": doc["aliases"]})
    dump("listings/all.yaml", {"listings": doc["listings"]})
    dump(
        "sessions.yaml",
        {
            k: doc[k]
            for k in ("trading_day_rules", "calendars", "session_windows", "session_classification")
        },
    )
    dump("costs.yaml", {"cost_profiles": doc["cost_profiles"]})
    dump("venue_profiles.yaml", {"venue_profiles": doc["venue_profiles"]})
    return root
