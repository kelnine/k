"""A demo database for looking at the dashboard (and taking its screenshots).

Everything here is SYNTHETIC: the forward runtime trades bars from fake
providers (``synthetic-fx``, ``synthetic-crypto``), never a real market feed.

1. migrates the database and creates three users (``ada`` ADMIN, ``otto``
   OPERATOR, ``vera`` VIEWER; password ``--password``);
2. records a lab simulation (``kterminal lab demo --store postgres`` code path)
   of ``config/lab.yaml``'s instances;
3. runs the real forward paper runtime (:class:`kterminal.paper.runtime.PaperRuntime`)
   on a fake clock over the last ``--hours`` hours: 16 instances of the demo
   strategies on six instruments, each in its dedicated Paper 50K account, with
   a global kill-switch drill and one strategy left halted;
4. with ``--live``, keeps the same session running on the real clock (resume:
   replay, verification, catch-up, then a new bar every minute) until Ctrl-C,
   so the dashboard shows a runtime that is alive.

Run from ``terminal/backend`` against a database of its own::

    uv run python -m tests.dashboard_demo \\
        --url postgresql://kterminal:kterminal@localhost:5432/kt_dash_demo --live
"""

import argparse
import asyncio
import contextlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from kterminal.api.auth.passwords import Passwords
from kterminal.api.auth.users import Role, create_user, get_user_by_username
from kterminal.config.settings import DatabaseSettings
from kterminal.core.clock import SystemClock
from kterminal.db import migrate
from kterminal.db.repositories.kill_switches import set_kill_switch
from kterminal.db.session import Database
from kterminal.domain.catalog import InstrumentCatalog
from kterminal.marketdata.synthetic import synthetic_bars
from kterminal.paper.config import LabConfig
from kterminal.paper.feed import FeedConfig
from kterminal.paper.lab import Lab
from kterminal.paper.pg_store import PostgresLabStore
from kterminal.paper.runtime import PaperRuntime, RuntimeOptions
from kterminal.strategy_engine.registry import discover_strategies
from tests.fixtures.forward import FakeProvider, FakeTime

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
MINUTE = timedelta(minutes=1)

# instrument → (provider, start price, tick, seed)
MARKETS: dict[str, tuple[str, str, str, int]] = {
    "XAUUSD": ("synthetic-fx", "4012.40", "0.01", 31),
    "XAGUSD": ("synthetic-fx", "48.215", "0.001", 32),
    "EURUSD": ("synthetic-fx", "1.16420", "0.00001", 33),
    "BTCUSD": ("synthetic-crypto", "112450.00", "0.01", 34),
    "SOLUSD": ("synthetic-crypto", "192.40", "0.01", 35),
    "NEARUSD": ("synthetic-crypto", "3.012", "0.001", 36),
}


def _sma(iid: str, symbol: str, tf: str, fast: int, slow: int, **extra: Any) -> dict[str, Any]:
    return {
        "id": iid,
        "strategy": "demo_sma_cross",
        "name": f"SMA {fast}/{slow} · {symbol} {tf}",
        "params": {"fast": fast, "slow": slow, **extra},
        "instruments": [symbol],
        "timeframe": tf,
    }


def _breakout(iid: str, symbol: str, tf: str, bars: int, trend: bool) -> dict[str, Any]:
    return {
        "id": iid,
        "strategy": "demo_breakout",
        "name": f"Breakout {bars}{' + 1h filter' if trend else ''} · {symbol} {tf}",
        "params": {"channel_bars": bars, "trend_filter": trend},
        "instruments": [symbol],
        "timeframe": tf,
    }


INSTANCES = [
    _sma("sma_9_21_xau_5m", "XAUUSD", "5m", 9, 21),
    _sma("sma_5_13_xau_1m", "XAUUSD", "1m", 5, 13),
    _sma("sma_20_50_xau_15m", "XAUUSD", "15m", 20, 50),
    _breakout("brk_20_xau_5m", "XAUUSD", "5m", 20, True),
    _breakout("brk_10_xau_1m", "XAUUSD", "1m", 10, False),
    _sma("sma_9_21_xag_5m", "XAGUSD", "5m", 9, 21),
    _breakout("brk_20_xag_5m", "XAGUSD", "5m", 20, False),
    _sma("sma_9_21_eur_5m", "EURUSD", "5m", 9, 21),
    _sma("sma_5_13_eur_1m", "EURUSD", "1m", 5, 13, reward_risk="1.5"),
    _sma("sma_9_21_btc_1m", "BTCUSD", "1m", 9, 21),
    _sma("sma_20_50_btc_5m", "BTCUSD", "5m", 20, 50),
    _breakout("brk_20_btc_5m", "BTCUSD", "5m", 20, True),
    _sma("sma_9_21_sol_5m", "SOLUSD", "5m", 9, 21, stop_range_mult="2"),
    _breakout("brk_10_sol_1m", "SOLUSD", "1m", 10, False),
    _sma("sma_5_13_near_1m", "NEARUSD", "1m", 5, 13),
    _breakout("brk_20_near_15m", "NEARUSD", "15m", 20, False),
]


