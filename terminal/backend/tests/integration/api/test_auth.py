"""Sign-in, sessions, lockout, CSRF and roles against the real database."""

import asyncio
from collections.abc import Callable
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from kterminal.api.app import API_PREFIX
from kterminal.api.auth.service import SESSION_COOKIE
from kterminal.api.auth.users import change_password
from kterminal.core.clock import SimulatedClock
from kterminal.db.models import AuditLogRow
from tests.integration.api.conftest import demo_session, sign_in
from tests.integration.api.demo import PASSWORD, DemoData, cheap_passwords

pytestmark = pytest.mark.integration

LOGIN = f"{API_PREFIX}/auth/login"


def test_sign_in_sets_a_strict_http_only_cookie(
    make_client: Callable[..., TestClient],
) -> None:
    client = make_client(cookie_secure=True)
    response = client.post(LOGIN, json={"username": "vera", "password": PASSWORD})
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["username"] == "vera"
    assert body["user"]["role"] == "VIEWER"
    assert body["csrf_token"]
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{SESSION_COOKIE}=")
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie
    assert "Secure" in cookie
    assert "Path=/" in cookie
    assert "Max-Age=43200" in cookie
    assert response.headers["cache-control"] == "no-store"


def test_me_returns_the_user_and_csrf_token(client: TestClient) -> None:
    csrf = sign_in(client, "Vera")  # usernames are case-insensitive
    me = client.get(f"{API_PREFIX}/auth/me").json()
    assert me["user"]["username"] == "vera"
    assert me["csrf_token"] == csrf


@pytest.mark.parametrize(
    ("username", "password"),
    [("vera", "wrong password!"), ("nobody", PASSWORD), ("dora", PASSWORD)],
    ids=["wrong-password", "unknown-user", "disabled-user"],
)
def test_failed_sign_ins_look_alike(client: TestClient, username: str, password: str) -> None:
    response = client.post(LOGIN, json={"username": username, "password": password})
    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_CREDENTIALS"
    assert "set-cookie" not in response.headers


def test_sign_in_requires_json(client: TestClient) -> None:
    form = client.post(LOGIN, data={"username": "vera", "password": PASSWORD})
    assert form.status_code == 422  # a cross-site HTML form cannot sign anyone in
    extra = client.post(LOGIN, json={"username": "vera", "password": PASSWORD, "role": "ADMIN"})
    assert extra.status_code == 422


def test_repeated_failures_lock_the_username(
    make_client: Callable[..., TestClient], demo: DemoData
) -> None:
    clock = SimulatedClock(demo.now)
    client = make_client(clock=clock, max_failed_logins=3, lockout_minutes=10)
    for _ in range(3):
        assert client.post(LOGIN, json={"username": "otto", "password": "nope"}).status_code == 401
    locked = client.post(LOGIN, json={"username": "otto", "password": PASSWORD})
    assert locked.status_code == 429
    assert locked.json()["code"] == "LOGIN_LOCKED"
    assert 0 < int(locked.headers["retry-after"]) <= 600
    # another user is not affected
    assert client.post(LOGIN, json={"username": "vera", "password": PASSWORD}).status_code == 200
    # the lock expires
    clock.advance(timedelta(minutes=10, seconds=1))
    assert client.post(LOGIN, json={"username": "otto", "password": PASSWORD}).status_code == 200


def test_unknown_usernames_lock_too(make_client: Callable[..., TestClient]) -> None:
    client = make_client(max_failed_logins=2)
    for _ in range(2):
        client.post(LOGIN, json={"username": "ghost", "password": "x"})
    assert client.post(LOGIN, json={"username": "ghost", "password": "x"}).status_code == 429


def test_an_address_trying_many_usernames_is_blocked(
    make_client: Callable[..., TestClient],
) -> None:
    client = make_client(max_failed_logins_per_ip=4)
    for index in range(4):
        client.post(LOGIN, json={"username": f"spray{index}", "password": "x"})
    blocked = client.post(LOGIN, json={"username": "vera", "password": PASSWORD})
    assert blocked.status_code == 429


def test_a_successful_sign_in_resets_the_failure_count(
    make_client: Callable[..., TestClient],
) -> None:
    client = make_client(max_failed_logins=2)
    client.post(LOGIN, json={"username": "vera", "password": "nope"})
    sign_in(client, "vera")
    client.post(LOGIN, json={"username": "vera", "password": "nope"})
    assert client.post(LOGIN, json={"username": "vera", "password": PASSWORD}).status_code == 200


def test_every_dashboard_route_requires_a_session(client: TestClient) -> None:
    public = {f"{API_PREFIX}/auth/login"}
    placeholders = {
        "{account_id}": "00000000-0000-0000-0000-000000000000",
        "{trade_id}": "00000000-0000-0000-0000-000000000000",
        "{run_id}": "00000000-0000-0000-0000-000000000000",
        "{instance_id}": "x",
        "{symbol}": "XAUUSD",
    }
    checked = 0
    for template, operations in client.app.openapi()["paths"].items():  # type: ignore[attr-defined]
        if not template.startswith(API_PREFIX) or template in public:
            continue
        path = template
        for placeholder, value in placeholders.items():
            path = path.replace(placeholder, value)
        for method in operations:
            response = client.request(method.upper(), path, json={})
            assert response.status_code == 401, (method, path, response.status_code)
            checked += 1
    assert checked >= 20


