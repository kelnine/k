"""apply_catalog: idempotent upserts, snapshots per fingerprint, retiring removed rows."""

from datetime import date, time
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from kterminal.core.ids import new_correlation_id, uuid7
from kterminal.db.models import (
    CatalogSnapshotRow,
    InstrumentListingRow,
    InstrumentRow,
    OrderRow,
    SessionWindowRow,
    SymbolAliasRow,
    TradingDayRuleRow,
    VenueProfileEntryRow,
    VenueProfileRow,
)
from kterminal.db.repositories.catalog import (
    CatalogDocumentError,
    apply_catalog,
    latest_catalog_snapshot,
)
from tests.integration.db.helpers import T0, catalog_document, insert_signal, seed_lab_subject

pytestmark = pytest.mark.integration


async def _ctids(session: AsyncSession, table: str) -> dict[str, str]:
    """Physical row versions: an UPDATE gives a row a new ctid, a no-op leaves it."""
    rows = await session.execute(text(f"SELECT ctid::text, * FROM {table}"))  # noqa: S608
    return {str(row[1:3]): row[0] for row in rows}


async def test_apply_populates_the_reference_tables(session: AsyncSession) -> None:
    snapshot = await apply_catalog(session, catalog_document(), "fp-1", applied_by="test")
    assert snapshot.created
    assert snapshot.fingerprint == "fp-1"

    gold = await session.get(InstrumentRow, "XAUUSD")
    assert gold is not None
    assert gold.tick_size == Decimal("0.01")
    assert gold.tags == ["metals"]
    mnq = await session.get(InstrumentRow, "MNQ")
    assert mnq is not None and mnq.futures is not None
    assert mnq.futures["contract_months"] == "HMUZ"

    perp = await session.get(InstrumentListingRow, ("binance_usdm", "NEARUSD"))
    assert perp is not None
    assert (perp.venue_symbol, perp.quote_currency, perp.min_notional) == (
        "NEARUSDT",
        "USDT",
        Decimal(5),
    )
    cfd = await session.get(InstrumentListingRow, ("generic_mt5_cfd", "XAUUSD"))
    assert cfd is not None
    assert cfd.contract_size == Decimal(100)
    assert cfd.verified_on == date(2026, 10, 1)
    assert cfd.aliases == ["GOLD"]
    data_only = await session.get(InstrumentListingRow, ("tradingview", "MNQ"))
    assert data_only is not None and data_only.tradable is False

    rule = await session.get(TradingDayRuleRow, "ny_1700")
    assert rule is not None and (rule.timezone, rule.rollover) == ("America/New_York", time(17))
    asia = await session.get(SessionWindowRow, "asia")
    assert asia is not None
    assert (asia.start_time, asia.end_time, asia.classification_rank) == (time(19), time(3), 0)
    orb = await session.get(SessionWindowRow, "ny_orb_15")
    assert orb is not None and orb.classification_rank is None

    entries = {
        e.instrument: (e.execution_venue, e.data_venue)
        for e in (await session.execute(select(VenueProfileEntryRow))).scalars()
    }
    assert entries == {
        "XAUUSD": ("generic_mt5_cfd", None),
        "NEARUSD": ("binance_usdm", None),
        "MNQ": ("cme", "tradingview"),
    }
    stored = await latest_catalog_snapshot(session)
    assert stored is not None
    assert (stored.id, stored.fingerprint, stored.applied_by) == (snapshot.id, "fp-1", "test")
    assert stored.document["instruments"][0]["tick_size"] == "0.01"


async def test_reapplying_is_idempotent(session: AsyncSession) -> None:
    first = await apply_catalog(session, catalog_document(), "fp-1", applied_by="test")
    before = {t: await _ctids(session, t) for t in ("instruments", "instrument_listings")}

    again = await apply_catalog(session, catalog_document(), "fp-1", applied_by="someone else")
    assert (again.id, again.created) == (first.id, False)
    assert {t: await _ctids(session, t) for t in before} == before  # no row was rewritten
    snapshots = (await session.execute(select(CatalogSnapshotRow.fingerprint))).scalars()
    assert list(snapshots) == ["fp-1"]


