"""Building the configured providers from the settings and the data source map.

For each instrument the map lists sources in order of preference. The first one whose
provider is usable on this host is chosen; a provider is unusable when it is disabled
(``KT_MARKETDATA__DISABLED_PROVIDERS``, e.g. a venue that geo-blocks this host) or not
configured (OANDA without a token, ``csv`` without ``KT_MARKETDATA__CSV_DIR``).
Instruments with no usable source are skipped with the reasons, never silently.

One provider object — and so one HTTP client and one request budget — serves every
instrument routed to that provider.
"""

import asyncio
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

import httpx

from kterminal.config.settings import MarketDataSettings, Settings
from kterminal.core.clock import Clock
from kterminal.domain.catalog import InstrumentCatalog
from kterminal.marketdata.base import MarketDataProvider
from kterminal.marketdata.providers import (
    HTTP_PROVIDERS,
    CsvProvider,
    OandaProvider,
    ProviderOptions,
)
from kterminal.marketdata.providers._http import Monotonic, Sleep
from kterminal.marketdata.sources import PROVIDERS, DataSource, DataSourceError, DataSourceMap
from kterminal.observability.logging import get_logger

_log = get_logger("kterminal.marketdata")


@dataclass(frozen=True, slots=True)
class SourceChoice:
    """Which source an instrument uses on this host, and why earlier ones were passed over."""

    instrument: str
    chain: tuple[DataSource, ...]
    source: DataSource | None
    passed_over: tuple[str, ...] = ()

    @property
    def is_fallback(self) -> bool:
        return self.source is not None and self.source != self.chain[0]

    @property
    def reason(self) -> str:
        return "; ".join(self.passed_over)


def load_data_sources(settings: Settings, catalog: InstrumentCatalog) -> DataSourceMap:
    """The data source map named by the settings (default <config>/catalog/data_sources.yaml)."""
    return DataSourceMap.load(
        settings.marketdata.sources_file or settings.paths.data_sources, catalog
    )


def settings_problems(settings: MarketDataSettings) -> list[str]:
    problems = [
        f"KT_MARKETDATA__DISABLED_PROVIDERS: unknown provider {name!r} "
        f"(known: {', '.join(sorted(PROVIDERS))})"
        for name in settings.disabled_providers
        if name not in PROVIDERS
    ]
    for name, url in settings.base_urls.items():
        if name not in PROVIDERS or name == "csv":
            problems.append(f"KT_MARKETDATA__BASE_URLS: {name!r} is not an HTTP provider")
        elif not url.startswith("https://"):
            problems.append(f"KT_MARKETDATA__BASE_URLS: {name} must be an https:// URL")
    return problems


def unavailable_reason(provider: str, settings: MarketDataSettings) -> str | None:
    """Why ``provider`` cannot be used on this host, or ``None`` if it can."""
    if provider in settings.disabled_providers:
        return f"{provider} is disabled (KT_MARKETDATA__DISABLED_PROVIDERS)"
    if provider == "oanda" and not settings.oanda_configured:
        return (
            "oanda needs an API token "
            "(KT_MARKETDATA__OANDA_TOKEN or KT_MARKETDATA__OANDA_TOKEN_FILE)"
        )
    if provider == "csv" and settings.csv_dir is None:
        return "csv needs a directory of imported files (KT_MARKETDATA__CSV_DIR)"
    return None


def select_sources(sources: DataSourceMap, settings: MarketDataSettings) -> dict[str, SourceChoice]:
    """Pick each instrument's source: the first in its chain whose provider is usable."""
    problems = settings_problems(settings)
    if problems:
        raise DataSourceError(problems)
    choices: dict[str, SourceChoice] = {}
    for instrument in sources.instruments:
        chain = sources.chain(instrument)
        passed_over: list[str] = []
        chosen: DataSource | None = None
        for source in chain:
            reason = unavailable_reason(source.provider, settings)
            if reason is None:
                chosen = source
                break
            passed_over.append(reason)
        choices[instrument] = SourceChoice(instrument, chain, chosen, tuple(passed_over))
    return choices


