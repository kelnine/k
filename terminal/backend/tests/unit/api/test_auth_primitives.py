"""Session tokens, CSRF tokens, sign-in limiting, password hashing and auth settings."""

import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from argon2.low_level import Type
from argon2.profiles import CHEAPEST
from pydantic import ValidationError

from kterminal.api.auth.limiter import LoginLimiter
from kterminal.api.auth.passwords import Passwords, password_problems
from kterminal.api.auth.settings import AuthSettings, load_auth_settings
from kterminal.api.auth.tokens import SessionSigner
from kterminal.api.auth.users import Role
from kterminal.core.ids import uuid7

T0 = datetime(2026, 10, 5, 14, 30, tzinfo=UTC)
SECRET = "s" * 40


@pytest.fixture
def signer() -> SessionSigner:
    return SessionSigner(SECRET, timedelta(hours=12))


def test_session_token_round_trip(signer: SessionSigner) -> None:
    user_id = uuid7()
    token, claims = signer.issue(user_id, "$argon2id$hash", T0)
    verified = signer.verify(token, T0 + timedelta(hours=11, minutes=59))
    assert verified == claims
    assert claims.user_id == user_id
    assert claims.expires_at == T0 + timedelta(hours=12)
    assert claims.password_tag == signer.password_tag("$argon2id$hash")
    assert "argon2" not in token  # the token carries a tag of the hash, never the hash


def test_session_tokens_expire(signer: SessionSigner) -> None:
    token, _ = signer.issue(uuid7(), "h", T0)
    assert signer.verify(token, T0 + timedelta(hours=12)) is None


def test_every_session_gets_its_own_id(signer: SessionSigner) -> None:
    user_id = uuid7()
    first = signer.issue(user_id, "h", T0)[1]
    second = signer.issue(user_id, "h", T0)[1]
    assert first.session_id != second.session_id


@pytest.mark.parametrize(
    "mangle",
    [
        lambda t: t[:-2] + ("AA" if not t.endswith("AA") else "BB"),  # signature
        lambda t: "v2" + t[2:],  # version
        lambda t: t + ".x",  # shape
        lambda t: "",
        lambda t: "v1." + "a" * 2000,
    ],
)
def test_tampered_tokens_are_refused(signer: SessionSigner, mangle: object) -> None:
    token, _ = signer.issue(uuid7(), "h", T0)
    assert signer.verify(mangle(token), T0) is None  # type: ignore[operator]


def test_claims_cannot_be_rewritten(signer: SessionSigner) -> None:
    token, _ = signer.issue(uuid7(), "h", T0)
    version, payload, signature = token.split(".")
    document = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    document["e"] += 10 * 86400  # extend the session
    forged = base64.urlsafe_b64encode(json.dumps(document).encode()).rstrip(b"=").decode()
    assert signer.verify(f"{version}.{forged}.{signature}", T0) is None


def test_a_different_secret_refuses_the_token(signer: SessionSigner) -> None:
    token, _ = signer.issue(uuid7(), "h", T0)
    assert SessionSigner("t" * 40, timedelta(hours=12)).verify(token, T0) is None


def test_short_secrets_are_refused() -> None:
    with pytest.raises(ValueError, match="at least 32"):
        SessionSigner("short", timedelta(hours=1))


def test_csrf_tokens_are_bound_to_the_session(signer: SessionSigner) -> None:
    csrf = signer.csrf_token("session-a")
    assert signer.csrf_valid("session-a", csrf)
    assert not signer.csrf_valid("session-b", csrf)
    assert not signer.csrf_valid("session-a", None)
    assert not signer.csrf_valid("session-a", "")
    assert not signer.csrf_valid("session-a", csrf + "x")


# ── sign-in limiting ─────────────────────────────────────────────────────────
def limiter() -> LoginLimiter:
    return LoginLimiter(max_failures=3, max_failures_per_ip=5, window=timedelta(minutes=15))


def test_a_username_locks_after_repeated_failures() -> None:
    gate = limiter()
    assert not gate.record_failure("Ada", "10.0.0.1", T0)
    assert not gate.record_failure("ada", "10.0.0.2", T0 + timedelta(minutes=1))
    assert gate.blocked_until("ada", "10.0.0.3", T0 + timedelta(minutes=2)) is None
    assert gate.record_failure(" ADA ", "10.0.0.3", T0 + timedelta(minutes=2))  # this one locks
    until = gate.blocked_until("ada", "10.0.0.9", T0 + timedelta(minutes=3))
    assert until == T0 + timedelta(minutes=17)
    assert gate.blocked_until("other", "10.0.0.9", T0 + timedelta(minutes=3)) is None
    assert gate.blocked_until("ada", "10.0.0.9", T0 + timedelta(minutes=17)) is None


