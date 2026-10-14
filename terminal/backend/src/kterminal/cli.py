"""Command-line entry point: ``kterminal <command>``.

One Docker image, several process roles::

    kterminal api        # dashboard API + TradingView webhook receiver
    kterminal engine     # signal routing, risk, execution (single active instance)
    kterminal worker     # notifications, reports, analytics, backtests
    kterminal config check | show
"""

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

import typer
from pydantic import ValidationError

from kterminal import __version__
from kterminal.config.settings import Settings, load_settings
from kterminal.core.errors import LeadershipLostError
from kterminal.observability.logging import configure_logging, get_logger
from kterminal.runtime.container import Container
from kterminal.runtime.service import run_until_signalled

if TYPE_CHECKING:
    from kterminal.domain.catalog import InstrumentCatalog

EXIT_CONFIG_ERROR = 2
EXIT_LEADERSHIP_LOST = 3

app = typer.Typer(
    name="kterminal",
    help="K Terminal — modular algorithmic trading terminal.",
    no_args_is_help=True,
    add_completion=False,
)
config_app = typer.Typer(help="Inspect and validate configuration.", no_args_is_help=True)
app.add_typer(config_app, name="config")
catalog_app = typer.Typer(
    help="Instrument catalog: instruments, venues, listings, sessions, costs.", no_args_is_help=True
)
app.add_typer(catalog_app, name="catalog")
strategies_app = typer.Typer(help="Strategy definitions and lab instances.", no_args_is_help=True)
app.add_typer(strategies_app, name="strategies")
lab_app = typer.Typer(help="The strategy lab.", no_args_is_help=True)
app.add_typer(lab_app, name="lab")
db_app = typer.Typer(help="Database migrations, partitions and audit log.", no_args_is_help=True)
app.add_typer(db_app, name="db")


def _load_settings_or_exit() -> Settings:
    try:
        return load_settings()
    except ValidationError as exc:
        typer.echo("Configuration is invalid:", err=True)
        # Never echo input values: they may be secrets.
        for error in exc.errors(include_input=False, include_url=False):
            location = ".".join(str(part) for part in error["loc"]) or "settings"
            typer.echo(f"  - {location}: {error['msg']}", err=True)
        raise typer.Exit(EXIT_CONFIG_ERROR) from None
    except OSError as exc:
        typer.echo(f"Configuration is invalid: {exc}", err=True)
        raise typer.Exit(EXIT_CONFIG_ERROR) from None


def _bootstrap(role: str) -> Settings:
    settings = _load_settings_or_exit()
    configure_logging(
        settings.logging,
        service=f"{settings.service_name}-{role}",
        environment=settings.environment.value,
    )
    return settings


def _run_role(
    role: str, settings: Settings, main: Callable[[Container, asyncio.Event], Awaitable[None]]
) -> None:
    async def _run() -> None:
        container = Container.build(settings, role=role)
        try:
            await run_until_signalled(role, lambda stop: main(container, stop))
        finally:
            await container.aclose()

    try:
        asyncio.run(_run())
    except LeadershipLostError as exc:
        get_logger("kterminal.cli").critical("process.leadership_lost", role=role, error=str(exc))
        raise typer.Exit(EXIT_LEADERSHIP_LOST) from None


@app.command()
def api() -> None:
    """Run the HTTP API (dashboard API, health probes, TradingView webhook receiver)."""
    import uvicorn

    from kterminal.api.app import create_app
    from kterminal.db.session import Database

    settings = _bootstrap("api")
    database = Database(settings.database, application_name=f"{settings.service_name}-api")
    uvicorn.run(
        create_app(settings, database),
        host=settings.api.host,
        port=settings.api.port,
        log_config=None,  # logging is already configured (structured JSON)
        access_log=False,  # RequestContextMiddleware logs requests with correlation IDs
        proxy_headers=True,
        forwarded_allow_ips=",".join(settings.api.trusted_proxies),
        server_header=False,
    )


@app.command()
def engine() -> None:
    """Run the trading engine (exactly one active instance; others wait in standby)."""
    from kterminal.runtime.engine import run_engine

    _run_role("engine", _bootstrap("engine"), run_engine)


@app.command()
def worker() -> None:
    """Run a background worker (notifications, reports, analytics, backtests)."""
    from kterminal.runtime.worker import run_worker

    _run_role("worker", _bootstrap("worker"), run_worker)


@app.command()
def version() -> None:
    """Print the version."""
    typer.echo(__version__)


