"""The instrument catalog: every venue, instrument, listing, alias, calendar,
session window, cost profile and venue profile, loaded from configuration.

``InstrumentCatalog.load(directory)`` reads ``terminal/config/catalog``::

    venues.yaml          venues: [...]
    instruments.yaml     instruments: [...]   (each may list global ``aliases``)
                         aliases: [{source, alias, instrument}]
    listings/*.yaml      listings: [...]      (a file may set ``venue:`` for all its rows)
    sessions.yaml        trading_day_rules / calendars / session_windows / session_classification
    costs.yaml           cost_profiles: [...]
    venue_profiles.yaml  venue_profiles: [...]

Everything is normalised into one *catalog document* (plain JSON-safe data)
that is validated as a whole — every cross-reference must resolve — and
hashed into a fingerprint. The document is what ``kterminal catalog apply``
writes to PostgreSQL, and the fingerprint is recorded with every decision so
the exact specification a trade was sized and costed with is never lost.
"""

from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from functools import cached_property
from pathlib import Path
from typing import Any

import yaml

from kterminal.core.canonical import hash_data
from kterminal.domain.costs import (
    CostCalculator,
    CostProfile,
    parse_cost_profiles,
    profile_listing_problems,
)
from kterminal.domain.instruments import (
    AssetClass,
    ContractType,
    FuturesSpec,
    Instrument,
    Listing,
    Platform,
    PnlModel,
    QuantityUnit,
    Venue,
    VenueKind,
)
from kterminal.domain.sessions import SessionBook, TradingCalendar
from kterminal.domain.symbols import (
    GLOBAL_SOURCE,
    SymbolAlias,
    SymbolResolver,
    find_alias_conflicts,
)

SESSION_KEYS = ("trading_day_rules", "calendars", "session_windows", "session_classification")
DOCUMENT_KEYS = (
    "venues",
    "instruments",
    "aliases",
    "listings",
    *SESSION_KEYS,
    "cost_profiles",
    "venue_profiles",
)


