"""A dashboard without sign-in (KT_AUTH__LOCAL_NO_LOGIN) on this computer only."""

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from kterminal.api.app import API_PREFIX
from kterminal.api.auth.service import SESSION_COOKIE
from tests.integration.api.conftest import sign_in
from tests.integration.api.demo import PASSWORD, DemoData

pytestmark = pytest.mark.integration

LOCAL = f"{API_PREFIX}/auth/local"
OPTIONS = f"{API_PREFIX}/auth/options"
SWITCHES = f"{API_PREFIX}/kill-switches"
LOCALHOST = {"Host": "localhost"}


@pytest.fixture
def local_client(make_client: Callable[..., TestClient]) -> TestClient:
    return make_client(local_no_login=True, published_address="127.0.0.1")


def test_options_tell_the_dashboard_whether_to_sign_in(
    client: TestClient, local_client: TestClient
) -> None:
    assert client.get(OPTIONS).json() == {"local_no_login": False}
    assert local_client.get(OPTIONS).json() == {"local_no_login": True}


def test_without_the_setting_there_is_no_local_sign_in(client: TestClient) -> None:
    response = client.post(LOCAL, headers=LOCALHOST)
    assert response.status_code == 404
    assert "set-cookie" not in response.headers


def test_local_sign_in_opens_an_admin_session_for_the_built_in_user(
    local_client: TestClient,
) -> None:
    first = local_client.post(LOCAL, headers=LOCALHOST)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["local"] is True
    assert body["user"]["username"] == "local"
    assert body["user"]["role"] == "ADMIN"
    assert body["csrf_token"]
    cookie = first.headers["set-cookie"]
    assert cookie.startswith(f"{SESSION_COOKIE}=") and "HttpOnly" in cookie
    me = local_client.get(f"{API_PREFIX}/auth/me", headers=LOCALHOST).json()
    assert me["local"] is True and me["user"]["id"] == body["user"]["id"]
    # the next visit reuses the same user
    again = local_client.post(LOCAL, headers={"Host": "127.0.0.1:443"})
    assert again.status_code == 200
    assert again.json()["user"]["id"] == body["user"]["id"]


@pytest.mark.parametrize("host", ["evil.example", "192.168.1.20", "localhost.evil.example:443"])
def test_local_sign_in_answers_only_requests_addressed_to_this_computer(
    local_client: TestClient, host: str
) -> None:
    response = local_client.post(LOCAL, headers={"Host": host})
    assert response.status_code == 403
    assert response.json()["code"] == "LOCAL_ONLY"
    assert "set-cookie" not in response.headers


def test_the_local_user_cannot_sign_in_with_any_password(local_client: TestClient) -> None:
    assert local_client.post(LOCAL, headers=LOCALHOST).status_code == 200
    response = local_client.post(
        f"{API_PREFIX}/auth/login", json={"username": "local", "password": PASSWORD}
    )
    assert response.status_code == 401


def test_the_local_user_releases_a_kill_switch_without_a_password_but_with_csrf(
    local_client: TestClient, demo: DemoData
) -> None:
    csrf = local_client.post(LOCAL, headers=LOCALHOST).json()["csrf_token"]
    scope = {"scope": "STRATEGY", "scope_id": "demo_sma_fast"}
    halt = {**scope, "active": True, "reason": "local halt"}
    release = {**scope, "active": False, "reason": "local release"}
    # state changes still need the session's CSRF token (no cross-site requests)
    assert local_client.post(SWITCHES, json=halt, headers=LOCALHOST).status_code == 403
    headers = {**LOCALHOST, "X-CSRF-Token": csrf}
    assert local_client.post(SWITCHES, json=halt, headers=headers).status_code == 200
    released = local_client.post(SWITCHES, json=release, headers=headers)
    assert released.status_code == 200, released.text
    assert released.json()["active"] is False


def test_password_users_still_confirm_a_release_in_local_mode(local_client: TestClient) -> None:
    csrf = sign_in(local_client, "otto")
    scope = {"scope": "STRATEGY", "scope_id": "demo_sma_fast"}
    headers = {"X-CSRF-Token": csrf}
    halt = {**scope, "active": True, "reason": "operator halt"}
    assert local_client.post(SWITCHES, json=halt, headers=headers).status_code == 200
    release = {**scope, "active": False, "reason": "operator release"}
    refused = local_client.post(SWITCHES, json=release, headers=headers)
    assert refused.status_code == 403
    assert refused.json()["code"] == "REAUTH_REQUIRED"
    confirmed = local_client.post(SWITCHES, json={**release, "password": PASSWORD}, headers=headers)
    assert confirmed.status_code == 200, confirmed.text