@config_app.command("check")
def config_check() -> None:
    """Validate configuration (including the LIVE-trading interlocks) and summarize it."""
    settings = _load_settings_or_exit()
    live = settings.trading.live_trading_permitted
    typer.echo(f"environment            : {settings.environment.value}")
    typer.echo(f"default trading mode   : {settings.trading.default_mode.value}")
    typer.echo(f"live trading permitted : {'YES — real money at risk' if live else 'no'}")
    typer.echo("configuration OK")


@config_app.command("show")
def config_show() -> None:
    """Print the effective configuration as JSON with every secret masked."""
    typer.echo(json.dumps(_load_settings_or_exit().redacted(), indent=2))


# ── catalog ──────────────────────────────────────────────────────────────────
def _load_catalog(settings: Settings, directory: Path | None) -> "InstrumentCatalog":
    from kterminal.domain.catalog import CatalogError, InstrumentCatalog

    path = directory or settings.paths.catalog_dir
    try:
        return InstrumentCatalog.load(path)
    except CatalogError as exc:
        typer.echo(f"Catalog {path} is invalid:", err=True)
        for problem in exc.problems:
            typer.echo(f"  - {problem}", err=True)
        raise typer.Exit(EXIT_CONFIG_ERROR) from None


CatalogDir = Annotated[
    Path | None, typer.Option("--dir", help="Catalog directory (default: <config>/catalog)")
]


@catalog_app.command("validate")
def catalog_validate(directory: CatalogDir = None) -> None:
    """Load and cross-check every catalog file; print a summary and the fingerprint."""
    catalog = _load_catalog(_load_settings_or_exit(), directory)
    typer.echo(
        f"{len(catalog.instruments)} instruments, {len(catalog.venues)} venues, "
        f"{len(catalog.listings)} listings, {len(catalog.aliases)} aliases, "
        f"{len(catalog.cost_profiles)} cost profiles, {len(catalog.venue_profiles)} venue profiles"
    )
    typer.echo(f"fingerprint {catalog.fingerprint}")
    typer.echo("catalog OK")


@catalog_app.command("show")
def catalog_show(symbol: str, directory: CatalogDir = None) -> None:
    """Show an instrument and every venue listing of it (accepts any alias)."""
    catalog = _load_catalog(_load_settings_or_exit(), directory)
    try:
        instrument = catalog.resolve_symbol(symbol)
    except LookupError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None
    today = datetime.now(UTC).date()
    typer.echo(
        f"{instrument.symbol} — {instrument.name} ({instrument.asset_class.value}), "
        f"tick {instrument.tick_size}, hours {instrument.trading_hours}, "
        f"day {instrument.trading_day}"
    )
    for listing in sorted(catalog.listings_for(instrument.symbol), key=lambda item: item.key):
        typer.echo(
            f"  {listing.venue:<20} {listing.venue_symbol_for(instrument, today):<22} "
            f"{listing.contract_type.value:<11} tick {listing.tick_size:<10} "
            f"size {listing.contract_size:<8} {listing.quantity_unit.value:<10} "
            f"min {listing.min_qty:<8} step {listing.qty_step:<8} {listing.quote_currency:<5} "
            f"costs {listing.cost_profile or '-'}"
        )


@catalog_app.command("resolve")
def catalog_resolve(
    raw: str,
    source: Annotated[str | None, typer.Option(help="Venue/source the symbol came from")] = None,
    directory: CatalogDir = None,
) -> None:
    """Map an outside symbol (e.g. BINANCE:NEARUSDT.P, US100, MNQ1!) to the canonical one."""
    catalog = _load_catalog(_load_settings_or_exit(), directory)
    try:
        typer.echo(catalog.resolve_symbol(raw, source).symbol)
    except LookupError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None


# ── strategies ───────────────────────────────────────────────────────────────
@strategies_app.command("list")
def strategies_list(
    lab_config: Annotated[Path | None, typer.Option("--config", help="lab.yaml")] = None,
) -> None:
    """Registered strategy definitions, and the instances configured in lab.yaml."""
    from kterminal.paper.config import LabConfig
    from kterminal.strategy_engine import DEFINITIONS, discover_strategies

    settings = _load_settings_or_exit()
    discover_strategies()
    typer.echo("Definitions:")
    for definition_id, definition in DEFINITIONS.items():
        meta = definition.meta
        typer.echo(
            f"  {definition_id:<24} v{meta.version:<8} {definition.kind.value:<9} "
            f"code {definition.code_hash[:12]}  {meta.name}"
        )
    path = lab_config or settings.paths.lab_config
    if not path.exists():
        typer.echo(f"(no lab config at {path})")
        return
    config = LabConfig.load(path)
    typer.echo(f"Instances ({path}):")
    for instance in config.instances:
        account = config.account_settings(instance)
        state = "enabled" if instance.enabled else "disabled"
        typer.echo(
            f"  {instance.id:<24} {instance.strategy:<20} {','.join(instance.instruments):<12} "
            f"{instance.timeframe:<4} {account.display_name_prefix:<11} {state}"
        )


