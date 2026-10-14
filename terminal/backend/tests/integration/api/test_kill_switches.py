"""Kill switches from the dashboard: the row the runtime reads, the audit entry, re-auth."""

import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from kterminal.api.app import API_PREFIX
from kterminal.db import models as m
from kterminal.db.audit import verify
from tests.integration.api.conftest import demo_session, sign_in
from tests.integration.api.demo import PASSWORD, DemoData

pytestmark = pytest.mark.integration

URL = f"{API_PREFIX}/kill-switches"


@pytest.fixture
def operator(client: TestClient) -> tuple[TestClient, dict[str, str]]:
    csrf = sign_in(client, "otto")
    return client, {"X-CSRF-Token": csrf}


def stored(demo: DemoData, scope: str, scope_id: str) -> m.KillSwitchRow | None:
    async def read() -> m.KillSwitchRow | None:
        async with demo_session(demo) as session:
            return await session.get(m.KillSwitchRow, (scope, scope_id))

    return asyncio.run(read())


def audit_entries(demo: DemoData, entity_id: str) -> list[Any]:
    async def read() -> list[Any]:
        async with demo_session(demo) as session:
            result = await session.execute(
                select(m.AuditLogRow)
                .where(
                    m.AuditLogRow.entity_type == "kill_switch", m.AuditLogRow.entity_id == entity_id
                )
                .order_by(m.AuditLogRow.seq)
            )
            return list(result.scalars())

    return asyncio.run(read())


def test_an_operator_halts_and_releases_one_account(
    operator: tuple[TestClient, dict[str, str]], demo: DemoData
) -> None:
    client, csrf = operator
    account_id = str(demo.forward_accounts["demo_breakout_xau"])
    response = client.post(
        URL,
        json={
            "scope": "ACCOUNT",
            "scope_id": account_id,
            "active": True,
            "reason": "feed looks wrong",
            "close_positions": True,
        },
        headers=csrf,
    )
    assert response.status_code == 200, response.text
    switch = response.json()
    assert switch["active"] is True
    assert switch["label"] == "Paper 50K · demo_breakout_xau"
    assert switch["changed_by_username"] == "otto"
    assert switch["close_positions"] is True

    row = stored(demo, "ACCOUNT", account_id)
    assert row is not None and row.active and row.close_positions
    assert row.changed_by == f"user:{demo.user_ids['otto']}"
    assert row.reason == "feed looks wrong"

    accounts = {a["id"]: a for a in client.get(f"{API_PREFIX}/accounts").json()["items"]}
    assert accounts[account_id]["halted"] is True
    assert not accounts[str(demo.forward_accounts["demo_sma_fast"])]["halted"]
    detail = client.get(f"{API_PREFIX}/accounts/{account_id}").json()
    assert [s["scope"] for s in detail["kill_switches"]] == ["ACCOUNT"]
    overview = client.get(f"{API_PREFIX}/overview").json()
    assert [s["scope_id"] for s in overview["active_kill_switches"]] == [account_id]
    assert overview["global_halt"] is False

    # releasing re-enables trading: it needs the password again
    release = {"scope": "ACCOUNT", "scope_id": account_id, "active": False, "reason": "fixed"}
    refused = client.post(URL, json=release, headers=csrf)
    assert refused.status_code == 403
    assert refused.json()["code"] == "REAUTH_REQUIRED"
    wrong = client.post(URL, json={**release, "password": "not it"}, headers=csrf)
    assert wrong.status_code == 403
    released = client.post(URL, json={**release, "password": PASSWORD}, headers=csrf)
    assert released.status_code == 200
    assert released.json()["active"] is False
    assert released.json()["close_positions"] is False
    row = stored(demo, "ACCOUNT", account_id)
    assert row is not None and not row.active

    entries = audit_entries(demo, f"ACCOUNT:{account_id}")
    assert [e.action for e in entries] == ["killswitch.activate", "killswitch.release"]
    assert entries[0].data["username"] == "otto"
    assert entries[0].data["close_positions"] is True
    assert "password" not in str(entries[1].data)
    history = client.get(URL).json()["history"]
    assert history[0]["action"] == "killswitch.release"
    assert history[0]["scope_id"] == account_id

    async def chain_ok() -> bool:
        async with demo_session(demo) as session:
            return (await verify(session)).ok

    assert asyncio.run(chain_ok())