def test_a_forged_cookie_is_refused(client: TestClient) -> None:
    client.cookies.set(SESSION_COOKIE, "v1.eyJ1IjoiYWRtaW4ifQ.c2lnbmF0dXJl")
    assert client.get(f"{API_PREFIX}/overview").status_code == 401


def test_sign_out_ends_the_session_everywhere(client: TestClient) -> None:
    csrf = sign_in(client, "vera")
    token = client.cookies.get(SESSION_COOKIE)
    assert client.get(f"{API_PREFIX}/overview").status_code == 200
    response = client.post(f"{API_PREFIX}/auth/logout", headers={"X-CSRF-Token": csrf})
    assert response.status_code == 204
    assert SESSION_COOKIE in response.headers["set-cookie"]
    # replaying the old cookie (e.g. from a stolen copy) does not work either
    assert token is not None
    client.cookies.set(SESSION_COOKIE, token)
    assert client.get(f"{API_PREFIX}/overview").status_code == 401


def test_state_changing_requests_need_the_csrf_token(client: TestClient) -> None:
    sign_in(client, "otto")
    body = {"scope": "GLOBAL", "active": True, "reason": "csrf test"}
    missing = client.post(f"{API_PREFIX}/kill-switches", json=body)
    assert missing.status_code == 403
    assert missing.json()["code"] == "CSRF_TOKEN_INVALID"
    wrong = client.post(
        f"{API_PREFIX}/kill-switches", json=body, headers={"X-CSRF-Token": "forged"}
    )
    assert wrong.status_code == 403
    logout = client.post(f"{API_PREFIX}/auth/logout")
    assert logout.status_code == 403
    assert client.get(f"{API_PREFIX}/kill-switches").status_code == 200  # reads need none


def test_the_csrf_token_of_another_session_is_refused(
    make_client: Callable[..., TestClient],
) -> None:
    other = make_client()
    foreign_csrf = sign_in(other, "otto")
    client = make_client()
    sign_in(client, "otto")
    response = client.post(
        f"{API_PREFIX}/kill-switches",
        json={"scope": "GLOBAL", "active": True, "reason": "foreign token"},
        headers={"X-CSRF-Token": foreign_csrf},
    )
    assert response.status_code == 403


def test_viewers_cannot_operate_kill_switches(client: TestClient) -> None:
    csrf = sign_in(client, "vera")
    response = client.post(
        f"{API_PREFIX}/kill-switches",
        json={"scope": "GLOBAL", "active": True, "reason": "viewer try"},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


def test_sessions_expire(make_client: Callable[..., TestClient], demo: DemoData) -> None:
    clock = SimulatedClock(demo.now)
    client = make_client(clock=clock, session_ttl_minutes=30)
    sign_in(client, "vera")
    clock.advance(timedelta(minutes=29))
    assert client.get(f"{API_PREFIX}/auth/me").status_code == 200
    clock.advance(timedelta(minutes=1))
    assert client.get(f"{API_PREFIX}/auth/me").status_code == 401


def test_a_password_change_ends_existing_sessions(
    make_client: Callable[..., TestClient], demo: DemoData
) -> None:
    client = make_client()
    sign_in(client, "ada")
    passwords = cheap_passwords()

    async def change(to: str) -> None:
        async with demo_session(demo) as session:
            await change_password(
                session, "ada", password_hash=passwords.hash(to), actor="test", now=demo.now
            )

    asyncio.run(change("a brand new passphrase"))
    try:
        assert client.get(f"{API_PREFIX}/auth/me").status_code == 401
        assert client.post(LOGIN, json={"username": "ada", "password": PASSWORD}).status_code == 401
        sign_in(client, "ada", "a brand new passphrase")
    finally:
        asyncio.run(change(PASSWORD))


def test_sign_ins_and_lockouts_are_audited(
    make_client: Callable[..., TestClient], demo: DemoData
) -> None:
    client = make_client(max_failed_logins=2)
    sign_in(client, "otto")
    for _ in range(2):
        client.post(LOGIN, json={"username": "audited-ghost", "password": "x"})

    async def entries() -> list[tuple[str, dict[str, object]]]:
        async with demo_session(demo) as session:
            rows = await session.execute(
                select(AuditLogRow.action, AuditLogRow.data).where(
                    AuditLogRow.action.in_(["auth.login", "auth.lockout"])
                )
            )
            return [(row.action, row.data) for row in rows]

    found = asyncio.run(entries())
    assert ("auth.lockout", {"username": "audited-ghost", "client": "testclient"}) in found
    assert any(a == "auth.login" and d["username"] == "otto" for a, d in found)
    assert not any("password" in str(d) for _, d in found)