# ── lab ──────────────────────────────────────────────────────────────────────
@lab_app.command("demo")
def lab_demo(
    days: Annotated[float, typer.Option(help="Days of synthetic 1-minute data")] = 5,
    seed: Annotated[int, typer.Option(help="Random seed for the synthetic data")] = 21,
    subprocess: Annotated[bool, typer.Option(help="Run each instance in its own process")] = False,
    store: Annotated[str, typer.Option(help="memory | postgres")] = "memory",
    lab_config: Annotated[Path | None, typer.Option("--config", help="lab.yaml")] = None,
) -> None:
    """Run the configured instances simultaneously on synthetic data, each into its own
    paper account, and audit from the recorded rows that they did not affect each other."""
    from kterminal.paper.config import LabConfig
    from kterminal.paper.demo import format_report, run_demo

    settings = _bootstrap("lab")
    catalog = _load_catalog(settings, None)
    config = LabConfig.load(lab_config or settings.paths.lab_config)

    async def _run() -> str:
        lab_store, cleanup = await _open_store(store, settings)
        try:
            demo = await run_demo(
                catalog,
                config,
                lab_store,
                days=days,
                seed=seed,
                host="subprocess" if subprocess else None,
            )
            checks = await lab_store.isolation_checks(demo.result.run_id)
        finally:
            await cleanup()
        report = format_report(demo.result, checks, demo.solo)
        if not checks or not all(check.ok for check in [*checks, *demo.solo]):
            raise RuntimeError(report)
        return report

    try:
        typer.echo(asyncio.run(_run()))
    except RuntimeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None


@lab_app.command("provision")
def lab_provision(
    lab_config: Annotated[Path | None, typer.Option("--config", help="lab.yaml")] = None,
) -> None:
    """Create each instance's persistent Paper account (default $50,000) in the database.

    Registers definitions, instances and their current versions. Idempotent.
    """
    from kterminal.paper.config import LabConfig
    from kterminal.paper.lab import Lab

    settings = _bootstrap("lab")
    catalog = _load_catalog(settings, None)
    config = LabConfig.load(lab_config or settings.paths.lab_config)

    async def _run() -> list[str]:
        lab_store, cleanup = await _open_store("postgres", settings)
        try:
            lines = []
            for instance_id, account in await Lab(config, catalog, lab_store).provision_dedicated():
                state = "created" if account.created else "up to date"
                lines.append(f"{instance_id:<24} {account.name:<36} {account.account_id}  {state}")
            return lines
        finally:
            await cleanup()

    for line in asyncio.run(_run()):
        typer.echo(line)


async def _open_store(kind: str, settings: Settings) -> tuple[Any, Callable[[], Awaitable[None]]]:
    from kterminal.paper.store import InMemoryLabStore

    async def nothing() -> None:
        return None

    if kind == "memory":
        return InMemoryLabStore(), nothing
    if kind == "postgres":
        from kterminal.db.session import Database
        from kterminal.paper.pg_store import PostgresLabStore

        database = Database(settings.database, application_name=f"{settings.service_name}-lab")
        return PostgresLabStore(database), database.dispose
    raise typer.BadParameter(f"unknown store {kind!r} (memory | postgres)")


# ── database ─────────────────────────────────────────────────────────────────
@db_app.command("upgrade")
def db_upgrade(revision: str = "head") -> None:
    """Apply migrations (default: to the latest revision), then ensure partitions exist."""
    from kterminal.db import migrate
    from kterminal.db.partitions import ensure_monthly_partitions
    from kterminal.db.session import Database

    settings = _bootstrap("migrate")

    async def _run() -> list[str]:
        await migrate.upgrade(settings.database.dsn(), revision)
        database = Database(settings.database, application_name="kterminal-migrate")
        try:
            return await ensure_monthly_partitions(database.engine, today=datetime.now(UTC).date())
        finally:
            await database.dispose()

    created = asyncio.run(_run())
    typer.echo(f"database at revision {revision}; {len(created)} new monthly partitions")


