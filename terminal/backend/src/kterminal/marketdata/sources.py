"""The data source map: which provider serves each canonical instrument's 1m bars.

``terminal/config/catalog/data_sources.yaml``::

    data_sources:
      BTCUSD:
        provider: binance_usdm      # one of PROVIDERS
        symbol: BTCUSDT             # the provider's own symbol
        volume: exchange            # exchange | tick | none — what Bar.volume means
        note: Same feed as BINANCE:BTCUSDT.P on TradingView.
        alternatives:               # optional, tried in order when the provider above is
          - provider: coinbase      # disabled (geo-blocked) or not configured
            symbol: BTC-USD
            volume: exchange

The map is strict, like the catalog: unknown keys, duplicate keys, unknown instruments
or providers, a volume kind the provider cannot deliver, a symbol that does not look
like the provider's symbols, or a symbol that differs from the catalog listing of the
same venue are all reported at once in a :class:`DataSourceError`.
"""

import difflib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml

from kterminal.domain.catalog import InstrumentCatalog


class VolumeKind(StrEnum):
    """What ``Bar.volume`` means for a source."""

    EXCHANGE = "exchange"  # traded quantity reported by the venue
    TICK = "tick"  # number of price updates in the minute (OANDA), not a traded quantity
    NONE = "none"  # no volume; bars carry 0


@dataclass(frozen=True, slots=True)
class ProviderInfo:
    """Static facts about a provider: its venue id in the catalog and what it can deliver."""

    name: str
    venue: str | None  # catalog venue whose listings hold the same symbols (None: no venue)
    volume: frozenset[VolumeKind]
    symbol_pattern: re.Pattern[str]
    symbol_example: str
    description: str


PROVIDERS: Mapping[str, ProviderInfo] = {
    info.name: info
    for info in (
        ProviderInfo(
            "binance_usdm",
            "binance_usdm",
            frozenset({VolumeKind.EXCHANGE}),
            re.compile(r"^[A-Z0-9]+(_[0-9]{6})?$"),
            "BTCUSDT",
            "Binance USD-M futures REST API (/fapi/v1/klines)",
        ),
        ProviderInfo(
            "binance_spot",
            "binance_spot",
            frozenset({VolumeKind.EXCHANGE}),
            re.compile(r"^[A-Z0-9]+$"),
            "PUMPUSDT",
            "Binance spot REST API (/api/v3/klines)",
        ),
        ProviderInfo(
            "bybit_linear",
            "bybit_linear",
            frozenset({VolumeKind.EXCHANGE}),
            re.compile(r"^[A-Z0-9]+$"),
            "SOLUSDT",
            "Bybit v5 REST API, linear perpetuals (/v5/market/kline)",
        ),
        ProviderInfo(
            "coinbase",
            "coinbase",
            frozenset({VolumeKind.EXCHANGE}),
            re.compile(r"^[A-Z0-9]+-[A-Z0-9]+$"),
            "ZEC-USD",
            "Coinbase Exchange REST API (/products/{id}/candles)",
        ),
        ProviderInfo(
            "hyperliquid",
            "hyperliquid",
            frozenset({VolumeKind.EXCHANGE}),
            re.compile(r"^([a-z0-9]+:)?[A-Za-z0-9]+$"),
            "HYPE",
            "Hyperliquid info API (candleSnapshot)",
        ),
        ProviderInfo(
            "oanda",
            "oanda",
            frozenset({VolumeKind.TICK}),
            re.compile(r"^[A-Z0-9]+_[A-Z0-9]+$"),
            "XAU_USD",
            "OANDA v20 REST API (/v3/instruments/{instrument}/candles), needs a token",
        ),
        ProviderInfo(
            "csv",
            None,
            frozenset(VolumeKind),
            re.compile(r"^\S.*$"),
            "CME_MINI:MNQ1!",
            "Imported 1m files <csv_dir>/<INSTRUMENT>.csv (no download)",
        ),
    )
}

_TOP_KEYS = frozenset({"data_sources"})
_SOURCE_KEYS = frozenset({"provider", "symbol", "volume", "note"})
_ENTRY_KEYS = _SOURCE_KEYS | {"alternatives"}
_REQUIRED_KEYS = ("provider", "symbol", "volume")