class ProviderMap(dict[str, MarketDataProvider]):
    """Canonical instrument → the provider serving it. Instruments whose sources are all
    unusable are absent and listed in :attr:`skipped` with the reasons; :attr:`choices`
    records the source behind every instrument (``is_fallback`` when an alternative was
    used)."""

    def __init__(
        self, providers: Mapping[str, MarketDataProvider], choices: Mapping[str, SourceChoice]
    ) -> None:
        super().__init__(providers)
        self.choices = dict(choices)
        self.skipped = {
            instrument: choice.reason
            for instrument, choice in choices.items()
            if choice.source is None
        }

    @property
    def instances(self) -> list[MarketDataProvider]:
        """Each distinct provider once."""
        unique: dict[int, MarketDataProvider] = {}
        for provider in self.values():
            unique.setdefault(id(provider), provider)
        return list(unique.values())

    async def aclose(self) -> None:
        for provider in self.instances:
            await provider.aclose()


def build_provider(
    provider: str,
    symbols: Mapping[str, str],
    settings: MarketDataSettings,
    *,
    clock: Clock | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    sleep: Sleep = asyncio.sleep,
    monotonic: Monotonic = time.monotonic,
) -> MarketDataProvider:
    """One provider serving ``symbols`` (canonical instrument → provider symbol)."""
    problems = settings_problems(settings)
    reason = unavailable_reason(provider, settings)
    if reason is not None:
        problems.append(reason)
    if problems:
        raise DataSourceError(problems)
    options = ProviderOptions.from_settings(settings)
    base_url = settings.base_urls.get(provider)
    if provider == "csv" and settings.csv_dir is not None:
        return CsvProvider.from_directory(
            Path(settings.csv_dir), list(symbols), clock=clock, close_delay_s=options.close_delay_s
        )
    if provider == "oanda" and settings.oanda_token is not None:
        return OandaProvider(
            symbols,
            token=settings.oanda_token,
            environment=settings.oanda_environment,
            options=options,
            clock=clock,
            base_url=base_url,
            transport=transport,
            sleep=sleep,
            monotonic=monotonic,
        )
    try:
        provider_type = HTTP_PROVIDERS[provider]
    except KeyError:
        raise DataSourceError([f"unknown provider {provider!r}"]) from None
    return provider_type(
        symbols,
        options=options,
        clock=clock,
        base_url=base_url,
        transport=transport,
        sleep=sleep,
        monotonic=monotonic,
    )


def build_providers(
    settings: Settings | MarketDataSettings,
    sources: DataSourceMap,
    catalog: InstrumentCatalog,
    *,
    instruments: Iterable[str] | None = None,
    clock: Clock | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    sleep: Sleep = asyncio.sleep,
    monotonic: Monotonic = time.monotonic,
) -> ProviderMap:
    """Providers for every instrument in the map (or only ``instruments``), keyed by
    canonical instrument; one shared provider object per provider name.

    Raises :class:`DataSourceError` if the map does not fit ``catalog`` or the settings
    name unknown providers.
    """
    md = settings.marketdata if isinstance(settings, Settings) else settings
    problems = sources.problems(catalog)
    if problems:
        raise DataSourceError(problems)
    choices = select_sources(sources, md)
    if instruments is not None:
        wanted = list(instruments)
        unknown = [i for i in wanted if i not in choices]
        if unknown:
            raise DataSourceError([f"no data source for {i}" for i in unknown])
        choices = {i: choices[i] for i in wanted}
    by_provider: dict[str, dict[str, str]] = {}
    for instrument, choice in choices.items():
        if choice.source is not None:
            by_provider.setdefault(choice.source.provider, {})[instrument] = choice.source.symbol
    built = {
        name: build_provider(
            name, symbols, md, clock=clock, transport=transport, sleep=sleep, monotonic=monotonic
        )
        for name, symbols in by_provider.items()
    }
    providers = {
        instrument: built[choice.source.provider]
        for instrument, choice in choices.items()
        if choice.source is not None
    }
    result = ProviderMap(providers, choices)
    for instrument, choice in choices.items():
        if choice.is_fallback and choice.source is not None:
            _log.info(
                "marketdata.fallback_source",
                instrument=instrument,
                provider=choice.source.provider,
                reason=choice.reason,
            )
    for instrument, reason in result.skipped.items():
        _log.warning("marketdata.instrument_skipped", instrument=instrument, reason=reason)
    return result


__all__ = [
    "ProviderMap",
    "SourceChoice",
    "build_provider",
    "build_providers",
    "load_data_sources",
    "select_sources",
    "settings_problems",
    "unavailable_reason",
]