@db_app.command("current")
def db_current() -> None:
    """Print the database's current migration revision."""
    from kterminal.db import migrate

    settings = _load_settings_or_exit()
    typer.echo(asyncio.run(migrate.current(settings.database.dsn())) or "(empty database)")


@db_app.command("check")
def db_check() -> None:
    """Fail if the live schema differs from the models (missing migration)."""
    from kterminal.db import migrate

    settings = _load_settings_or_exit()
    differences = asyncio.run(migrate.check(settings.database.dsn()))
    if differences:
        typer.echo("schema differs from the models:", err=True)
        for difference in differences:
            typer.echo(f"  - {difference}", err=True)
        raise typer.Exit(1)
    typer.echo("schema matches the models")


@db_app.command("verify-audit")
def db_verify_audit() -> None:
    """Recompute the audit log hash chain and report the first broken link."""
    from kterminal.db.audit import verify
    from kterminal.db.session import Database

    settings = _load_settings_or_exit()

    async def _run() -> Any:
        database = Database(settings.database, application_name="kterminal-audit")
        try:
            async with database.session() as session:
                return await verify(session)
        finally:
            await database.dispose()

    result = asyncio.run(_run())
    if not result.ok:
        typer.echo(
            f"audit chain BROKEN at seq {result.first_bad_seq} ({result.checked} entries checked)",
            err=True,
        )
        raise typer.Exit(1)
    typer.echo(f"audit chain OK ({result.checked} entries)")


@catalog_app.command("apply")
def catalog_apply(directory: CatalogDir = None) -> None:
    """Write the catalog to the database (upsert) and record a snapshot of its fingerprint."""
    from kterminal.db.repositories.catalog import apply_catalog
    from kterminal.db.session import Database

    settings = _bootstrap("catalog")
    catalog = _load_catalog(settings, directory)

    async def _run() -> Any:
        database = Database(settings.database, application_name="kterminal-catalog")
        try:
            async with database.session() as session:
                return await apply_catalog(
                    session, catalog.to_document(), catalog.fingerprint, applied_by="cli"
                )
        finally:
            await database.dispose()

    snapshot = asyncio.run(_run())
    state = "new snapshot" if snapshot.created else "unchanged"
    typer.echo(f"catalog applied ({state}) fingerprint {snapshot.fingerprint}")


# ── market data (docs/15-market-data.md) ─────────────────────────────────────
# Read-only: these commands download candles; nothing here can place an order.
data_app = typer.Typer(
    help="Market data: data sources and history downloads.", no_args_is_help=True
)
app.add_typer(data_app, name="data")


def _data_sources_or_exit(settings: Settings, catalog: "InstrumentCatalog") -> Any:
    from kterminal.marketdata.factory import load_data_sources
    from kterminal.marketdata.sources import DataSourceError

    try:
        return load_data_sources(settings, catalog)
    except DataSourceError as exc:
        typer.echo("Data source map is invalid:", err=True)
        for problem in exc.problems:
            typer.echo(f"  - {problem}", err=True)
        raise typer.Exit(EXIT_CONFIG_ERROR) from None


def _source_choices_or_exit(sources: Any, settings: Settings) -> Any:
    from kterminal.marketdata.factory import select_sources
    from kterminal.marketdata.sources import DataSourceError

    try:
        return select_sources(sources, settings.marketdata)
    except DataSourceError as exc:
        typer.echo("Market-data settings are invalid:", err=True)
        for problem in exc.problems:
            typer.echo(f"  - {problem}", err=True)
        raise typer.Exit(EXIT_CONFIG_ERROR) from None


