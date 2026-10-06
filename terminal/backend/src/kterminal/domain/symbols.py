"""Symbol mapping between canonical instruments and every outside spelling.

``SymbolResolver.resolve("BINANCE:NEARUSDT.P", source="tradingview")`` →
``NEARUSD``; ``resolve("US100")`` → ``NAS100``; ``resolve("XAUUSD.r",
source="generic_mt5_cfd")`` → ``XAUUSD``. Resolution order (first hit wins):

1. aliases declared for that source (e.g. ``tradingview: CME_MINI:MNQ1!``);
2. that source's venue symbols and per-listing aliases, after stripping the
   venue's configured broker suffixes (``.r``, ``m`` …);
3. global aliases (``GOLD``, ``US100``, ``NEAR``) and canonical symbols;
4. with no source: every source's aliases and venue symbols, if they all agree.

Each step is tried for the full text, then without an ``EXCHANGE:`` prefix,
then without TradingView's ``.P`` perpetual suffix.
"""

import difflib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from kterminal.domain.instruments import Listing, Venue

GLOBAL_SOURCE = "*"


class UnknownSymbolError(LookupError):
    pass


class AmbiguousSymbolError(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class SymbolAlias:
    source: str  # a venue id, "tradingview", or "*" for global aliases
    alias: str
    instrument: str

    def key(self) -> tuple[str, str]:
        return (self.source.lower(), self.alias.strip().upper())


def _variants(text: str) -> list[str]:
    upper = text.strip().upper()
    variants = [upper]
    if ":" in upper:
        variants.append(upper.split(":", 1)[1])
    for value in list(variants):
        if value.endswith(".P"):
            variants.append(value[:-2])
    return list(dict.fromkeys(v for v in variants if v))


class SymbolResolver:
    def __init__(
        self,
        instruments: Iterable[str],
        venues: Mapping[str, Venue],
        listings: Iterable[Listing],
        aliases: Iterable[SymbolAlias],
    ) -> None:
        self._canonical = {s.upper(): s for s in instruments}
        self._venues = dict(venues)
        self._aliases: dict[str, dict[str, str]] = {}
        for alias in aliases:
            source, key = alias.key()
            self._aliases.setdefault(source, {})[key] = alias.instrument
        self._venue_symbols: dict[str, dict[str, set[str]]] = {}
        for listing in listings:
            table = self._venue_symbols.setdefault(listing.venue, {})
            for name in (listing.venue_symbol, *listing.aliases):
                table.setdefault(name.strip().upper(), set()).add(listing.instrument)

    # ── resolution ──────────────────────────────────────────────────────────
    def resolve(self, raw: str, source: str | None = None) -> str:
        if not raw or not raw.strip():
            raise UnknownSymbolError("empty symbol")
        source_key = source.lower() if source else None
        for candidate in _variants(raw):
            if source_key is not None:
                hit = self._aliases.get(source_key, {}).get(candidate)
                if hit:
                    return hit
                hit = self._from_venue(source_key, candidate)
                if hit:
                    return hit
            hit = self._aliases.get(GLOBAL_SOURCE, {}).get(candidate)
            if hit:
                return hit
            if candidate in self._canonical:
                return self._canonical[candidate]
        if source_key is None:
            for candidate in _variants(raw):
                found = {
                    instrument
                    for venue in self._venue_symbols
                    for instrument in self._lookup_venue(venue, candidate)
                }
                found.update(
                    table[candidate]
                    for alias_source, table in self._aliases.items()
                    if alias_source != GLOBAL_SOURCE and candidate in table
                )
                if len(found) == 1:
                    return found.pop()
                if len(found) > 1:
                    raise AmbiguousSymbolError(
                        f"{raw!r} is used by several venues for different instruments: "
                        f"{', '.join(sorted(found))} — specify the source"
                    )
        raise UnknownSymbolError(self._unknown_message(raw, source))

    def _from_venue(self, venue: str, candidate: str) -> str | None:
        found = self._lookup_venue(venue, candidate)
        if len(found) > 1:
            raise AmbiguousSymbolError(
                f"{candidate!r} maps to several instruments at {venue}: {', '.join(sorted(found))}"
            )
        return next(iter(found), None)

    def _lookup_venue(self, venue: str, candidate: str) -> set[str]:
        table = self._venue_symbols.get(venue, {})
        if candidate in table:
            return set(table[candidate])
        venue_info = self._venues.get(venue)
        for suffix in venue_info.symbol_suffixes if venue_info else ():
            suffix_upper = suffix.upper()
            if suffix_upper and candidate.endswith(suffix_upper):
                stripped = candidate[: -len(suffix_upper)]
                if stripped in table:
                    return set(table[stripped])
        return set()

    def _unknown_message(self, raw: str, source: str | None) -> str:
        names = set(self._canonical)
        for table in self._aliases.values():
            names.update(table)
        for venue_table in self._venue_symbols.values():
            names.update(venue_table)
        suggestions = difflib.get_close_matches(raw.strip().upper(), sorted(names), n=4)
        hint = f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""
        where = f" for source {source!r}" if source else ""
        return f"unknown symbol {raw!r}{where}.{hint}"


def find_alias_conflicts(aliases: Iterable[SymbolAlias], canonical: Iterable[str]) -> list[str]:
    """Aliases that point to two instruments within one source, or shadow another
    instrument's canonical symbol."""
    problems: list[str] = []
    seen: dict[tuple[str, str], str] = {}
    canonical_upper = {c.upper(): c for c in canonical}
    for alias in aliases:
        key = alias.key()
        previous = seen.get(key)
        if previous is not None and previous != alias.instrument:
            problems.append(
                f"alias {alias.alias!r} (source {alias.source}) maps to both {previous} "
                f"and {alias.instrument}"
            )
        seen[key] = alias.instrument
        shadowed = canonical_upper.get(key[1])
        if shadowed is not None and shadowed != alias.instrument:
            problems.append(
                f"alias {alias.alias!r} → {alias.instrument} shadows canonical symbol {shadowed}"
            )
    return problems