def test_global_and_strategy_switches(
    operator: tuple[TestClient, dict[str, str]], demo: DemoData
) -> None:
    client, csrf = operator
    on = client.post(
        URL, json={"scope": "GLOBAL", "active": True, "reason": "news spike"}, headers=csrf
    )
    assert on.status_code == 200
    assert on.json()["scope_id"] == "*"
    assert on.json()["label"] == "all trading"
    try:
        overview = client.get(f"{API_PREFIX}/overview").json()
        assert overview["global_halt"] is True
        leaderboard = client.get(f"{API_PREFIX}/accounts", params={"scope": "forward"}).json()
        assert all(a["halted"] for a in leaderboard["items"])
    finally:
        off = client.post(
            URL,
            json={"scope": "GLOBAL", "active": False, "reason": "calm", "password": PASSWORD},
            headers=csrf,
        )
        assert off.status_code == 200
    strategy = client.post(
        URL,
        json={"scope": "STRATEGY", "scope_id": "demo_sma_fast", "active": True, "reason": "review"},
        headers=csrf,
    )
    assert strategy.status_code == 200
    try:
        accounts = client.get(f"{API_PREFIX}/accounts").json()["items"]
        halted = {a["instance_id"] for a in accounts if a["halted"]}
        assert halted == {"demo_sma_fast"}  # its forward and its lab account
    finally:
        client.post(
            URL,
            json={
                "scope": "STRATEGY",
                "scope_id": "demo_sma_fast",
                "active": False,
                "reason": "done",
                "password": PASSWORD,
            },
            headers=csrf,
        )


@pytest.mark.parametrize(
    ("body", "status", "code"),
    [
        ({"scope": "ACCOUNT", "scope_id": "nope", "active": True, "reason": "x y z"}, 422, None),
        (
            {
                "scope": "ACCOUNT",
                "scope_id": "00000000-0000-0000-0000-000000000000",
                "active": True,
                "reason": "x y z",
            },
            404,
            "NOT_FOUND",
        ),
        ({"scope": "STRATEGY", "scope_id": "nope", "active": True, "reason": "x y z"}, 404, None),
        ({"scope": "BROKER", "active": True, "reason": "x y z"}, 422, None),
        ({"scope": "GLOBAL", "active": True, "reason": ""}, 422, None),
        ({"scope": "GLOBAL", "active": True, "reason": "ok", "extra": 1}, 422, None),
    ],
)
def test_invalid_requests_change_nothing(
    operator: tuple[TestClient, dict[str, str]],
    body: dict[str, Any],
    status: int,
    code: str | None,
) -> None:
    client, csrf = operator
    before = client.get(URL).json()["switches"]
    response = client.post(URL, json=body, headers=csrf)
    assert response.status_code == status, response.text
    if code:
        assert response.json()["code"] == code
    assert client.get(URL).json()["switches"] == before


def test_admins_operate_switches_too(client: TestClient) -> None:
    csrf = sign_in(client, "ada")
    response = client.post(
        URL,
        json={"scope": "STRATEGY", "scope_id": "demo_breakout_xau", "active": True, "reason": "a"},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 422  # reason too short: validation runs before anything
    response = client.post(
        URL,
        json={
            "scope": "STRATEGY",
            "scope_id": "demo_breakout_xau",
            "active": False,
            "reason": "admin release",
            "password": PASSWORD,
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 200
    assert response.json()["changed_by_username"] == "ada"
