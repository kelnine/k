"""The dashboard against the real forward paper runtime.

The runtime trades live bars from fake providers on a fake clock (the set-up of
``tests/integration/paper``) into a fresh database. While it runs, an operator
uses the dashboard API to pull the global kill switch (closing positions) and,
later, to release it; the runtime picks both changes up from ``kill_switches``.
Afterwards every dashboard view is read from what the runtime wrote: its
status document, the dedicated accounts, signals rejected by the switch,
flattened trades, the candles log with trade markers and the audit trail.
"""

from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.engine import make_url

from kterminal.analytics.summary import summarize_trades
from kterminal.api.app import API_PREFIX, create_app
from kterminal.api.auth.settings import AuthSettings
from kterminal.api.auth.users import Role, create_user
from kterminal.config.settings import DatabaseSettings, Settings
from kterminal.core.ids import uuid7
from kterminal.db import migrate
from kterminal.db import models as m
from kterminal.db.session import Database
from tests.fixtures.forward import FakeTime
from tests.integration.api.conftest import SECRET, _admin
from tests.integration.api.demo import PASSWORD, cheap_passwords
from tests.integration.paper.forward_helpers import MIN, START, lab_config, run_runtime

pytestmark = pytest.mark.integration

END = START + 90 * MIN
HALT_AT = START + 20 * MIN
RELEASE_AT = START + 70 * MIN


@pytest.fixture
async def database(database_url: str) -> AsyncIterator[Database]:
    name = f"kt_dash_{uuid7().hex[-12:]}"
    await _admin(database_url, f'CREATE DATABASE "{name}"')
    url = make_url(database_url).set(database=name).render_as_string(hide_password=False)
    db = Database(DatabaseSettings.model_validate({"url": url}), application_name="kt-tests")
    try:
        await migrate.upgrade(url)
        yield db
    finally:
        await db.dispose()
        await _admin(database_url, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


class Dashboard:
    """The dashboard as an operator's browser uses it: signed in, CSRF token in hand."""

    def __init__(self, database: Database, clock: FakeTime) -> None:
        app = create_app(
            Settings(_env_file=None, environment="test"),
            database,
            clock=clock,
            auth_settings=AuthSettings(
                _env_file=None,  # type: ignore[call-arg]
                session_secret=SECRET,  # type: ignore[arg-type]
                cookie_secure=False,
            ),
            passwords=cheap_passwords(),
        )
        self.http = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://dashboard.test"
        )
        self.csrf = ""

    async def sign_in(self, username: str) -> None:
        response = await self.http.post(
            f"{API_PREFIX}/auth/login", json={"username": username, "password": PASSWORD}
        )
        assert response.status_code == 200, response.text
        self.csrf = response.json()["csrf_token"]

    async def get(self, path: str, **params: Any) -> Any:
        response = await self.http.get(f"{API_PREFIX}{path}", params=params)
        assert response.status_code == 200, (path, response.status_code, response.text)
        return response.json()

    async def kill_switch(self, **body: Any) -> Any:
        response = await self.http.post(
            f"{API_PREFIX}/kill-switches", json=body, headers={"X-CSRF-Token": self.csrf}
        )
        assert response.status_code == 200, response.text
        return response.json()


