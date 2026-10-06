import copy
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml

from kterminal.domain.catalog import CatalogError, InstrumentCatalog, read_catalog_document
from kterminal.domain.instruments import ContractType
from kterminal.domain.symbols import AmbiguousSymbolError, UnknownSymbolError
from tests.fixtures.catalog import catalog_document, lab_catalog


def broken(mutate: Any) -> list[str]:
    doc = copy.deepcopy(catalog_document())
    mutate(doc)
    with pytest.raises(CatalogError) as excinfo:
        InstrumentCatalog.from_document(doc)
    return excinfo.value.problems


def test_document_round_trip_and_stable_fingerprint() -> None:
    catalog = lab_catalog()
    again = InstrumentCatalog.from_document(catalog.to_document())
    assert again.to_document() == catalog.to_document()
    assert again.fingerprint == catalog.fingerprint
    shuffled = copy.deepcopy(catalog_document())
    shuffled["listings"].reverse()
    shuffled["instruments"].reverse()
    assert InstrumentCatalog.from_document(shuffled).fingerprint == catalog.fingerprint


def test_fingerprint_changes_with_any_spec() -> None:
    doc = copy.deepcopy(catalog_document())
    doc["listings"][0]["contract_size"] = "10"
    assert InstrumentCatalog.from_document(doc).fingerprint != lab_catalog().fingerprint


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda d: d["instruments"][0].update(trading_hours="nope"), "unknown calendar 'nope'"),
        (lambda d: d["instruments"][0].update(trading_day="nope"), "unknown trading-day rule"),
        (lambda d: d["listings"][0].update(venue="ghost"), "unknown venue 'ghost'"),
        (lambda d: d["listings"][0].update(cost_profile=None), "tradable listings need a cost"),
        (lambda d: d["listings"][0].update(cost_profile="ghost"), "unknown cost profile"),
        (
            lambda d: d["listings"][0].update(cost_profile="crypto_perp_binance"),
            "charges funding, which only applies to PERPETUAL",
        ),
        (lambda d: d["listings"][1].update(symbol_format="{root}"), "requires a futures"),
        (
            lambda d: d["aliases"].append({"source": "*", "alias": "GOLD", "instrument": "XAGUSD"}),
            "maps to both XAUUSD and XAGUSD",
        ),
        (
            lambda d: d["aliases"].append(
                {"source": "*", "alias": "XAGUSD", "instrument": "XAUUSD"}
            ),
            "shadows canonical symbol XAGUSD",
        ),
        (
            lambda d: d["aliases"].append(
                {"source": "nowhere", "alias": "X", "instrument": "XAUUSD"}
            ),
            "unknown source",
        ),
        (
            lambda d: d["venue_profiles"][0]["execution"].update(XAUUSD="tradingview:XAUUSD"),
            "data-only and cannot be executed",
        ),
        (
            lambda d: d["venue_profiles"][0]["execution"].update(XAUUSD="cme:MNQ"),
            "mapped to a listing of MNQ",
        ),
        (lambda d: d["listings"][0].update(tick_size="abc"), "is not a number"),
        (lambda d: d.update(bogus=[]), "unknown top-level keys"),
    ],
)
def test_validation_catches_bad_references(mutate: Any, expected: str) -> None:
    problems = broken(mutate)
    assert any(expected in p for p in problems), problems


def test_duplicate_venue_symbol_rejected() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["listings"][1]["venue_symbol"] = "XAUUSD"

    assert any("already used by XAUUSD" in p for p in broken(mutate))


def test_lookups_and_profiles() -> None:
    catalog = lab_catalog()
    listing = catalog.execution_listing("lab_default", "XAUUSD")
    assert listing.key == "generic_mt5_cfd:XAUUSD"
    assert catalog.calendar_for(listing).id == "metals_otc"
    assert catalog.cost_calculator(listing).profile.id == "cfd_metals"
    assert [item.contract_type for item in catalog.listings_for("XAUUSD")] == [
        ContractType.CFD,
        ContractType.INDEX_DATA,
    ] or len(catalog.listings_for("XAUUSD")) == 2
    with pytest.raises(KeyError, match="does not trade"):
        catalog.execution_listing("lab_default", "GHOST")
    with pytest.raises(KeyError, match="unknown venue profile"):
        catalog.venue_profile("nope")


