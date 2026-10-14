"""The ``engine`` process: the only process that routes signals and talks to brokers.

Phase 1 established its lifecycle and the single-active-instance guarantee
(PostgreSQL advisory-lock leader election). Phase 3 wires in **forward paper
trading**: once this process is the leader it runs the
:class:`~kterminal.paper.runtime.PaperRuntime` — live closed 1-minute bars from
the configured market-data providers into the strategy lab, every instance on
its own dedicated Paper account, results committed to PostgreSQL every minute.

The paper runtime runs only when ``<config>/lab.yaml`` exists. If it stops with
an error (for example the open session was started under a different
configuration and must be replaced with ``kterminal paper start
--new-session``), the error is logged and published in the runtime status, the
runtime's lock is released so the operator can act, and it is retried after
:data:`PAPER_RETRY_S`. LIVE (real-money) execution is not implemented: no
broker adapter is constructed here.
"""

import asyncio
import contextlib
import importlib
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from kterminal.config.settings import Settings
from kterminal.core.errors import LeadershipLostError
from kterminal.db.locks import ENGINE_LEADER_LOCK, AdvisoryLock
from kterminal.domain.catalog import InstrumentCatalog
from kterminal.marketdata.base import MarketDataProvider
from kterminal.observability.logging import get_logger
from kterminal.paper.config import LabConfig
from kterminal.paper.runtime import PaperRuntime
from kterminal.runtime.container import Container
from kterminal.runtime.service import sleep_or_stop

_log = get_logger("kterminal.engine")

PAPER_RETRY_S = 60.0

type ProviderFactory = Callable[
    [Settings, InstrumentCatalog, Sequence[str]], Mapping[str, MarketDataProvider]
]
"""Builds the market-data provider of each canonical instrument (instrument → provider)."""


def configured_providers(
    settings: Settings, catalog: InstrumentCatalog, instruments: Sequence[str]
) -> Mapping[str, MarketDataProvider]:
    """The providers named by the data-source map, from ``kterminal.marketdata.factory``.

    That module arrives with the market-data providers; until it is installed (or if
    the map cannot be built) there are no providers, the runtime reports every
    instrument as ``no_provider`` and nothing trades.
    """
    try:
        factory: Any = importlib.import_module("kterminal.marketdata.factory")
    except ImportError:
        _log.warning("engine.market_data_unavailable", reason="no provider factory installed")
        return {}
    try:
        sources = factory.load_data_sources(settings, catalog)
        built = factory.build_providers(settings, sources, catalog)
    except Exception as exc:
        _log.error("engine.market_data_failed", error=f"{type(exc).__name__}: {exc}"[:500])
        return {}
    wanted = set(instruments)
    return {symbol: provider for symbol, provider in built.items() if symbol in wanted}


async def close_providers(providers: Mapping[str, MarketDataProvider]) -> None:
    unique: dict[int, MarketDataProvider] = {}
    for provider in providers.values():
        unique.setdefault(id(provider), provider)
    for provider in unique.values():
        try:
            await provider.aclose()
        except Exception as exc:  # closing is best effort
            _log.warning("engine.provider_close_failed", provider=provider.name, error=str(exc))


async def run_engine(
    container: Container,
    stop: asyncio.Event,
    *,
    providers: ProviderFactory = configured_providers,
) -> None:
    settings = container.settings
    _log.info(
        "engine.configuration",
        default_mode=settings.trading.default_mode.value,
        live_trading_permitted=settings.trading.live_trading_permitted,
    )
    if settings.trading.live_trading_permitted:
        _log.warning("engine.live_trading_globally_enabled")

    lock = AdvisoryLock(container.db.engine, ENGINE_LEADER_LOCK)
    if not await _acquire_leadership(lock, stop, settings.runtime.leader_retry_interval_s):
        return
    paper = _PaperSupervisor.build(container, providers)
    try:
        _log.info(
            "engine.active",
            components="paper runtime" if paper is not None else "none (no lab.yaml)",
        )
        while not await sleep_or_stop(stop, settings.runtime.heartbeat_interval_s):
            if not await lock.verify():
                # Another engine may take over now; continuing would risk duplicate orders.
                raise LeadershipLostError("engine leader lock lost — stopping immediately")
            if paper is not None:
                paper.supervise()
            _log.debug("engine.heartbeat")
    finally:
        if paper is not None:
            await paper.shutdown()
        await lock.release()


class _PaperSupervisor:
    """Keeps the paper runtime running inside the engine; retries it after errors."""

    def __init__(
        self,
        container: Container,
        config: LabConfig,
        catalog: InstrumentCatalog,
        providers: ProviderFactory,
    ) -> None:
        self.container = container
        self.config = config
        self.catalog = catalog
        self.providers = providers
        self.stop = asyncio.Event()
        self.task: asyncio.Task[None] | None = None
        self.retry_at = 0.0

    @classmethod
    def build(cls, container: Container, providers: ProviderFactory) -> "_PaperSupervisor | None":
        paths = container.settings.paths
        if not paths.lab_config.exists():
            _log.info("engine.paper_disabled", reason=f"no lab configuration at {paths.lab_config}")
            return None
        try:
            config = LabConfig.load(paths.lab_config)
            catalog = InstrumentCatalog.load(paths.catalog_dir)
        except Exception as exc:
            _log.error("engine.paper_config_invalid", error=f"{type(exc).__name__}: {exc}"[:1_000])
            return None
        supervisor = cls(container, config, catalog, providers)
        supervisor.supervise()
        return supervisor

    def supervise(self) -> None:
        loop = asyncio.get_running_loop()
        if self.task is not None and not self.task.done():
            return
        if self.task is not None:
            if not self.task.cancelled() and (error := self.task.exception()) is not None:
                _log.error(
                    "engine.paper_runtime_stopped",
                    error=f"{type(error).__name__}: {error}"[:1_000],
                    retry_in_s=PAPER_RETRY_S,
                )
                self.retry_at = loop.time() + PAPER_RETRY_S
            self.task = None
        if loop.time() >= self.retry_at and not self.stop.is_set():
            self.task = asyncio.create_task(self._run(), name="paper-runtime")

    async def _run(self) -> None:
        settings = self.container.settings
        instruments = sorted({s for i in self.config.enabled_instances for s in i.instruments})
        providers = self.providers(settings, self.catalog, instruments)
        try:
            await PaperRuntime(
                config=self.config,
                catalog=self.catalog,
                database=self.container.db,
                providers=providers,
                clock=self.container.clock,
                config_dir=settings.paths.config_dir,
            ).run(self.stop)
        finally:
            await close_providers(providers)

    async def shutdown(self) -> None:
        self.stop.set()
        if self.task is not None:
            with contextlib.suppress(Exception, asyncio.CancelledError):
                await self.task


async def _acquire_leadership(lock: AdvisoryLock, stop: asyncio.Event, retry_s: float) -> bool:
    """Block (in standby) until this process becomes the leader or a stop is requested."""
    standby_logged = False
    while not stop.is_set():
        try:
            if await lock.try_acquire():
                return True
            if not standby_logged:
                _log.info("engine.standby", reason="another engine instance is active")
                standby_logged = True
        except Exception as exc:
            _log.warning("engine.leader_lock_unavailable", error=type(exc).__name__)
        if await sleep_or_stop(stop, retry_s):
            break
    return False
