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

import typer
from pydantic import ValidationError

from kterminal import __version__
from kterminal.config.settings import Settings, load_settings
from kterminal.core.errors import LeadershipLostError
from kterminal.observability.logging import configure_logging, get_logger
from kterminal.runtime.container import Container
from kterminal.runtime.service import run_until_signalled

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