def test_old_failures_are_forgotten() -> None:
    gate = limiter()
    gate.record_failure("ada", "ip", T0)
    gate.record_failure("ada", "ip", T0 + timedelta(minutes=1))
    assert not gate.record_failure("ada", "ip", T0 + timedelta(minutes=16))
    assert gate.blocked_until("ada", "ip", T0 + timedelta(minutes=16)) is None


def test_success_clears_the_username_but_not_the_address() -> None:
    gate = limiter()
    for minute in range(2):
        gate.record_failure("ada", "ip", T0 + timedelta(minutes=minute))
    gate.record_success("ADA")
    assert not gate.record_failure("ada", "ip", T0 + timedelta(minutes=3))
    assert len(gate._addresses["ip"]) == 3


def test_an_address_spraying_many_usernames_is_blocked() -> None:
    gate = limiter()
    for index in range(5):
        gate.record_failure(f"user{index}", "203.0.113.7", T0 + timedelta(seconds=index))
    assert gate.blocked_until("fresh", "203.0.113.7", T0 + timedelta(minutes=1)) == T0 + timedelta(
        minutes=15
    )
    assert gate.blocked_until("fresh", "198.51.100.1", T0 + timedelta(minutes=1)) is None


def test_tracked_keys_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("kterminal.api.auth.limiter.MAX_TRACKED_KEYS", 10)
    gate = limiter()
    for index in range(50):
        gate.record_failure(f"user{index}", f"ip{index}", T0 + timedelta(seconds=index))
    assert len(gate._users) <= 10
    assert len(gate._addresses) <= 10


# ── passwords ────────────────────────────────────────────────────────────────
def test_passwords_are_argon2id_and_verify() -> None:
    passwords = Passwords(PasswordHasher.from_parameters(CHEAPEST))
    stored = passwords.hash("a long passphrase 42")
    assert stored.startswith("$argon2id$")
    assert passwords.verify(stored, "a long passphrase 42")
    assert not passwords.verify(stored, "a long passphrase 43")
    assert not passwords.verify("not-a-hash", "anything")
    passwords.verify_decoy("anything")  # never raises


def test_weaker_hashes_need_a_rehash() -> None:
    cheap = Passwords(PasswordHasher.from_parameters(CHEAPEST))
    default = Passwords()
    stored = cheap.hash("a long passphrase 42")
    assert default.needs_rehash(stored)
    assert not cheap.needs_rehash(stored)
    assert default.needs_rehash("garbage")


def test_only_argon2id_is_accepted() -> None:
    with pytest.raises(ValueError, match="argon2id"):
        Passwords(PasswordHasher(type=Type.I))


@pytest.mark.parametrize(
    ("password", "problem"),
    [
        ("short", "at least 12"),
        (" leading space 123", "whitespace"),
        ("ada-the-admin-2026", "username"),
        ("aaaaaaaaaaaaaaaa", "5 different"),
    ],
)
def test_password_policy(password: str, problem: str) -> None:
    assert any(problem in p for p in password_problems(password, min_length=12, username="ada"))


def test_a_good_password_passes_the_policy() -> None:
    assert password_problems("correct horse battery", min_length=12, username="ada") == []


# ── roles and settings ───────────────────────────────────────────────────────
def test_roles_are_ordered() -> None:
    assert Role.ADMIN.allows(Role.OPERATOR)
    assert Role.OPERATOR.allows(Role.OPERATOR)
    assert Role.OPERATOR.allows(Role.VIEWER)
    assert not Role.VIEWER.allows(Role.OPERATOR)
    assert not Role.OPERATOR.allows(Role.ADMIN)


def test_auth_settings_defaults_are_safe() -> None:
    settings = AuthSettings(_env_file=None)  # type: ignore[call-arg]
    assert settings.cookie_secure is True
    assert settings.session_secret is None
    assert settings.max_failed_logins == 5


def test_short_session_secrets_are_refused() -> None:
    with pytest.raises(ValidationError, match="at least 32"):
        AuthSettings(_env_file=None, session_secret="too-short")  # type: ignore[call-arg]


def test_session_secret_from_a_docker_secret_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = tmp_path / "session_secret"
    secret.write_text("x" * 48 + "\n")
    monkeypatch.setenv("KT_AUTH__SESSION_SECRET_FILE", str(secret))
    monkeypatch.setenv("KT_AUTH__COOKIE_SECURE", "false")
    settings = load_auth_settings(env_file=None)
    assert settings.session_secret is not None
    assert settings.session_secret.get_secret_value() == "x" * 48
    assert settings.cookie_secure is False
    assert "x" * 48 not in repr(settings)


def test_an_unreadable_secret_file_is_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KT_AUTH__SESSION_SECRET_FILE", str(tmp_path / "missing"))
    with pytest.raises(OSError, match="KT_AUTH__SESSION_SECRET_FILE"):
        load_auth_settings(env_file=None)