class CatalogError(ValueError):
    """The catalog configuration is invalid. ``problems`` lists every issue found."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        listed = "\n  - ".join(problems)
        super().__init__(f"{len(problems)} catalog problem(s):\n  - {listed}")


@dataclass(frozen=True, slots=True)
class VenueProfile:
    """Which listing an account simulates for each instrument (and where bars come from)."""

    id: str
    description: str
    execution: Mapping[str, str]  # instrument → "venue:INSTRUMENT"
    data: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "execution": dict(sorted(self.execution.items())),
            "data": dict(sorted(self.data.items())),
        }


# ── parsing helpers ──────────────────────────────────────────────────────────
def _dec(value: Any, where: str, problems: list[str]) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        problems.append(f"{where}: {value!r} is not a number")
        return Decimal(0)
    if not result.is_finite():
        problems.append(f"{where}: {value!r} is not finite")
    return result


_VENUE_KEYS = frozenset(
    {"id", "name", "kind", "platform", "timezone", "symbol_suffixes", "description"}
)
_INSTRUMENT_KEYS = frozenset(
    {
        "symbol",
        "name",
        "asset_class",
        "base",
        "quote_currency",
        "tick_size",
        "trading_hours",
        "trading_day",
        "underlying",
        "futures",
        "description",
        "tags",
    }
)
_LISTING_KEYS = frozenset(
    {
        "venue",
        "instrument",
        "venue_symbol",
        "contract_type",
        "tick_size",
        "contract_size",
        "quantity_unit",
        "min_qty",
        "qty_step",
        "quote_currency",
        "max_qty",
        "min_notional",
        "pnl_model",
        "trading_hours",
        "cost_profile",
        "symbol_format",
        "tradable",
        "verified_on",
        "source",
        "notes",
        "aliases",
    }
)
_ALIAS_KEYS = frozenset({"source", "alias", "instrument"})
_VENUE_PROFILE_KEYS = frozenset({"id", "description", "execution", "data"})


def _check_keys(d: Any, allowed: frozenset[str], where: str, problems: list[str]) -> bool:
    """Rows are strict: a misspelled key (``pnl_modle``) must not be silently ignored."""
    if not isinstance(d, Mapping):
        problems.append(f"{where}: expected a mapping, got {type(d).__name__}")
        return False
    unknown = sorted(set(d) - allowed)
    if unknown:
        problems.append(f"{where}: unknown key(s) {', '.join(map(str, unknown))}")
        return False
    return True


def _strict_bool(value: Any, where: str, problems: list[str]) -> bool:
    if not isinstance(value, bool):
        problems.append(f"{where}: expected true or false, got {value!r}")
        return False
    return value


def _opt_dec(value: Any, where: str, problems: list[str]) -> Decimal | None:
    return None if value in (None, "") else _dec(value, where, problems)


def _str_decimal(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def instrument_from_dict(d: Mapping[str, Any], problems: list[str]) -> Instrument | None:
    where = f"instrument {d.get('symbol', '?') if isinstance(d, Mapping) else '?'}"
    if not _check_keys(d, _INSTRUMENT_KEYS, where, problems):
        return None
    try:
        futures = d.get("futures")
        return Instrument(
            symbol=str(d["symbol"]),
            name=str(d["name"]),
            asset_class=AssetClass(d["asset_class"]),
            base=str(d["base"]),
            quote_currency=str(d["quote_currency"]),
            tick_size=_dec(d["tick_size"], f"{where}.tick_size", problems),
            trading_hours=str(d["trading_hours"]),
            trading_day=str(d["trading_day"]),
            underlying=str(d.get("underlying") or ""),
            futures=FuturesSpec(**futures) if futures else None,
            description=str(d.get("description") or ""),
            tags=tuple(d.get("tags") or ()),
        )
    except (KeyError, TypeError, ValueError) as exc:
        problems.append(f"{where}: {exc}")
        return None


def instrument_to_dict(i: Instrument) -> dict[str, Any]:
    return {
        "symbol": i.symbol,
        "name": i.name,
        "asset_class": i.asset_class.value,
        "base": i.base,
        "quote_currency": i.quote_currency,
        "tick_size": str(i.tick_size),
        "trading_hours": i.trading_hours,
        "trading_day": i.trading_day,
        "underlying": i.underlying,
        "futures": None
        if i.futures is None
        else {
            "root": i.futures.root,
            "contract_months": i.futures.contract_months,
            "expiry_rule": i.futures.expiry_rule,
            "roll_days_before_expiry": i.futures.roll_days_before_expiry,
        },
        "description": i.description,
        "tags": list(i.tags),
    }


def venue_from_dict(d: Mapping[str, Any], problems: list[str]) -> Venue | None:
    where = f"venue {d.get('id', '?') if isinstance(d, Mapping) else '?'}"
    if not _check_keys(d, _VENUE_KEYS, where, problems):
        return None
    try:
        return Venue(
            id=str(d["id"]),
            name=str(d["name"]),
            kind=VenueKind(d["kind"]),
            platform=Platform(d["platform"]) if d.get("platform") else None,
            timezone=str(d.get("timezone") or "UTC"),
            symbol_suffixes=tuple(d.get("symbol_suffixes") or ()),
            description=str(d.get("description") or ""),
        )
    except (KeyError, TypeError, ValueError) as exc:
        problems.append(f"venue {d.get('id', '?')}: {exc}")
        return None


def venue_to_dict(v: Venue) -> dict[str, Any]:
    return {
        "id": v.id,
        "name": v.name,
        "kind": v.kind.value,
        "platform": v.platform.value if v.platform else None,
        "timezone": v.timezone,
        "symbol_suffixes": list(v.symbol_suffixes),
        "description": v.description,
    }


def listing_from_dict(d: Any, problems: list[str]) -> Listing | None:
    if not isinstance(d, Mapping):
        problems.append(f"listing: expected a mapping, got {type(d).__name__}")
        return None
    where = f"listing {d.get('venue', '?')}:{d.get('instrument', '?')}"
    if not _check_keys(d, _LISTING_KEYS, where, problems):
        return None
    tradable = _strict_bool(d.get("tradable", True), f"{where}.tradable", problems)
    try:
        verified = d.get("verified_on")
        return Listing(
            venue=str(d["venue"]),
            instrument=str(d["instrument"]),
            venue_symbol=str(d["venue_symbol"]),
            contract_type=ContractType(d["contract_type"]),
            tick_size=_dec(d["tick_size"], f"{where}.tick_size", problems),
            contract_size=_dec(d["contract_size"], f"{where}.contract_size", problems),
            quantity_unit=QuantityUnit(d["quantity_unit"]),
            min_qty=_dec(d["min_qty"], f"{where}.min_qty", problems),
            qty_step=_dec(d["qty_step"], f"{where}.qty_step", problems),
            quote_currency=str(d["quote_currency"]),
            max_qty=_opt_dec(d.get("max_qty"), f"{where}.max_qty", problems),
            min_notional=_opt_dec(d.get("min_notional"), f"{where}.min_notional", problems),
            pnl_model=PnlModel(d.get("pnl_model") or "LINEAR"),
            trading_hours=d.get("trading_hours") or None,
            cost_profile=d.get("cost_profile") or None,
            symbol_format=d.get("symbol_format") or None,
            tradable=tradable,
            verified_on=date.fromisoformat(str(verified)) if verified else None,
            source=str(d.get("source") or ""),
            notes=str(d.get("notes") or ""),
            aliases=tuple(str(a) for a in d.get("aliases") or ()),
        )
    except (KeyError, TypeError, ValueError) as exc:
        problems.append(f"{where}: {exc}")
        return None


def listing_to_dict(item: Listing) -> dict[str, Any]:
    return {
        "venue": item.venue,
        "instrument": item.instrument,
        "venue_symbol": item.venue_symbol,
        "contract_type": item.contract_type.value,
        "tick_size": str(item.tick_size),
        "contract_size": str(item.contract_size),
        "quantity_unit": item.quantity_unit.value,
        "min_qty": str(item.min_qty),
        "qty_step": str(item.qty_step),
        "quote_currency": item.quote_currency,
        "max_qty": _str_decimal(item.max_qty),
        "min_notional": _str_decimal(item.min_notional),
        "pnl_model": item.pnl_model.value,
        "trading_hours": item.trading_hours,
        "cost_profile": item.cost_profile,
        "symbol_format": item.symbol_format,
        "tradable": item.tradable,
        "verified_on": item.verified_on.isoformat() if item.verified_on else None,
        "source": item.source,
        "notes": item.notes,
        "aliases": list(item.aliases),
    }


def _duplicates(kind: str, keys: list[str]) -> list[str]:
    counts = Counter(keys)
    return [f"duplicate {kind} {key} ({n} rows)" for key, n in sorted(counts.items()) if n > 1]


# ── the catalog ──────────────────────────────────────────────────────────────
class InstrumentCatalog:
    def __init__(
        self,
        *,
        venues: Iterable[Venue],
        instruments: Iterable[Instrument],
        listings: Iterable[Listing],
        aliases: Iterable[SymbolAlias],
        sessions: SessionBook,
        cost_profiles: Mapping[str, CostProfile],
        venue_profiles: Iterable[VenueProfile],
    ) -> None:
        venues, instruments = list(venues), list(instruments)
        listings, venue_profiles = list(listings), list(venue_profiles)
        # A second row with the same key must never silently replace the first.
        problems = [
            *_duplicates("venue", [v.id for v in venues]),
            *_duplicates("instrument", [i.symbol for i in instruments]),
            *_duplicates("listing", [item.key for item in listings]),
            *_duplicates("venue profile", [p.id for p in venue_profiles]),
        ]
        self.venues = {v.id: v for v in venues}
        self.instruments = {i.symbol: i for i in instruments}
        self.listings = {item.key: item for item in listings}
        self.aliases = tuple(aliases)
        self.sessions = sessions
        self.cost_profiles = dict(cost_profiles)
        self.venue_profiles = {p.id: p for p in venue_profiles}
        problems.extend(self.validate())
        if problems:
            raise CatalogError(problems)

    # ── loading ─────────────────────────────────────────────────────────────
    @classmethod
    def load(cls, directory: str | Path) -> "InstrumentCatalog":
        return cls.from_document(read_catalog_document(directory))

    @classmethod
    def from_document(cls, document: Mapping[str, Any]) -> "InstrumentCatalog":
        problems: list[str] = []
        unknown = set(document) - set(DOCUMENT_KEYS)
        if unknown:
            problems.append(f"unknown top-level keys: {', '.join(sorted(unknown))}")
        venues = [v for d in document.get("venues") or [] if (v := venue_from_dict(d, problems))]
        instruments = [
            i for d in document.get("instruments") or [] if (i := instrument_from_dict(d, problems))
        ]
        listings = [
            item for d in document.get("listings") or [] if (item := listing_from_dict(d, problems))
        ]
        aliases = []
        for d in document.get("aliases") or []:
            if not _check_keys(d, _ALIAS_KEYS, f"alias {d!r}", problems):
                continue
            try:
                aliases.append(SymbolAlias(str(d["source"]), str(d["alias"]), str(d["instrument"])))
            except (KeyError, TypeError) as exc:
                problems.append(f"alias {d!r}: missing {exc}")
        try:
            sessions = SessionBook.from_document({k: document.get(k) or [] for k in SESSION_KEYS})
        except (KeyError, TypeError, ValueError) as exc:
            problems.append(f"sessions: {exc}")
            sessions = SessionBook.from_document({k: [] for k in SESSION_KEYS})
        try:
            cost_profiles = parse_cost_profiles(
                {"cost_profiles": document.get("cost_profiles") or []}
            )
        except (KeyError, TypeError, ValueError) as exc:
            problems.append(f"cost profiles: {exc}")
            cost_profiles = {}
        profiles = []
        for d in document.get("venue_profiles") or []:
            where = f"venue profile {d.get('id', '?') if isinstance(d, Mapping) else d!r}"
            if not _check_keys(d, _VENUE_PROFILE_KEYS, where, problems):
                continue
            try:
                profiles.append(
                    VenueProfile(
                        id=str(d["id"]),
                        description=str(d.get("description") or ""),
                        execution={str(k): str(v) for k, v in (d.get("execution") or {}).items()},
                        data={str(k): str(v) for k, v in (d.get("data") or {}).items()},
                    )
                )
            except (KeyError, TypeError) as exc:
                problems.append(f"venue profile {d!r}: {exc}")
        if problems:
            raise CatalogError(problems)
        return cls(
            venues=venues,
            instruments=instruments,
            listings=listings,
            aliases=aliases,
            sessions=sessions,
            cost_profiles=cost_profiles,
            venue_profiles=profiles,
        )

    # ── validation ──────────────────────────────────────────────────────────
    def validate(self) -> list[str]:
        problems: list[str] = []
        calendars = {c.id for c in self.sessions.calendars}
        day_rules = {r.id for r in self.sessions.trading_day_rules}
        windows = {w.id for w in self.sessions.windows}
        for inst in self.instruments.values():
            if inst.trading_hours not in calendars:
                problems.append(
                    f"instrument {inst.symbol}: unknown calendar {inst.trading_hours!r}"
                )
            if inst.trading_day not in day_rules:
                problems.append(
                    f"instrument {inst.symbol}: unknown trading-day rule {inst.trading_day!r}"
                )
        seen_symbols: dict[tuple[str, str], str] = {}
        for item in self.listings.values():
            where = f"listing {item.key}"
            if item.venue not in self.venues:
                problems.append(f"{where}: unknown venue {item.venue!r}")
            listed = self.instruments.get(item.instrument)
            if listed is None:
                problems.append(f"{where}: unknown instrument {item.instrument!r}")
            if item.trading_hours and item.trading_hours not in calendars:
                problems.append(f"{where}: unknown calendar {item.trading_hours!r}")
            profile = self.cost_profiles.get(item.cost_profile) if item.cost_profile else None
            if item.cost_profile and profile is None:
                problems.append(f"{where}: unknown cost profile {item.cost_profile!r}")
            if profile is not None:
                problems.extend(
                    f"{where}: {reason}" for reason in profile_listing_problems(profile, item)
                )
            if item.tradable and item.pnl_model is not PnlModel.LINEAR:
                problems.append(
                    f"{where}: {item.pnl_model} P&L is not supported yet "
                    "(keep the listing tradable: false)"
                )
            if item.tradable and not item.cost_profile:
                problems.append(
                    f"{where}: tradable listings need a cost_profile (costs are "
                    "never silently zero; use 'zero_cost' explicitly)"
                )
            if item.symbol_format and (listed is None or listed.futures is None):
                problems.append(f"{where}: symbol_format requires a futures instrument")
            elif item.symbol_format and listed is not None:
                try:  # render it once: an unknown token must fail here, not on first use
                    item.venue_symbol_for(listed, date(2026, 1, 15))
                except (KeyError, IndexError, ValueError) as exc:
                    problems.append(
                        f"{where}: invalid symbol_format {item.symbol_format!r}: "
                        f"{type(exc).__name__}: {exc}"
                    )
            symbol_key = (item.venue, item.venue_symbol.upper())
            other = seen_symbols.get(symbol_key)
            if other is not None and other != item.instrument:
                problems.append(
                    f"{where}: venue symbol {item.venue_symbol!r} already used by {other}"
                )
            seen_symbols[symbol_key] = item.instrument
        for alias in self.aliases:
            if alias.instrument not in self.instruments:
                problems.append(f"alias {alias.alias!r}: unknown instrument {alias.instrument!r}")
            if alias.source != GLOBAL_SOURCE and alias.source not in self.venues:
                problems.append(f"alias {alias.alias!r}: unknown source {alias.source!r}")
        problems.extend(find_alias_conflicts(self.aliases, self.instruments))
        for profile in self.cost_profiles.values():
            for window_id in getattr(profile.spread, "window_ids", frozenset()):
                if window_id not in windows:
                    problems.append(f"cost profile {profile.id}: unknown window {window_id!r}")
        for vp in self.venue_profiles.values():
            for symbol in sorted(set(vp.data) - set(vp.execution)):
                problems.append(
                    f"venue profile {vp.id}: data listing for {symbol} without an execution "
                    "listing (data only selects where an executed instrument's bars come from)"
                )
            for kind, mapping in (("execution", vp.execution), ("data", vp.data)):
                for symbol, key in mapping.items():
                    if symbol not in self.instruments:
                        problems.append(f"venue profile {vp.id}: unknown instrument {symbol!r}")
                    target = self.listings.get(key)
                    if target is None:
                        problems.append(f"venue profile {vp.id}: unknown listing {key!r}")
                    elif target.instrument != symbol:
                        problems.append(
                            f"venue profile {vp.id}: {symbol} mapped to a listing of "
                            f"{target.instrument}"
                        )
                    elif kind == "execution" and not target.tradable:
                        problems.append(
                            f"venue profile {vp.id}: {key} is data-only and cannot be executed"
                        )
        return problems

    # ── lookups ─────────────────────────────────────────────────────────────
    def instrument(self, symbol: str) -> Instrument:
        try:
            return self.instruments[symbol]
        except KeyError:
            raise KeyError(f"unknown instrument {symbol!r}") from None

    def listing(self, venue: str, instrument: str) -> Listing:
        try:
            return self.listings[f"{venue}:{instrument}"]
        except KeyError:
            raise KeyError(f"no listing of {instrument} at {venue}") from None

    def listings_for(self, instrument: str) -> list[Listing]:
        return [item for item in self.listings.values() if item.instrument == instrument]

    def venue_profile(self, profile_id: str) -> VenueProfile:
        try:
            return self.venue_profiles[profile_id]
        except KeyError:
            raise KeyError(
                f"unknown venue profile {profile_id!r} "
                f"(available: {', '.join(sorted(self.venue_profiles))})"
            ) from None

    def execution_listing(self, profile_id: str, instrument: str) -> Listing:
        profile = self.venue_profile(profile_id)
        key = profile.execution.get(instrument)
        if key is None:
            raise KeyError(f"venue profile {profile_id} does not trade {instrument}")
        return self.listings[key]

    def calendar_for(self, listing: Listing) -> TradingCalendar:
        calendar_id = listing.trading_hours or self.instrument(listing.instrument).trading_hours
        return self.sessions.calendar(calendar_id)

    def cost_calculator(self, listing: Listing) -> CostCalculator:
        if listing.cost_profile is None:
            raise KeyError(f"{listing.key} has no cost profile")
        return CostCalculator(
            self.cost_profiles[listing.cost_profile], listing, window_lookup=self.sessions.labels
        )

    @cached_property
    def resolver(self) -> SymbolResolver:
        return SymbolResolver(self.instruments, self.venues, self.listings.values(), self.aliases)

    def resolve_symbol(self, raw: str, source: str | None = None) -> Instrument:
        return self.instruments[self.resolver.resolve(raw, source)]

    def venue_symbol(self, instrument: str, venue: str, on: date) -> str:
        return self.listing(venue, instrument).venue_symbol_for(self.instrument(instrument), on)

    def window_lookup(self) -> Callable[[datetime], frozenset[str]]:
        return self.sessions.labels

    # ── document & fingerprint ──────────────────────────────────────────────
    def to_document(self) -> dict[str, Any]:
        sessions = self.sessions.to_document()
        return {
            "venues": [venue_to_dict(v) for _, v in sorted(self.venues.items())],
            "instruments": [instrument_to_dict(i) for _, i in sorted(self.instruments.items())],
            "aliases": [
                {"source": a.source, "alias": a.alias, "instrument": a.instrument}
                for a in sorted(self.aliases, key=lambda a: (a.source, a.alias.upper()))
            ],
            "listings": [listing_to_dict(item) for _, item in sorted(self.listings.items())],
            **{key: sessions.get(key, []) for key in SESSION_KEYS},
            "cost_profiles": [p.to_dict() for _, p in sorted(self.cost_profiles.items())],
            "venue_profiles": [p.to_dict() for _, p in sorted(self.venue_profiles.items())],
        }

    @cached_property
    def fingerprint(self) -> str:
        return hash_data(self.to_document())


def read_catalog_document(directory: str | Path) -> dict[str, Any]:
    """Read the YAML files of a catalog directory into one normalised document."""
    root = Path(directory)
    if not root.is_dir():
        raise CatalogError([f"catalog directory {root} does not exist"])
    document: dict[str, Any] = {key: [] for key in DOCUMENT_KEYS}
    document["session_classification"] = []
    problems: list[str] = []

    def load(path: Path) -> dict[str, Any]:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            problems.append(f"{path.name}: invalid YAML: {exc}")
            return {}
        if not isinstance(data, dict):
            problems.append(f"{path.name}: expected a mapping at the top level")
            return {}
        return data

    files = sorted(root.glob("*.yaml")) + sorted((root / "listings").glob("*.yaml"))
    for path in files:
        data = load(path)
        default_venue = data.pop("venue", None)
        for key, value in data.items():
            if key not in DOCUMENT_KEYS:
                problems.append(f"{path.name}: unknown key {key!r}")
                continue
            if key == "session_classification":
                document[key] = list(value or [])
                continue
            rows = list(value or [])
            if key == "listings" and default_venue:
                rows = [{"venue": default_venue, **row} for row in rows]
            if key == "instruments":
                for row in rows:
                    for alias in row.pop("aliases", None) or []:
                        document["aliases"].append(
                            {
                                "source": GLOBAL_SOURCE,
                                "alias": str(alias),
                                "instrument": row.get("symbol"),
                            }
                        )
            document[key].extend(rows)
    if problems:
        raise CatalogError(problems)
    return document