def forward_config() -> LabConfig:
    return LabConfig.model_validate(
        {
            "equity_snapshot_minutes": 15,
            "defaults": {
                "account": {
                    "starting_balance": 50000,
                    "currency": "USD",
                    "venue_profile": "lab_default",
                    "risk_per_trade_pct": 0.5,
                    "max_open_positions": 1,
                    "trading_day": "ny_1700",
                }
            },
            "instances": INSTANCES,
        }
    )


def providers(catalog: InstrumentCatalog, clock: Any, start: datetime, end: datetime) -> Any:
    """One fake provider per venue, holding synthetic 1m bars from ``start`` to ``end``."""
    bars: dict[str, list[Any]] = {}
    minutes = int((end - start) / MINUTE)
    for symbol, (name, price, tick, seed) in MARKETS.items():
        calendar = catalog.sessions.calendar(catalog.instrument(symbol).trading_hours)
        generated = synthetic_bars(
            symbol,
            start=start,
            count=minutes,
            start_price=Decimal(price),
            tick_size=Decimal(tick),
            seed=seed,
            is_open=calendar.is_open,
            source=name,
            volatility=0.0012,
        )
        bars.setdefault(name, []).extend(b for b in generated if b.open_time < end)
    feeds = {name: FakeProvider(name, venue_bars, clock) for name, venue_bars in bars.items()}
    return {symbol: feeds[name] for symbol, (name, *_rest) in MARKETS.items()}


async def seed(url: str, *, hours: int, password: str, live: bool) -> None:
    await migrate.upgrade(url)
    database = Database(DatabaseSettings.model_validate({"url": url}), application_name="kt-demo")
    catalog = InstrumentCatalog.load(CONFIG_DIR / "catalog")
    discover_strategies(entry_points=False)
    try:
        async with database.session() as session:
            passwords = Passwords()
            for name, role in (("ada", Role.ADMIN), ("otto", Role.OPERATOR), ("vera", Role.VIEWER)):
                if await get_user_by_username(session, name) is None:
                    await create_user(
                        session,
                        username=name,
                        password_hash=passwords.hash(password),
                        role=role,
                        actor="demo",
                        now=datetime.now(UTC),
                    )
            admin = await get_user_by_username(session, "ada")
        assert admin is not None
        operator = f"user:{admin.id}"

        lab_config = LabConfig.load(CONFIG_DIR / "lab.yaml")
        await Lab(lab_config, catalog, PostgresLabStore(database), run_name="lab-demo").run(
            synthetic_bars(
                "XAUUSD",
                start=datetime.now(UTC).replace(second=0, microsecond=0) - timedelta(days=10),
                count=3 * 1_440,
                start_price=Decimal("4000.00"),
                tick_size=Decimal("0.01"),
                is_open=catalog.sessions.calendar(
                    catalog.instrument("XAUUSD").trading_hours
                ).is_open,
            )
        )

        now = datetime.now(UTC).replace(second=0, microsecond=0)
        start = now - timedelta(hours=hours)
        history = start - timedelta(days=2)
        clock = FakeTime(start + timedelta(seconds=5))

        def switch(**kwargs: Any) -> Any:
            async def action() -> None:
                async with database.session() as session:
                    await set_kill_switch(session, changed_by=operator, ts=clock.now(), **kwargs)

            return action

        clock.at(
            start + timedelta(hours=hours * 0.4),
            switch(scope="GLOBAL", active=True, reason="CPI release drill", close_positions=True),
        )
        clock.at(
            start + timedelta(hours=hours * 0.4, minutes=20),
            switch(scope="GLOBAL", active=False, reason="drill over"),
        )
        clock.at(
            start + timedelta(hours=hours * 0.8),
            switch(
                scope="STRATEGY",
                scope_id="brk_10_xau_1m",
                active=True,
                reason="too many losers in a row; review",
            ),
        )
        config = forward_config()
        fast = PaperRuntime(
            config=config,
            catalog=catalog,
            database=database,
            providers=providers(catalog, clock, history, now + timedelta(hours=6)),
            clock=clock,
            options=RuntimeOptions(warmup_days=2, feed=FeedConfig(batch_timeout_s=20)),
            discover=False,
            wait=clock.wait,
        )
        clock.stop_at = now
        await fast.run(asyncio.Event())
        if not live:
            return

        real = SystemClock()
        runtime = PaperRuntime(
            config=config,
            catalog=catalog,
            database=database,
            providers=providers(catalog, real, history, now + timedelta(hours=6)),
            clock=real,
            options=RuntimeOptions(feed=FeedConfig(poll_delay_s=2, batch_timeout_s=20)),
            discover=False,
        )
        stop = asyncio.Event()
        task = asyncio.create_task(runtime.run(stop))
        try:
            await task
        finally:
            stop.set()
            with contextlib.suppress(asyncio.CancelledError):
                await task
    finally:
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--url", required=True, help="PostgreSQL URL of an EMPTY database")
    parser.add_argument("--hours", type=int, default=8, help="forward history to fast-forward")
    parser.add_argument("--password", default="demo-password-123", help="password of the users")
    parser.add_argument("--live", action="store_true", help="keep the runtime running live")
    args = parser.parse_args()
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(seed(args.url, hours=args.hours, password=args.password, live=args.live))


if __name__ == "__main__":
    main()