def _utc_option(value: str, option: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        raise typer.BadParameter(
            f"{value!r} is not an ISO date or time (e.g. 2026-10-01 or 2026-10-01T13:30Z)",
            param_hint=option,
        ) from None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


@data_app.command("sources")
def data_sources(
    notes: Annotated[bool, typer.Option("--notes", help="Show each source's note")] = False,
) -> None:
    """Each instrument's data source and whether its provider is usable on this host.

    Disabled (KT_MARKETDATA__DISABLED_PROVIDERS) or unconfigured providers fall back to the
    instrument's alternatives. "configured" does not mean the venue was reached.
    """
    from kterminal.marketdata.factory import unavailable_reason
    from kterminal.marketdata.sources import PROVIDERS

    settings = _load_settings_or_exit()
    catalog = _load_catalog(settings, None)
    sources = _data_sources_or_exit(settings, catalog)
    choices = _source_choices_or_exit(sources, settings)
    path = settings.marketdata.sources_file or settings.paths.data_sources
    typer.echo(f"Data sources ({path}):")
    typer.echo(f"  {'INSTRUMENT':<10} {'PROVIDER':<13} {'SYMBOL':<16} {'VOLUME':<9} STATUS")
    for instrument, choice in choices.items():
        source = choice.source or choice.chain[0]
        if choice.source is None:
            status = f"skipped: {choice.reason}"
        elif choice.is_fallback:
            status = f"configured (alternative: {choice.reason})"
        else:
            status = "configured"
        typer.echo(
            f"  {instrument:<10} {source.provider:<13} {source.symbol:<16} "
            f"{source.volume.value:<9} {status}"
        )
        if notes and source.note:
            typer.echo(f"  {'':<10} {source.note}")
    uncovered = sorted(set(catalog.instruments) - set(sources.instruments))
    if uncovered:
        typer.echo(f"No data source: {', '.join(uncovered)}")
    typer.echo("Providers:")
    for name, info in PROVIDERS.items():
        reason = unavailable_reason(name, settings.marketdata)
        typer.echo(f"  {name:<13} {reason or 'configured'} — {info.description}")


@data_app.command("fetch")
def data_fetch(
    instrument: Annotated[str, typer.Argument(help="Canonical symbol or any alias")],
    start: Annotated[str, typer.Option(help="First minute, ISO (UTC unless an offset is given)")],
    end: Annotated[str, typer.Option(help="End, exclusive, ISO (UTC unless an offset is given)")],
    out: Annotated[Path, typer.Option(help="CSV file to write (time,open,high,low,close,volume)")],
    provider: Annotated[
        str | None, typer.Option(help="Use this provider's source of the instrument")
    ] = None,
) -> None:
    """Download closed 1m bars with start <= time < end from the instrument's data source
    into a CSV file (re-readable with read_bars_csv). Missing minutes stay missing."""
    import logging

    from kterminal.marketdata.base import MarketDataError
    from kterminal.marketdata.csv_import import write_bars_csv
    from kterminal.marketdata.factory import build_provider, unavailable_reason
    from kterminal.marketdata.sources import DataSourceError

    first, stop = _utc_option(start, "--start"), _utc_option(end, "--end")
    if stop <= first:
        raise typer.BadParameter("must be after --start", param_hint="--end")
    settings = _bootstrap("data")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one INFO line per request otherwise
    catalog = _load_catalog(settings, None)
    try:
        symbol = catalog.resolve_symbol(instrument).symbol
    except LookupError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None
    sources = _data_sources_or_exit(settings, catalog)
    if symbol not in sources.instruments:
        typer.echo(f"{symbol} has no data source", err=True)
        raise typer.Exit(1)
    if provider is not None:
        try:
            source = sources.source(symbol, provider)
        except KeyError as exc:
            typer.echo(str(exc.args[0]), err=True)
            raise typer.Exit(1) from None
        reason = unavailable_reason(provider, settings.marketdata)
        if reason is not None:
            typer.echo(f"{symbol}: {reason}", err=True)
            raise typer.Exit(EXIT_CONFIG_ERROR)
    else:
        choice = _source_choices_or_exit(sources, settings)[symbol]
        if choice.source is None:
            typer.echo(f"{symbol}: no usable data source: {choice.reason}", err=True)
            raise typer.Exit(EXIT_CONFIG_ERROR)
        source = choice.source

    async def _run() -> list[Any]:
        try:
            feed = build_provider(source.provider, {symbol: source.symbol}, settings.marketdata)
        except DataSourceError as exc:
            raise MarketDataError("; ".join(exc.problems)) from None
        try:
            return await feed.history(symbol, first, stop)
        finally:
            await feed.aclose()

    try:
        bars = asyncio.run(_run())
    except MarketDataError as exc:
        typer.echo(f"fetch failed: {exc}", err=True)
        raise typer.Exit(1) from None
    count = write_bars_csv(out, bars)
    span = (
        f"{bars[0].open_time:%Y-%m-%d %H:%M} → {bars[-1].open_time:%Y-%m-%d %H:%M} UTC"
        if bars
        else "no bars in the range"
    )
    typer.echo(
        f"{count} bars of {symbol} from {source.provider} {source.symbol} "
        f"({source.volume.value} volume), {span}, written to {out}"
    )


# ════════════════════════════════════════════════════════════════════════════
# Forward paper trading, candle import and kill switches (docs/12 §12.7, runbook)
# ════════════════════════════════════════════════════════════════════════════
paper_app = typer.Typer(help="Forward paper trading on live data.", no_args_is_help=True)
app.add_typer(paper_app, name="paper")
killswitch_app = typer.Typer(
    help="Kill switches: stop new entries globally, per account or per strategy.",
    no_args_is_help=True,
)
app.add_typer(killswitch_app, name="killswitch")

EXIT_PAPER_ERROR = 1


@paper_app.command("start")
def paper_start(
    new_session: Annotated[
        bool,
        typer.Option(
            "--new-session",
            help="End the open session (closing its positions at the last price) and start anew",
        ),
    ] = False,
    warmup_days: Annotated[
        float | None,
        typer.Option(
            "--warmup-days",
            help="How far back warm-up history may reach (default: lab.yaml forward.warmup_days)",
        ),
    ] = None,
    lab_config: Annotated[
        Path | None, typer.Option("--config", help="lab.yaml (instances.d/ beside it is read too)")
    ] = None,
) -> None:
    """Paper-trade the lab's instances on live bars until Ctrl-C / SIGTERM.

    Resumes the open forward session (replaying its logged bars and checking the result
    against the database) or starts a new one. Every instance trades only its own
    dedicated Paper account; nothing here can place a real order.
    """
    from kterminal.db.session import Database
    from kterminal.paper.forward import ForwardSessionError
    from kterminal.paper.runtime import PaperRuntime, RuntimeLockedError, RuntimeOptions
    from kterminal.runtime.engine import close_providers, unavailable_reasons

    if warmup_days is not None and warmup_days < 0:
        raise typer.BadParameter("cannot be negative", param_hint="--warmup-days")
    settings = _bootstrap("paper")
    catalog = _load_catalog(settings, None)
    config = _forward_config_or_exit(lab_config or settings.paths.lab_config)
    instruments = sorted({s for i in config.enabled_instances for s in i.instruments})
    providers = _paper_providers_or_exit(settings, catalog, instruments)
    for symbol, reason in sorted(unavailable_reasons(providers).items()):
        typer.echo(f"{symbol}: no market data ({reason}) — its instances will not trade", err=True)

    async def main(stop: asyncio.Event) -> None:
        database = Database(settings.database, application_name=f"{settings.service_name}-paper")
        try:
            await PaperRuntime(
                config=config,
                catalog=catalog,
                database=database,
                providers=providers,
                options=RuntimeOptions(new_session=new_session, warmup_days=warmup_days),
                config_dir=settings.paths.config_dir,
                unavailable=unavailable_reasons(providers),
            ).run(stop)
        finally:
            await close_providers(providers)
            await database.dispose()

    try:
        asyncio.run(run_until_signalled("paper", main))
    except (ForwardSessionError, RuntimeLockedError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_PAPER_ERROR) from None


def _forward_config_or_exit(path: Path) -> Any:
    from kterminal.paper.config import load_forward_config

    try:
        return load_forward_config(path)
    except (OSError, ValueError) as exc:  # pydantic's ValidationError is a ValueError
        typer.echo(f"Lab configuration is invalid: {exc}", err=True)
        raise typer.Exit(EXIT_CONFIG_ERROR) from None


def _paper_providers_or_exit(
    settings: Settings, catalog: "InstrumentCatalog", instruments: list[str]
) -> Any:
    from kterminal.marketdata.sources import DataSourceError
    from kterminal.runtime.engine import configured_providers

    try:
        return configured_providers(settings, catalog, instruments)
    except DataSourceError as exc:
        typer.echo("Market data is not usable:", err=True)
        for problem in exc.problems:
            typer.echo(f"  - {problem}", err=True)
        raise typer.Exit(EXIT_CONFIG_ERROR) from None


@paper_app.command("end-session")
def paper_end_session() -> None:
    """End the open forward session without starting a new one: its open positions are
    closed at their last processed price and recorded. The next start begins a fresh
    session (e.g. after changing the configuration). Refused while a runtime runs."""
    from kterminal.db.session import Database
    from kterminal.paper.runtime import RuntimeLockedError, end_open_sessions

    settings = _bootstrap("paper")

    async def _run() -> list[tuple[Any, int]]:
        database = Database(settings.database, application_name="kterminal-paper-end")
        try:
            return await end_open_sessions(database)
        finally:
            await database.dispose()

    try:
        ended = asyncio.run(_run())
    except RuntimeLockedError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_PAPER_ERROR) from None
    if not ended:
        typer.echo("no forward session is open")
    for run_id, closed in ended:
        typer.echo(f"ended forward session {run_id} ({closed} open position(s) closed)")


