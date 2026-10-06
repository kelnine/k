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
            result = await run_demo(
                catalog,
                config,
                lab_store,
                days=days,
                seed=seed,
                host="subprocess" if subprocess else None,
            )
            checks = await lab_store.isolation_checks(result.run_id)
        finally:
            await cleanup()
        report = format_report(result, checks)
        if not all(check.ok for check in checks):
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