@pytest.mark.parametrize(
    ("raw", "source", "expected"),
    [
        ("XAUUSD", None, "XAUUSD"),
        ("xauusd", None, "XAUUSD"),
        ("GOLD", None, "XAUUSD"),
        ("NEAR", None, "NEARUSD"),
        ("NEARUSDT", None, "NEARUSD"),
        ("BINANCE:NEARUSDT.P", None, "NEARUSD"),
        ("NEARUSDT.P", "binance_usdm", "NEARUSD"),
        ("CME_MINI:MNQ1!", "tradingview", "MNQ"),
        ("MNQ1!", "tradingview", "MNQ"),
        ("MNQ1!", None, "MNQ"),  # any source's alias resolves when unambiguous
        ("OANDA:XAUUSD", "tradingview", "XAUUSD"),
        ("XAUUSD.r", "generic_mt5_cfd", "XAUUSD"),
        ("XAUUSDm", "generic_mt5_cfd", "XAUUSD"),
        (" MNQ ", None, "MNQ"),
    ],
)
def test_symbol_resolution(raw: str, source: str | None, expected: str) -> None:
    assert lab_catalog().resolve_symbol(raw, source).symbol == expected


def test_unknown_symbol_suggests() -> None:
    with pytest.raises(UnknownSymbolError, match="Did you mean: XAUUSD"):
        lab_catalog().resolve_symbol("XAUUSDX")
    with pytest.raises(UnknownSymbolError, match="empty"):
        lab_catalog().resolve_symbol("  ")


def test_ambiguous_venue_symbol_without_source() -> None:
    doc = copy.deepcopy(catalog_document())
    doc["listings"].append(
        {
            **doc["listings"][1],
            "venue": "binance_usdm",
            "instrument": "XAGUSD",
            "venue_symbol": "SAME",
        }
    )
    doc["listings"].append(
        {
            **doc["listings"][1],
            "venue": "generic_mt5_cfd",
            "instrument": "MNQ",
            "venue_symbol": "SAME",
        }
    )
    catalog = InstrumentCatalog.from_document(doc)
    with pytest.raises(AmbiguousSymbolError, match="specify the source"):
        catalog.resolve_symbol("SAME")
    assert catalog.resolve_symbol("SAME", "binance_usdm").symbol == "XAGUSD"


def test_venue_symbol_for_futures() -> None:
    assert lab_catalog().venue_symbol("MNQ", "cme", date(2026, 10, 6)) == "MNQZ6"
    assert lab_catalog().venue_symbol("NEARUSD", "binance_usdm", date(2026, 10, 6)) == "NEARUSDT"


def test_reading_a_directory(tmp_path: Path) -> None:
    doc = catalog_document()
    (tmp_path / "listings").mkdir()
    (tmp_path / "venues.yaml").write_text(yaml.safe_dump({"venues": doc["venues"]}))
    instruments = [dict(i) for i in doc["instruments"]]
    instruments[0]["aliases"] = ["GOLD"]
    (tmp_path / "instruments.yaml").write_text(
        yaml.safe_dump(
            {
                "instruments": instruments,
                "aliases": [
                    a for a in doc["aliases"] if a["source"] != "*" or a["alias"] != "GOLD"
                ],
            }
        )
    )
    cme = [dict(item) for item in doc["listings"] if item["venue"] == "cme"]
    for item in cme:
        item.pop("venue")
    (tmp_path / "listings" / "cme.yaml").write_text(
        yaml.safe_dump({"venue": "cme", "listings": cme})
    )
    others = [item for item in doc["listings"] if item["venue"] != "cme"]
    (tmp_path / "listings" / "others.yaml").write_text(yaml.safe_dump({"listings": others}))
    sessions = {
        k: doc[k]
        for k in ("trading_day_rules", "calendars", "session_windows", "session_classification")
    }
    (tmp_path / "sessions.yaml").write_text(yaml.safe_dump(sessions))
    (tmp_path / "costs.yaml").write_text(yaml.safe_dump({"cost_profiles": doc["cost_profiles"]}))
    (tmp_path / "venue_profiles.yaml").write_text(
        yaml.safe_dump({"venue_profiles": doc["venue_profiles"]})
    )
    loaded = InstrumentCatalog.load(tmp_path)
    assert loaded.fingerprint == lab_catalog().fingerprint
    (tmp_path / "extra.yaml").write_text("weird: 1\n")
    with pytest.raises(CatalogError, match="unknown key 'weird'"):
        read_catalog_document(tmp_path)