@paper_app.command("status")
def paper_status() -> None:
    """The paper runtime's last published status and the open session's accounts."""
    from uuid import UUID

    from kterminal.db.repositories.accounts import get_account_state
    from kterminal.db.session import Database
    from kterminal.paper.pg_forward import PostgresForwardStore

    settings = _load_settings_or_exit()

    async def _run() -> list[str]:
        database = Database(settings.database, application_name="kterminal-paper-status")
        store = PostgresForwardStore(database)
        try:
            status = await store.read_status()
            lines = _format_runtime_status(status)
            for stored in await store.open_sessions():
                plan = stored.config.get("plan", {})
                lines.append(
                    f"Open session {stored.run_id} since {plan.get('live_start', '?')}, "
                    f"processed through {stored.progress.get('processed_through', '?')} "
                    f"({stored.progress.get('minutes', 0)} minutes with bars)"
                )
                for instance, account in sorted(plan.get("accounts", {}).items()):
                    async with database.session() as session:
                        state = await get_account_state(session, UUID(account["account_id"]))
                    lines.append(
                        f"  {instance:<24} {state.name:<36} balance {state.balance:>14,.2f}  "
                        f"open {state.open_trades}  closed {state.closed_trades}"
                    )
            return lines
        finally:
            await database.dispose()

    for line in asyncio.run(_run()):
        typer.echo(line)


