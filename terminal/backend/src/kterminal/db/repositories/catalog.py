"""Persist the instrument catalog (venues, instruments, listings, sessions, costs).

The catalog lives in ``terminal/config/catalog/*.yaml``; the catalog loader
validates it and produces a *normalised document* plus its fingerprint.
:func:`apply_catalog` makes the reference tables match that document:

* everything in the document is upserted (rows that did not change are not
  touched, so ``updated_at`` means "last changed");
* aliases and venue-profile entries that are no longer in the document are
  deleted — they are pure configuration;
* venues, instruments, listings, calendars, rules, windows, cost profiles and
  venue profiles that are no longer in the document are deleted when nothing
  references them, and otherwise **disabled** (``enabled = false``; listings
  also ``tradable = false``) so the history that points at them (signals,
  trades, orders, accounts) stays intact;
* the document itself is stored once per fingerprint in ``catalog_snapshots``,
  so every signal, decision, trade and run can record exactly which
  specification it was sized and costed with.

Like every repository it never commits: the caller owns the transaction, so a
catalog is applied entirely or not at all.

Document shape (decimals are strings, times ``"HH:MM"``, dates ``"YYYY-MM-DD"``)::

    venues            [{id, name, kind, platform, timezone, symbol_suffixes, description}]
    instruments       [{symbol, name, asset_class, base, quote_currency, tick_size,
                        trading_hours, trading_day, underlying, futures, description, tags}]
    aliases           [{source, alias, instrument}]          # source "*" = global
    listings          [{venue, instrument, venue_symbol, contract_type, tick_size,
                        contract_size, quantity_unit, min_qty, qty_step, quote_currency,
                        max_qty, min_notional, pnl_model, trading_hours, cost_profile,
                        symbol_format, tradable, verified_on, source, notes, aliases}]
    trading_day_rules [{id, timezone, rollover, description?}]
    calendars         [{id, timezone, …}]                    # stored whole as jsonb
    session_windows   [{id, name, timezone, start, end, days, description}]
    session_classification [window id, …]                    # ordered
    cost_profiles     [{id, description, …}]                 # stored whole as jsonb
    venue_profiles    [{id, description, execution: {INSTR: "venue:INSTR"}, data: {…}}]
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Final
from uuid import UUID

from sqlalchemy import Table, and_, delete, func, or_, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from kterminal.core.errors import KTerminalError
from kterminal.core.ids import uuid7
from kterminal.db.audit import json_safe
from kterminal.db.models import (
    CatalogSnapshotRow,
    CostProfileRow,
    InstrumentListingRow,
    InstrumentRow,
    SessionWindowRow,
    SymbolAliasRow,
    TradingCalendarRow,
    TradingDayRuleRow,
    VenueProfileEntryRow,
    VenueProfileRow,
    VenueRow,
    table_of,
)
from kterminal.domain.sessions import parse_date, parse_time
from kterminal.observability.logging import get_logger

_log = get_logger(__name__)

_CHUNK: Final = 500  # rows per multi-row INSERT (PostgreSQL allows 32767 parameters)

type Row = dict[str, Any]
type Key = tuple[Any, ...]


class CatalogDocumentError(KTerminalError, ValueError):
    """The catalog document is malformed or refers to something it does not define."""


@dataclass(frozen=True, slots=True)
class CatalogSnapshot:
    """Result of :func:`apply_catalog`."""

    id: UUID
    fingerprint: str
    created: bool  # False when this fingerprint had been applied before


@dataclass(frozen=True, slots=True)
class StoredCatalogSnapshot:
    id: UUID
    fingerprint: str
    document: dict[str, Any]
    applied_at: datetime
    applied_by: str
    last_applied_at: datetime


# ── document parsing ─────────────────────────────────────────────────────────
def _items(document: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    value = document.get(key) or []
    if not isinstance(value, Sequence) or isinstance(value, str):
        raise CatalogDocumentError(f"catalog document: {key!r} must be a list")
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise CatalogDocumentError(f"catalog document: {key}[{index}] must be a mapping")
    return list(value)


def _req(item: Mapping[str, Any], key: str, where: str) -> Any:
    if item.get(key) is None:
        raise CatalogDocumentError(f"{where}: missing required key {key!r}")
    return item[key]


def _text(item: Mapping[str, Any], key: str, default: str = "") -> str:
    value = item.get(key)
    return default if value is None else str(value)


def _optional_text(item: Mapping[str, Any], key: str) -> str | None:
    value = item.get(key)
    return None if value is None or value == "" else str(value)


def _decimal(value: Any, where: str) -> Decimal:
    if isinstance(value, float):
        raise CatalogDocumentError(f"{where}: decimals must be strings, got float {value!r}")
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise CatalogDocumentError(f"{where}: invalid decimal {value!r}") from None
    if not result.is_finite():
        raise CatalogDocumentError(f"{where}: decimal must be finite, got {value!r}")
    return result


def _optional_decimal(item: Mapping[str, Any], key: str, where: str) -> Decimal | None:
    value = item.get(key)
    return None if value is None or value == "" else _decimal(value, f"{where}.{key}")


def _strings(value: Any, where: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str) or not isinstance(value, Iterable):
        raise CatalogDocumentError(f"{where}: expected a list of strings")
    return [str(v) for v in value]


def _bool(item: Mapping[str, Any], key: str, default: bool, where: str) -> bool:
    value = item.get(key, default)
    if not isinstance(value, bool):
        raise CatalogDocumentError(f"{where}.{key}: expected true or false, got {value!r}")
    return value


def _parse(fn: Any, value: Any, where: str) -> Any:
    try:
        return fn(value, where)
    except ValueError as exc:
        raise CatalogDocumentError(str(exc)) from None


@dataclass(frozen=True, slots=True)
class _Plan:
    """The document turned into table rows."""

    rules: list[Row]
    calendars: list[Row]
    windows: list[Row]
    costs: list[Row]
    venues: list[Row]
    instruments: list[Row]
    listings: list[Row]
    aliases: list[Row]
    profiles: list[Row]
    entries: list[Row]


def _unique(rows: list[Row], key: tuple[str, ...], kind: str) -> list[Row]:
    seen: set[Key] = set()
    for row in rows:
        value = tuple(row[k] for k in key)
        if value in seen:
            raise CatalogDocumentError(f"duplicate {kind} {':'.join(map(str, value))}")
        seen.add(value)
    return rows


def _plan(document: Mapping[str, Any]) -> _Plan:
    rules = [
        {
            "id": _req(r, "id", "trading_day_rules"),
            "timezone": _req(r, "timezone", f"trading_day_rules.{r.get('id')}"),
            "rollover": _parse(
                parse_time,
                _req(r, "rollover", f"trading_day_rules.{r.get('id')}"),
                f"trading_day_rules.{r.get('id')}.rollover",
            ),
            "description": _text(r, "description"),
            "enabled": True,
        }
        for r in _items(document, "trading_day_rules")
    ]
    calendars = [
        {
            "id": _req(c, "id", "calendars"),
            "timezone": _req(c, "timezone", f"calendars.{c.get('id')}"),
            "definition": json_safe(dict(c)),
            "description": _text(c, "description"),
            "enabled": True,
        }
        for c in _items(document, "calendars")
    ]
    classification = _strings(document.get("session_classification"), "session_classification")
    if len(set(classification)) != len(classification):
        raise CatalogDocumentError("session_classification lists a window twice")
    rank = {window_id: index for index, window_id in enumerate(classification)}
    windows = []
    for w in _items(document, "session_windows"):
        where = f"session_windows.{w.get('id')}"
        days = [d.upper() for d in _strings(_req(w, "days", where), f"{where}.days")]
        windows.append(
            {
                "id": _req(w, "id", "session_windows"),
                "name": _text(w, "name") or str(w["id"]),
                "timezone": _req(w, "timezone", where),
                "start_time": _parse(parse_time, _req(w, "start", where), f"{where}.start"),
                "end_time": _parse(parse_time, _req(w, "end", where), f"{where}.end"),
                "days": days,
                "description": _text(w, "description"),
                "classification_rank": rank.get(str(w["id"])),
                "enabled": True,
            }
        )
    window_ids = {w["id"] for w in windows}
    if unknown := sorted(set(classification) - window_ids):
        raise CatalogDocumentError(f"session_classification: unknown window(s) {unknown}")
    costs = [
        {
            "id": _req(c, "id", "cost_profiles"),
            "description": _text(c, "description"),
            "definition": json_safe(dict(c)),
            "enabled": True,
        }
        for c in _items(document, "cost_profiles")
    ]
    venues = [
        {
            "id": _req(v, "id", "venues"),
            "name": _text(v, "name") or str(v["id"]),
            "kind": _req(v, "kind", f"venues.{v.get('id')}"),
            "platform": _optional_text(v, "platform"),
            "timezone": _text(v, "timezone", "UTC"),
            "symbol_suffixes": _strings(v.get("symbol_suffixes"), f"venues.{v['id']}"),
            "description": _text(v, "description"),
            "enabled": True,
        }
        for v in _items(document, "venues")
    ]
    instruments = []
    for i in _items(document, "instruments"):
        where = f"instruments.{i.get('symbol')}"
        futures = i.get("futures")
        instruments.append(
            {
                "symbol": _req(i, "symbol", "instruments"),
                "name": _text(i, "name") or str(i["symbol"]),
                "asset_class": _req(i, "asset_class", where),
                "base": _text(i, "base"),
                "quote_currency": _req(i, "quote_currency", where),
                "tick_size": _decimal(_req(i, "tick_size", where), f"{where}.tick_size"),
                "trading_hours": _req(i, "trading_hours", where),
                "trading_day": _req(i, "trading_day", where),
                "underlying": _text(i, "underlying"),
                "futures": None if futures is None else json_safe(futures),
                "description": _text(i, "description"),
                "tags": _strings(i.get("tags"), f"{where}.tags"),
                "enabled": True,
            }
        )
    listings = []
    for item in _items(document, "listings"):
        where = f"listings.{item.get('venue')}:{item.get('instrument')}"
        verified = item.get("verified_on")
        listings.append(
            {
                "venue": _req(item, "venue", "listings"),
                "instrument": _req(item, "instrument", "listings"),
                "venue_symbol": _req(item, "venue_symbol", where),
                "contract_type": _req(item, "contract_type", where),
                "tick_size": _decimal(_req(item, "tick_size", where), f"{where}.tick_size"),
                "contract_size": _decimal(
                    _req(item, "contract_size", where), f"{where}.contract_size"
                ),
                "quantity_unit": _req(item, "quantity_unit", where),
                "min_qty": _decimal(_req(item, "min_qty", where), f"{where}.min_qty"),
                "qty_step": _decimal(_req(item, "qty_step", where), f"{where}.qty_step"),
                "max_qty": _optional_decimal(item, "max_qty", where),
                "min_notional": _optional_decimal(item, "min_notional", where),
                "quote_currency": _req(item, "quote_currency", where),
                "pnl_model": _text(item, "pnl_model", "LINEAR"),
                "trading_hours": _optional_text(item, "trading_hours"),
                "cost_profile": _optional_text(item, "cost_profile"),
                "symbol_format": _optional_text(item, "symbol_format"),
                "tradable": _bool(item, "tradable", True, where),
                "enabled": True,
                "aliases": _strings(item.get("aliases"), f"{where}.aliases"),
                "verified_on": (
                    None if not verified else _parse(parse_date, verified, f"{where}.verified_on")
                ),
                "source": _text(item, "source"),
                "notes": _text(item, "notes"),
            }
        )
    aliases = [
        {
            "source": _req(a, "source", "aliases"),
            "alias": _req(a, "alias", "aliases"),
            "instrument": _req(a, "instrument", f"aliases.{a.get('alias')}"),
        }
        for a in _items(document, "aliases")
    ]
    profiles, entries = [], []
    for p in _items(document, "venue_profiles"):
        profile_id = _req(p, "id", "venue_profiles")
        profiles.append({"id": profile_id, "description": _text(p, "description"), "enabled": True})
        entries.extend(_profile_entries(p, str(profile_id)))
    plan = _Plan(
        rules=_unique(rules, ("id",), "trading-day rule"),
        calendars=_unique(calendars, ("id",), "calendar"),
        windows=_unique(windows, ("id",), "session window"),
        costs=_unique(costs, ("id",), "cost profile"),
        venues=_unique(venues, ("id",), "venue"),
        instruments=_unique(instruments, ("symbol",), "instrument"),
        listings=_unique(listings, ("venue", "instrument"), "listing"),
        aliases=_unique(aliases, ("source", "alias"), "alias"),
        profiles=_unique(profiles, ("id",), "venue profile"),
        entries=entries,
    )
    _check_references(plan)
    return plan


def _listing_ref(value: Any, instrument: str, where: str) -> str:
    if not isinstance(value, str) or ":" not in value:
        raise CatalogDocumentError(f"{where}: expected 'venue:{instrument}', got {value!r}")
    venue, listed = value.split(":", 1)
    if listed != instrument:
        raise CatalogDocumentError(
            f"{where}: listing {value!r} is not a listing of {instrument} "
            f"(expected '{venue}:{instrument}')"
        )
    return venue


def _profile_entries(profile: Mapping[str, Any], profile_id: str) -> list[Row]:
    execution = profile.get("execution") or {}
    data = profile.get("data") or {}
    if not isinstance(execution, Mapping) or not isinstance(data, Mapping):
        raise CatalogDocumentError(f"venue_profiles.{profile_id}: execution/data must be mappings")
    if extra := sorted(set(data) - set(execution)):
        raise CatalogDocumentError(
            f"venue_profiles.{profile_id}: data listings for {extra} without an execution listing"
        )
    return [
        {
            "venue_profile_id": profile_id,
            "instrument": instrument,
            "execution_venue": _listing_ref(
                ref, instrument, f"venue_profiles.{profile_id}.execution.{instrument}"
            ),
            "data_venue": (
                None
                if data.get(instrument) is None
                else _listing_ref(
                    data[instrument], instrument, f"venue_profiles.{profile_id}.data.{instrument}"
                )
            ),
        }
        for instrument, ref in sorted(execution.items())
    ]


def _check_references(plan: _Plan) -> None:
    rules = {r["id"] for r in plan.rules}
    calendars = {c["id"] for c in plan.calendars}
    costs = {c["id"] for c in plan.costs}
    venues = {v["id"] for v in plan.venues}
    instruments = {i["symbol"] for i in plan.instruments}
    listings = {(item["venue"], item["instrument"]) for item in plan.listings}
    problems: list[str] = []
    for i in plan.instruments:
        if i["trading_hours"] not in calendars:
            problems.append(f"instrument {i['symbol']}: unknown calendar {i['trading_hours']!r}")
        if i["trading_day"] not in rules:
            problems.append(
                f"instrument {i['symbol']}: unknown trading-day rule {i['trading_day']!r}"
            )
    for item in plan.listings:
        key = f"listing {item['venue']}:{item['instrument']}"
        if item["venue"] not in venues:
            problems.append(f"{key}: unknown venue")
        if item["instrument"] not in instruments:
            problems.append(f"{key}: unknown instrument")
        if item["cost_profile"] is not None and item["cost_profile"] not in costs:
            problems.append(f"{key}: unknown cost profile {item['cost_profile']!r}")
        if item["trading_hours"] is not None and item["trading_hours"] not in calendars:
            problems.append(f"{key}: unknown calendar {item['trading_hours']!r}")
    problems.extend(
        f"alias {a['source']}:{a['alias']}: unknown instrument {a['instrument']!r}"
        for a in plan.aliases
        if a["instrument"] not in instruments
    )
    for e in plan.entries:
        for column in ("execution_venue", "data_venue"):
            venue = e[column]
            if venue is not None and (venue, e["instrument"]) not in listings:
                problems.append(
                    f"venue profile {e['venue_profile_id']}: no listing {venue}:{e['instrument']}"
                )
    if problems:
        raise CatalogDocumentError("catalog document is inconsistent: " + "; ".join(problems))


# ── writing ──────────────────────────────────────────────────────────────────
async def _upsert(
    session: AsyncSession, table: Table, rows: list[Row], key: tuple[str, ...]
) -> None:
    """Insert or update ``rows``; unchanged rows are not touched (``updated_at`` stays)."""
    for start in range(0, len(rows), _CHUNK):
        chunk = rows[start : start + _CHUNK]
        statement = pg_insert(table).values(chunk)
        columns = [c for c in chunk[0] if c not in key]
        if not columns:
            await session.execute(statement.on_conflict_do_nothing(index_elements=list(key)))
            continue
        changes: dict[str, Any] = {c: statement.excluded[c] for c in columns}
        if "updated_at" in table.c:
            changes["updated_at"] = func.now()
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=list(key),
                set_=changes,
                where=or_(*(table.c[c].is_distinct_from(statement.excluded[c]) for c in columns)),
            )
        )


async def _existing_keys(session: AsyncSession, table: Table, key: tuple[str, ...]) -> set[Key]:
    rows = await session.execute(select(*(table.c[k] for k in key)))
    return {tuple(row) for row in rows}


def _match(table: Table, key: tuple[str, ...], value: Key) -> Any:
    return and_(*(table.c[k] == v for k, v in zip(key, value, strict=True)))


async def _delete_missing(
    session: AsyncSession, table: Table, rows: list[Row], key: tuple[str, ...]
) -> int:
    stale = await _existing_keys(session, table, key) - {tuple(r[k] for k in key) for r in rows}
    if stale:
        columns = tuple_(*(table.c[k] for k in key))
        await session.execute(delete(table).where(columns.in_(sorted(stale))))
    return len(stale)


async def _retire_missing(
    session: AsyncSession,
    table: Table,
    rows: list[Row],
    key: tuple[str, ...],
    disabled: Mapping[str, Any],
) -> tuple[int, int]:
    """Delete stale rows that nothing references; disable the referenced ones."""
    stale = await _existing_keys(session, table, key) - {tuple(r[k] for k in key) for r in rows}
    deleted = disabled_count = 0
    for value in sorted(stale):
        try:
            async with session.begin_nested():
                await session.execute(delete(table).where(_match(table, key, value)))
            deleted += 1
        except IntegrityError:  # still referenced (history, accounts, …): keep, but disable
            await session.execute(
                update(table)
                .where(_match(table, key, value), table.c.enabled.is_(True))
                .values(**disabled, updated_at=func.now())
            )
            disabled_count += 1
    return deleted, disabled_count


async def apply_catalog(
    session: AsyncSession, document: Mapping[str, Any], fingerprint: str, applied_by: str
) -> CatalogSnapshot:
    """Make the reference tables match ``document`` and record it under ``fingerprint``."""
    if not fingerprint:
        raise CatalogDocumentError("a catalog fingerprint is required")
    plan = _plan(document)
    off = {"enabled": False}

    # Parents first, so every row the document adds can reference them.
    await _upsert(session, table_of(TradingDayRuleRow), plan.rules, ("id",))
    await _upsert(session, table_of(TradingCalendarRow), plan.calendars, ("id",))
    await _upsert(session, table_of(SessionWindowRow), plan.windows, ("id",))
    await _upsert(session, table_of(CostProfileRow), plan.costs, ("id",))
    await _upsert(session, table_of(VenueRow), plan.venues, ("id",))
    await _upsert(session, table_of(InstrumentRow), plan.instruments, ("symbol",))
    # Remove configuration that no longer exists before (re)writing listings, so a
    # listing that moved to another instrument cannot collide with its old row.
    entry_key = ("venue_profile_id", "instrument")
    alias_key = ("source", "alias")
    listing_key = ("venue", "instrument")
    removed = {
        "venue_profile_entries": await _delete_missing(
            session, table_of(VenueProfileEntryRow), plan.entries, entry_key
        ),
        "symbol_aliases": await _delete_missing(
            session, table_of(SymbolAliasRow), plan.aliases, alias_key
        ),
    }
    listing_off = {"enabled": False, "tradable": False}
    await _retire_missing(
        session, table_of(InstrumentListingRow), plan.listings, listing_key, listing_off
    )
    await _upsert(session, table_of(InstrumentListingRow), plan.listings, listing_key)
    await _upsert(session, table_of(SymbolAliasRow), plan.aliases, alias_key)
    await _upsert(session, table_of(VenueProfileRow), plan.profiles, ("id",))
    await _upsert(session, table_of(VenueProfileEntryRow), plan.entries, entry_key)
    # Children are gone or rewritten: retire what the document no longer has. Stale
    # listings get a second pass — a profile entry may only now have moved off them.
    retired = {
        "instrument_listings": await _retire_missing(
            session, table_of(InstrumentListingRow), plan.listings, listing_key, listing_off
        )
    }
    for model, rows, key in (
        (VenueProfileRow, plan.profiles, ("id",)),
        (InstrumentRow, plan.instruments, ("symbol",)),
        (VenueRow, plan.venues, ("id",)),
        (CostProfileRow, plan.costs, ("id",)),
        (SessionWindowRow, plan.windows, ("id",)),
        (TradingCalendarRow, plan.calendars, ("id",)),
        (TradingDayRuleRow, plan.rules, ("id",)),
    ):
        retired[model.__tablename__] = await _retire_missing(
            session, table_of(model), rows, key, off
        )

    snapshot = await _record_snapshot(session, document, fingerprint, applied_by)
    _log.info(
        "catalog.applied",
        fingerprint=fingerprint,
        snapshot_created=snapshot.created,
        removed=removed,
        retired={table: {"deleted": d, "disabled": x} for table, (d, x) in retired.items()},
    )
    return snapshot


async def _record_snapshot(
    session: AsyncSession, document: Mapping[str, Any], fingerprint: str, applied_by: str
) -> CatalogSnapshot:
    snapshots = table_of(CatalogSnapshotRow)
    inserted = (
        await session.execute(
            pg_insert(snapshots)
            .values(
                id=uuid7(),
                fingerprint=fingerprint,
                document=json_safe(dict(document)),
                applied_by=applied_by,
                last_applied_at=func.clock_timestamp(),
            )
            .on_conflict_do_nothing(index_elements=["fingerprint"])
            .returning(snapshots.c.id)
        )
    ).scalar_one_or_none()
    if inserted is not None:
        return CatalogSnapshot(id=inserted, fingerprint=fingerprint, created=True)
    existing = (
        await session.execute(
            update(snapshots)
            .where(snapshots.c.fingerprint == fingerprint)
            .values(last_applied_at=func.clock_timestamp())
            .returning(snapshots.c.id)
        )
    ).scalar_one()
    return CatalogSnapshot(id=existing, fingerprint=fingerprint, created=False)


async def latest_catalog_snapshot(session: AsyncSession) -> StoredCatalogSnapshot | None:
    """The catalog most recently applied (re-applying an older one makes it current again)."""
    row = (
        await session.execute(
            select(table_of(CatalogSnapshotRow))
            .order_by(
                CatalogSnapshotRow.last_applied_at.desc(), CatalogSnapshotRow.applied_at.desc()
            )
            .limit(1)
        )
    ).one_or_none()
    if row is None:
        return None
    return StoredCatalogSnapshot(
        id=row.id,
        fingerprint=row.fingerprint,
        document=row.document,
        applied_at=row.applied_at,
        applied_by=row.applied_by,
        last_applied_at=row.last_applied_at,
    )