class DataSourceError(ValueError):
    """The data source map is invalid. ``problems`` lists every issue found."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        listed = "\n  - ".join(problems)
        super().__init__(f"{len(problems)} data source problem(s):\n  - {listed}")


@dataclass(frozen=True, slots=True)
class DataSource:
    """One way to get an instrument's 1m bars."""

    instrument: str
    provider: str
    symbol: str
    volume: VolumeKind
    note: str = ""


class DataSourceMap:
    """Each instrument's sources in order of preference (primary first, then alternatives)."""

    def __init__(self, chains: Mapping[str, Sequence[DataSource]]) -> None:
        self._chains = {instrument: tuple(chain) for instrument, chain in chains.items()}
        empty = sorted(i for i, chain in self._chains.items() if not chain)
        if empty:
            raise DataSourceError([f"data source {i}: no source" for i in empty])

    # ── loading ─────────────────────────────────────────────────────────────
    @classmethod
    def load(cls, path: str | Path, catalog: InstrumentCatalog) -> "DataSourceMap":
        file = Path(path)
        try:
            text = file.read_text(encoding="utf-8")
        except OSError as exc:
            raise DataSourceError([f"cannot read {file}: {exc.strerror}"]) from None
        try:
            document = yaml.load(text, Loader=_StrictLoader)  # noqa: S506 - SafeLoader subclass
        except yaml.YAMLError as exc:
            raise DataSourceError([f"{file.name}: invalid YAML: {exc}"]) from None
        return cls.from_document(document, catalog)

    @classmethod
    def from_document(cls, document: Any, catalog: InstrumentCatalog) -> "DataSourceMap":
        problems: list[str] = []
        if not isinstance(document, Mapping):
            raise DataSourceError(["expected a mapping with a 'data_sources' key"])
        unknown = sorted(set(map(str, document)) - _TOP_KEYS)
        if unknown:
            problems.append(f"unknown top-level key(s) {', '.join(unknown)}")
        rows = document.get("data_sources")
        if not isinstance(rows, Mapping):
            problems.append("'data_sources' must be a mapping of instrument → source")
            raise DataSourceError(problems)
        chains: dict[str, tuple[DataSource, ...]] = {}
        for instrument, entry in rows.items():
            chain = _parse_entry(instrument, entry, problems)
            if chain:
                chains[str(instrument)] = chain
            elif isinstance(instrument, str) and instrument not in catalog.instruments:
                problems.append(_unknown_instrument(instrument, catalog))
        sources = cls(chains)
        problems.extend(sources.problems(catalog))
        if problems:
            raise DataSourceError(problems)
        return sources

    # ── validation ──────────────────────────────────────────────────────────
    def problems(self, catalog: InstrumentCatalog) -> list[str]:
        """Cross-check against the catalog: instruments exist, symbols match its listings."""
        problems: list[str] = []
        for instrument, chain in self._chains.items():
            if instrument not in catalog.instruments:
                problems.append(_unknown_instrument(instrument, catalog))
                continue
            for source in chain:
                info = PROVIDERS[source.provider]
                if info.venue is None:
                    continue
                listing = catalog.listings.get(f"{info.venue}:{instrument}")
                if listing is not None and listing.venue_symbol != source.symbol:
                    problems.append(
                        f"data source {instrument} ({source.provider}): symbol "
                        f"{source.symbol!r} differs from the catalog listing "
                        f"{listing.key} ({listing.venue_symbol!r})"
                    )
        return problems

    # ── lookups ─────────────────────────────────────────────────────────────
    @property
    def instruments(self) -> tuple[str, ...]:
        return tuple(self._chains)

    def chain(self, instrument: str) -> tuple[DataSource, ...]:
        try:
            return self._chains[instrument]
        except KeyError:
            raise KeyError(f"no data source for {instrument!r}") from None

    def primary(self, instrument: str) -> DataSource:
        return self.chain(instrument)[0]

    def source(self, instrument: str, provider: str) -> DataSource:
        """The source of ``instrument`` served by ``provider`` (primary or alternative)."""
        for source in self.chain(instrument):
            if source.provider == provider:
                return source
        offered = ", ".join(s.provider for s in self.chain(instrument))
        raise KeyError(f"{instrument} has no {provider} source (configured: {offered})")

    def __len__(self) -> int:
        return len(self._chains)