def _format_runtime_status(status: dict[str, Any] | None) -> list[str]:
    if status is None:
        return ["Paper runtime: never started"]
    lines = [
        f"Paper runtime: {status.get('status')} (updated {status.get('updated_at')}, "
        f"run {status.get('run_id')}, last minute {status.get('last_batch_close') or '—'})"
    ]
    if status.get("error"):
        lines.append(f"  error: {status['error']}")
    kill = status.get("kill_switch") or {}
    lines.append(
        f"  kill switch: global {'ON' if kill.get('global') else 'off'}; "
        f"accounts {', '.join(kill.get('accounts') or []) or '—'}; "
        f"strategies {', '.join(kill.get('strategies') or []) or '—'}"
    )
    for symbol, info in sorted((status.get("instruments") or {}).items()):
        lines.append(
            f"  {symbol:<10} {info.get('provider') or '—':<14} {info.get('state'):<12} "
            f"last bar {info.get('last_bar_open') or '—'}  lag {info.get('lag_seconds')} s"
            + (f"  ({info['last_error']})" if info.get("last_error") else "")
        )
    for instance, info in sorted((status.get("instances") or {}).items()):
        lines.append(
            f"  {instance:<24} {info.get('state'):<9} account {info.get('account_id')}"
            + (f"  FAULT {info['fault']}" if info.get("fault") else "")
        )
    return lines


@paper_app.command("sessions")
def paper_sessions(
    limit: Annotated[int, typer.Option(help="How many sessions to list")] = 20,
) -> None:
    """Forward sessions, newest first."""
    from kterminal.db.session import Database
    from kterminal.paper.pg_forward import PostgresForwardStore

    settings = _load_settings_or_exit()

    async def _run() -> list[Any]:
        database = Database(settings.database, application_name="kterminal-paper-sessions")
        try:
            return await PostgresForwardStore(database).sessions(limit)
        finally:
            await database.dispose()

    sessions = asyncio.run(_run())
    if not sessions:
        typer.echo("no forward sessions yet")
        return
    typer.echo(
        f"{'RUN ID':<38}{'STATUS':<11}{'STARTED':<27}{'PROCESSED THROUGH':<27}"
        f"{'MINUTES':>8}  INSTANCES"
    )
    for stored in sessions:
        plan = stored.config.get("plan", {})
        typer.echo(
            f"{stored.run_id!s:<38}{stored.status:<11}{plan.get('live_start', '?'):<27}"
            f"{stored.progress.get('processed_through', '?'):<27}"
            f"{stored.progress.get('minutes', 0):>8}  "
            f"{', '.join(sorted(plan.get('versions', {})))}"
        )