async def test_changes_and_removals(session: AsyncSession) -> None:
    await apply_catalog(session, catalog_document(), "fp-1", applied_by="test")
    # History that references catalog rows: a lab account on lab_default, a signal on
    # NEARUSD and an exit order on the XAUUSD CFD listing.
    version_id, account = await seed_lab_subject(session, "demo_sma_fast")
    await insert_signal(
        session, instance_id="demo_sma_fast", version_id=version_id, instrument="NEARUSD"
    )
    await session.execute(
        insert(OrderRow).values(
            id=uuid7(),
            client_order_id="kt-exit-1",
            account_id=account.account_id,
            purpose="EXIT",
            mode="PAPER",
            venue="generic_mt5_cfd",
            instrument="XAUUSD",
            venue_symbol="XAUUSD",
            side="SELL",
            order_type="MARKET",
            qty=Decimal("0.1"),
            status="FILLED",
            created_at=T0,
            correlation_id=new_correlation_id(),
        )
    )

    changed = catalog_document()
    changed["instruments"][2]["tick_size"] = "0.5"  # MNQ: changed value is updated
    changed["aliases"] = [a for a in changed["aliases"] if a["alias"] != "NEAR"]
    # NEARUSD disappears entirely (its listing, alias and profile entry with it).
    changed["instruments"] = [i for i in changed["instruments"] if i["symbol"] != "NEARUSD"]
    changed["listings"] = [x for x in changed["listings"] if x["instrument"] != "NEARUSD"]
    changed["aliases"] = [a for a in changed["aliases"] if a["instrument"] != "NEARUSD"]
    # XAUUSD moves to a new CFD venue; the old listing is still referenced by an order.
    new_venue = dict(changed["venues"][0], id="other_cfd", name="Other CFD")
    changed["venues"] = [v for v in changed["venues"] if v["id"] != "generic_mt5_cfd"]
    changed["venues"].append(new_venue)
    changed["listings"][0]["venue"] = "other_cfd"
    changed["venue_profiles"] = [
        {
            "id": "lab_v2",
            "description": "second profile",
            "execution": {"XAUUSD": "other_cfd:XAUUSD", "MNQ": "cme:MNQ"},
            "data": {},
        }
    ]
    snapshot = await apply_catalog(session, changed, "fp-2", applied_by="test")
    assert snapshot.created

    mnq = await session.get(InstrumentRow, "MNQ", populate_existing=True)
    assert mnq is not None and mnq.tick_size == Decimal("0.5")
    near = await session.get(InstrumentRow, "NEARUSD", populate_existing=True)
    assert near is not None and near.enabled is False  # referenced by a signal → disabled
    # Unreferenced rows are deleted outright.
    assert await session.get(InstrumentListingRow, ("binance_usdm", "NEARUSD")) is None
    aliases = set((await session.execute(select(SymbolAliasRow.alias))).scalars())
    assert aliases == {"GOLD", "CME_MINI:MNQ1!"}
    old_cfd = await session.get(
        InstrumentListingRow, ("generic_mt5_cfd", "XAUUSD"), populate_existing=True
    )
    assert old_cfd is not None and (old_cfd.enabled, old_cfd.tradable) == (False, False)
    new_cfd = await session.get(InstrumentListingRow, ("other_cfd", "XAUUSD"))
    assert new_cfd is not None and new_cfd.enabled and new_cfd.tradable
    old_profile = await session.get(VenueProfileRow, "lab_default", populate_existing=True)
    assert old_profile is not None and old_profile.enabled is False  # an account uses it
    profiles = await session.execute(select(VenueProfileEntryRow.venue_profile_id))
    assert set(profiles.scalars()) == {"lab_v2"}

    latest = await latest_catalog_snapshot(session)
    assert latest is not None and latest.fingerprint == "fp-2"

    # Re-applying the first catalog re-enables what it defines and makes it current again.
    restored = await apply_catalog(session, catalog_document(), "fp-1", applied_by="test")
    assert not restored.created
    near = await session.get(InstrumentRow, "NEARUSD", populate_existing=True)
    assert near is not None and near.enabled is True
    old_profile = await session.get(VenueProfileRow, "lab_default", populate_existing=True)
    assert old_profile is not None and old_profile.enabled is True
    latest = await latest_catalog_snapshot(session)
    assert latest is not None and latest.fingerprint == "fp-1"


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d["listings"][0].update(venue="nowhere"), "unknown venue"),
        (lambda d: d["listings"][0].update(tick_size=0.01), "decimals must be strings"),
        (lambda d: d["instruments"][0].update(trading_day="mars"), "unknown trading-day rule"),
        (lambda d: d["aliases"].append(dict(d["aliases"][0])), "duplicate alias"),
        (
            lambda d: d["venue_profiles"][0]["execution"].update(XAUUSD="cme:MNQ"),
            "not a listing of XAUUSD",
        ),
        (lambda d: d.update(session_classification=["nope"]), "unknown window"),
        (lambda d: d["listings"][0].pop("venue_symbol"), "missing required key"),
    ],
)
async def test_inconsistent_documents_are_rejected(
    session: AsyncSession, mutate: Any, message: str
) -> None:
    document = catalog_document()
    mutate(document)
    with pytest.raises(CatalogDocumentError, match=message):
        await apply_catalog(session, document, "fp-bad", applied_by="test")


async def test_latest_snapshot_of_an_empty_catalog(session: AsyncSession) -> None:
    assert await latest_catalog_snapshot(session) is None