async def test_the_dashboard_watches_and_halts_a_forward_session(database: Database) -> None:
    async with database.session() as session:
        await create_user(
            session,
            username="otto",
            password_hash=cheap_passwords().hash(PASSWORD),
            role=Role.OPERATOR,
            actor="test",
            now=START,
        )
    clock = FakeTime(START + timedelta(seconds=5))
    dashboard = Dashboard(database, clock)
    seen: dict[str, Any] = {}

    async def halt() -> None:
        await dashboard.sign_in("otto")
        seen["halted"] = await dashboard.kill_switch(
            scope="GLOBAL", active=True, reason="drill from the dashboard", close_positions=True
        )
        seen["overview_while_running"] = await dashboard.get("/overview")

    async def release() -> None:
        seen["released"] = await dashboard.kill_switch(
            scope="GLOBAL", active=False, reason="drill over", password=PASSWORD
        )

    clock.at(HALT_AT, halt)
    clock.at(RELEASE_AT, release)
    runtime = await run_runtime(database, clock, lab_config(), until=END)
    assert runtime.session is not None
    run_id = str(runtime.session.run_id)

    try:
        # ── while it ran ────────────────────────────────────────────────────
        assert seen["halted"]["active"] and seen["halted"]["close_positions"]
        assert seen["halted"]["changed_by_username"] == "otto"
        assert seen["released"]["active"] is False
        live = seen["overview_while_running"]
        assert live["global_halt"] is True
        assert live["runtime"]["present"] and not live["runtime"]["stale"]
        assert live["runtime"]["status"]["status"] == "running"
        # the runtime applies a switch at its next minute: not yet at the moment it was set
        assert live["runtime"]["status"]["kill_switch"]["global"] is False

        # ── the runtime's status document, as the overview shows it ─────────
        overview = await dashboard.get("/overview")
        status = overview["runtime"]["status"]
        assert status["status"] == "stopped" and status["error"] is None
        assert status["run_id"] == run_id
        assert status["last_batch_close"] == (END - MIN).isoformat().replace("+00:00", "Z")
        assert status["instruments"]["NEARUSD"]["provider"] == "fake-crypto"
        assert status["instruments"]["NEARUSD"]["state"] == "ok"
        assert status["instruments"]["XAUUSD"]["state"] == "closed"  # gold's daily break
        assert set(status["instances"]) == {"sma_gold", "breakout_near", "scripted_both"}
        assert overview["global_halt"] is False
        assert overview["forward"]["accounts"] == 3
        assert overview["recent_runs"][0]["id"] == run_id
        assert overview["recent_runs"][0]["kind"] == "FORWARD"

        # ── the leaderboard: one dedicated account per instance ─────────────
        board = await dashboard.get("/accounts", scope="forward", sort="net_pnl")
        accounts = {a["instance_id"]: a for a in board["items"]}
        assert set(accounts) == set(status["instances"])
        for instance, account in accounts.items():
            assert account["kind"] == "FORWARD"
            assert account["name"] == f"Paper 50K · {instance}"
            assert account["id"] == status["instances"][instance]["account_id"]
            assert account["runtime"]["state"] == "STOPPED"
            assert account["halted"] is False
        async with database.session() as session:
            trades = list(
                (
                    await session.scalars(
                        select(m.TradeRow).where(m.TradeRow.run_id == runtime.session.run_id)
                    )
                ).all()
            )
        assert trades
        for instance, account in accounts.items():
            closed = [
                t for t in trades if t.strategy_instance_id == instance and t.status == "CLOSED"
            ]
            summary = summarize_trades(closed)
            assert account["metrics"]["trades"] == summary.trades
            assert Decimal(account["metrics"]["net_pnl"]) == summary.net_pnl

        # ── what the kill switch did, as the trade and signal pages show it ─
        rejected = await dashboard.get("/signals", scope="forward", outcome="REJECTED")
        assert "KILL_SWITCH_ACTIVE" in {s["outcome_code"] for s in rejected["items"]}
        flattened = [
            t
            for t in (await dashboard.get("/trades", scope="forward", limit=500))["items"]
            if t["exit_reason"] == "KILL_SWITCH"
        ]
        assert flattened
        explained = await dashboard.get(f"/trades/{flattened[0]['id']}")
        assert "FLATTEN" in {o["purpose"] for o in explained["orders"]}
        assert explained["trade"]["exit_time"] >= HALT_AT.isoformat().replace("+00:00", "Z")

        history = (await dashboard.get("/kill-switches"))["history"]
        assert [e["action"] for e in reversed(history)] == [
            "killswitch.activate",
            "killswitch.applied",
            "killswitch.deactivate",
            "killswitch.applied",
        ]
        applied = [e for e in history if e["action"] == "killswitch.applied"]
        assert {e["scope"] for e in applied} == {"RUN"}
        assert {e["scope_id"] for e in applied} == {run_id}
        assert {e["actor_username"] for e in history if e["scope"] == "GLOBAL"} == {"otto"}

        # ── the chart: the candles log, aggregated, with every trade's markers ─
        chart = await dashboard.get("/candles", instrument="NEARUSD", timeframe="5m", limit=100)
        assert chart["source"] == "fake-crypto"
        assert chart["built_from"] == "1m"
        assert chart["candles"]
        first = datetime.fromisoformat(chart["candles"][0]["t"])
        near_trades = {
            str(t.id)
            for t in trades
            if t.instrument == "NEARUSD" and (t.exit_time is None or t.exit_time >= first)
        }
        assert {mk["trade_id"] for mk in chart["markers"]} == near_trades
        instrument = await dashboard.get("/instruments/NEARUSD")
        assert set(instrument["instances"]) == {"breakout_near", "scripted_both"}
        assert instrument["feed"]["provider"] == "fake-crypto"
    finally:
        await dashboard.http.aclose()