@data_app.command("import-csv")
def data_import_csv(
    file: Annotated[Path, typer.Argument(help="CSV with time, open, high, low, close[, volume]")],
    instrument: Annotated[str, typer.Option(help="Instrument (any alias, e.g. OANDA:XAUUSD)")],
    source: Annotated[str, typer.Option(help="Source label stored with the bars")],
    timeframe: Annotated[str, typer.Option(help="Bar timeframe")] = "1m",
    tz: Annotated[str, typer.Option(help="Time zone of times without an offset")] = "UTC",
) -> None:
    """Load bars from a CSV file (generic OHLCV or a TradingView export, docs/15) into the
    candles table; bars already stored for the same minute are kept."""
    from kterminal.db.repositories.candles import insert_candles
    from kterminal.db.session import Database
    from kterminal.marketdata.csv_import import read_bars_csv

    settings = _bootstrap("data")
    catalog = _load_catalog(settings, None)
    try:
        symbol = catalog.resolve_symbol(instrument).symbol
        bars = read_bars_csv(file, symbol, source=source, timeframe=timeframe, tz=tz)
    except (LookupError, OSError, ValueError) as exc:
        typer.echo(f"cannot import {file}: {exc}", err=True)
        raise typer.Exit(1) from None
    if not bars:
        typer.echo(f"{file}: no bars")
        return

    async def _run() -> int:
        database = Database(settings.database, application_name="kterminal-data-import")
        try:
            async with database.session() as session:
                return await insert_candles(session, bars)
        finally:
            await database.dispose()

    inserted = asyncio.run(_run())
    typer.echo(
        f"{symbol} {timeframe} from {source}: {len(bars)} bars "
        f"({bars[0].open_time.isoformat()} → {bars[-1].open_time.isoformat()}), "
        f"{inserted} inserted, {len(bars) - inserted} already stored"
    )


ScopeOption = Annotated[str, typer.Option("--scope", help="global | account | strategy")]
IdOption = Annotated[
    str | None, typer.Option("--id", help="Account id (ACCOUNT) or strategy instance id")
]


def _set_kill_switch(
    scope: str, scope_id: str | None, *, active: bool, reason: str, close_positions: bool
) -> str:
    from kterminal.db.repositories.kill_switches import KillSwitchError, set_kill_switch
    from kterminal.db.session import Database

    settings = _bootstrap("killswitch")

    async def _run() -> str:
        database = Database(settings.database, application_name="kterminal-killswitch")
        try:
            async with database.session() as session:
                record = await set_kill_switch(
                    session,
                    scope=scope,
                    scope_id=scope_id,
                    active=active,
                    reason=reason,
                    changed_by="cli",
                    ts=datetime.now(UTC),
                    close_positions=close_positions,
                )
        finally:
            await database.dispose()
        target = "GLOBAL" if record.scope == "GLOBAL" else f"{record.scope} {record.scope_id}"
        extra = " — open positions will be closed at the next bar" if record.close_positions else ""
        return f"kill switch {target}: {'ON' if record.active else 'off'}{extra}"

    try:
        return asyncio.run(_run())
    except KillSwitchError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None


@killswitch_app.command("on")
def killswitch_on(
    reason: Annotated[str, typer.Option(help="Why (recorded in the audit log)")],
    scope: ScopeOption = "global",
    scope_id: IdOption = None,
    close_positions: Annotated[
        bool, typer.Option("--close-positions", help="Also flatten open positions at the next bar")
    ] = False,
) -> None:
    """Stop new entries (exits and stop moves still work). Takes effect at the next bar."""
    typer.echo(
        _set_kill_switch(
            scope, scope_id, active=True, reason=reason, close_positions=close_positions
        )
    )


@killswitch_app.command("off")
def killswitch_off(
    scope: ScopeOption = "global",
    scope_id: IdOption = None,
    reason: Annotated[str, typer.Option(help="Why (recorded in the audit log)")] = "released",
) -> None:
    """Allow new entries again for the scope."""
    typer.echo(
        _set_kill_switch(scope, scope_id, active=False, reason=reason, close_positions=False)
    )


@killswitch_app.command("status")
def killswitch_status() -> None:
    """Every kill switch and its state."""
    from kterminal.db.repositories.kill_switches import list_kill_switches
    from kterminal.db.session import Database

    settings = _load_settings_or_exit()

    async def _run() -> list[Any]:
        database = Database(settings.database, application_name="kterminal-killswitch")
        try:
            async with database.session() as session:
                return await list_kill_switches(session)
        finally:
            await database.dispose()

    switches = asyncio.run(_run())
    if not any(s.active for s in switches):
        typer.echo("no kill switch is active")
    for switch in switches:
        target = "GLOBAL" if switch.scope == "GLOBAL" else f"{switch.scope} {switch.scope_id}"
        typer.echo(
            f"{target:<50} {'ON ' if switch.active else 'off'} "
            f"{'close positions ' if switch.close_positions else ''}"
            f"by {switch.changed_by} at {switch.changed_at.isoformat()}: {switch.reason}"
        )