def _unknown_instrument(instrument: str, catalog: InstrumentCatalog) -> str:
    close = difflib.get_close_matches(instrument, catalog.instruments, n=3)
    hint = f" (did you mean {', '.join(close)}?)" if close else ""
    return f"data source {instrument}: unknown instrument{hint}"


def _parse_entry(instrument: Any, entry: Any, problems: list[str]) -> tuple[DataSource, ...]:
    where = f"data source {instrument}"
    if not isinstance(instrument, str):
        problems.append(f"{where}: instrument keys must be strings (quote {instrument!r})")
        return ()
    primary = _parse_source(instrument, entry, _ENTRY_KEYS, where, problems)
    if primary is None:
        return ()
    chain = [primary]
    alternatives = entry.get("alternatives") or []
    if not isinstance(alternatives, list):
        problems.append(f"{where}: 'alternatives' must be a list")
        return ()
    for index, alternative in enumerate(alternatives, start=1):
        source = _parse_source(
            instrument, alternative, _SOURCE_KEYS, f"{where} alternative {index}", problems
        )
        if source is not None:
            chain.append(source)
    seen: set[str] = set()
    for source in chain:
        if source.provider in seen:
            problems.append(f"{where}: provider {source.provider} listed more than once")
        seen.add(source.provider)
    return tuple(chain)


def _parse_source(
    instrument: str, row: Any, allowed: frozenset[str], where: str, problems: list[str]
) -> DataSource | None:
    if not isinstance(row, Mapping):
        problems.append(f"{where}: expected a mapping, got {type(row).__name__}")
        return None
    unknown = sorted(set(map(str, row)) - allowed)
    if unknown:
        problems.append(f"{where}: unknown key(s) {', '.join(unknown)}")
        return None
    missing = [key for key in _REQUIRED_KEYS if key not in row]
    if missing:
        problems.append(f"{where}: missing {', '.join(missing)}")
        return None
    values: dict[str, str] = {}
    for key in (*_REQUIRED_KEYS, "note"):
        value = row.get(key, "")
        if not isinstance(value, str):
            problems.append(f"{where}: {key} must be a string, got {value!r} (quote it)")
            return None
        values[key] = value.strip()
    info = PROVIDERS.get(values["provider"])
    if info is None:
        problems.append(
            f"{where}: unknown provider {values['provider']!r} "
            f"(known: {', '.join(sorted(PROVIDERS))})"
        )
        return None
    try:
        volume = VolumeKind(values["volume"])
    except ValueError:
        problems.append(
            f"{where}: volume must be one of {', '.join(v.value for v in VolumeKind)}, "
            f"got {values['volume']!r}"
        )
        return None
    ok = True
    if volume not in info.volume:
        allowed_kinds = ", ".join(sorted(v.value for v in info.volume))
        problems.append(f"{where}: {info.name} delivers {allowed_kinds} volume, not {volume}")
        ok = False
    if not info.symbol_pattern.fullmatch(values["symbol"]):
        problems.append(
            f"{where}: {values['symbol']!r} is not a {info.name} symbol "
            f"(like {info.symbol_example!r})"
        )
        ok = False
    if not ok:
        return None
    return DataSource(
        instrument=instrument,
        provider=info.name,
        symbol=values["symbol"],
        volume=volume,
        note=values["note"],
    )


class _StrictLoader(yaml.SafeLoader):
    """YAML ``SafeLoader`` that refuses duplicate mapping keys (PyYAML keeps the last one,
    which would silently switch an instrument's source)."""


def _construct_mapping(loader: _StrictLoader, node: yaml.MappingNode) -> dict[Any, Any]:
    seen: set[Any] = set()
    for key_node, _value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        if key in seen:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        seen.add(key)
    return loader.construct_mapping(node, deep=True)


_StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


__all__ = [
    "PROVIDERS",
    "DataSource",
    "DataSourceError",
    "DataSourceMap",
    "ProviderInfo",
    "VolumeKind",
]
