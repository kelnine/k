"""KT_AUTH__LOCAL_NO_LOGIN is accepted only for a dashboard published on a loopback address."""

# ruff: noqa: S104  (0.0.0.0 appears here as the address that must be refused)

import pytest
from pydantic import ValidationError

from kterminal.api.auth.settings import AuthSettings, is_loopback


@pytest.mark.parametrize(
    "address", ["127.0.0.1", "127.0.0.2", "::1", "[::1]", "localhost", " LOCALHOST "]
)
def test_loopback_addresses(address: str) -> None:
    assert is_loopback(address)


@pytest.mark.parametrize(
    "address",
    [None, "", "0.0.0.0", "::", "192.168.1.5", "10.0.0.1", "example.com", "localhost.example"],
)
def test_other_addresses(address: str | None) -> None:
    assert not is_loopback(address)


def test_off_by_default() -> None:
    assert AuthSettings(_env_file=None).local_no_login is False  # type: ignore[call-arg]


@pytest.mark.parametrize("address", ["127.0.0.1", "::1", "localhost"])
def test_accepted_on_a_loopback_address(address: str) -> None:
    settings = AuthSettings(_env_file=None, local_no_login=True, published_address=address)  # type: ignore[call-arg]
    assert settings.local_no_login


@pytest.mark.parametrize("address", [None, "0.0.0.0", "192.168.1.5"])
def test_refused_when_the_dashboard_is_published_more_widely(address: str | None) -> None:
    with pytest.raises(ValidationError, match="loopback"):
        AuthSettings(_env_file=None, local_no_login=True, published_address=address)  # type: ignore[call-arg]


def test_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KT_AUTH__LOCAL_NO_LOGIN", "true")
    monkeypatch.setenv("KT_AUTH__PUBLISHED_ADDRESS", "0.0.0.0")
    with pytest.raises(ValidationError, match="loopback"):
        AuthSettings(_env_file=None)  # type: ignore[call-arg]
    monkeypatch.setenv("KT_AUTH__PUBLISHED_ADDRESS", "127.0.0.1")
    assert AuthSettings(_env_file=None).local_no_login  # type: ignore[call-arg]
