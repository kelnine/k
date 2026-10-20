"""Dashboard authentication settings (``KT_AUTH__*``).

Kept beside the code that uses them, read the same way as the application
settings: environment variables, the ``.env`` file, and Docker secrets through
``KT_AUTH__SESSION_SECRET_FILE``.

``session_secret`` signs session cookies and CSRF tokens. Without one the API
generates a random secret at start-up: that is secure, but every session ends
when the process restarts and several API replicas would not accept each
other's cookies, so production deployments should set it.

``local_no_login`` opens the dashboard without a sign-in for a single person on
their own computer: every visitor becomes the built-in ``local`` user. It is
refused unless ``published_address`` (where the dashboard's port is published,
``KT_BIND_ADDRESS`` in the Docker stack) is a loopback address, so a dashboard
reachable from other machines always asks for a password.
"""

import ipaddress
import os
from pathlib import Path
from typing import Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

AUTH_ENV_PREFIX = "KT_AUTH__"
SECRET_FILE_VARIABLE = f"{AUTH_ENV_PREFIX}SESSION_SECRET_FILE"
MIN_SECRET_LENGTH = 32


class AuthSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix=AUTH_ENV_PREFIX,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    session_secret: SecretStr | None = None
    # Absolute lifetime of a session; the user signs in again afterwards.
    session_ttl_minutes: int = Field(default=720, ge=5, le=7 * 24 * 60)
    # Send the cookie over HTTPS only. Production refuses false; a local
    # development setup on plain http://127.0.0.1 may turn it off.
    cookie_secure: bool = True
    # Consecutive failed sign-ins of one username before it is locked …
    max_failed_logins: int = Field(default=5, ge=1, le=100)
    # … for this long (failures older than this are forgotten).
    lockout_minutes: int = Field(default=15, ge=1, le=24 * 60)
    # Failed sign-ins from one client address within ``lockout_minutes`` (any usernames).
    max_failed_logins_per_ip: int = Field(default=30, ge=1, le=10_000)
    password_min_length: int = Field(default=12, ge=8, le=128)
    # No sign-in on this computer (see the module docstring); needs a loopback address.
    local_no_login: bool = False
    published_address: str | None = None

    @field_validator("session_secret")
    @classmethod
    def _long_enough(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and len(value.get_secret_value().strip()) < MIN_SECRET_LENGTH:
            raise ValueError(f"session_secret must be at least {MIN_SECRET_LENGTH} characters")
        return value

    @model_validator(mode="after")
    def _no_login_only_on_this_computer(self) -> Self:
        if self.local_no_login and not is_loopback(self.published_address):
            raise ValueError(
                "local_no_login (no sign-in) is allowed only for a dashboard published on this"
                " computer alone: KT_AUTH__PUBLISHED_ADDRESS must be a loopback address such as"
                " 127.0.0.1 (Docker: KT_BIND_ADDRESS). Turn it off (KT_LOCAL_NO_LOGIN=false) to"
                " publish the dashboard more widely."
            )
        return self


def is_loopback(address: str | None) -> bool:
    """True for ``localhost`` and loopback IP addresses (``127.0.0.1``, ``::1``, ``[::1]``)."""
    if address is None:
        return False
    text = address.strip().lower().removeprefix("[").removesuffix("]")
    if text == "localhost":
        return True
    try:
        return ipaddress.ip_address(text).is_loopback
    except ValueError:
        return False


def load_auth_settings(*, env_file: str | Path | None = ".env") -> AuthSettings:
    """Settings from the environment, ``.env`` and ``KT_AUTH__SESSION_SECRET_FILE``."""
    overrides: dict[str, object] = {}
    secret_file = os.environ.get(SECRET_FILE_VARIABLE)
    if secret_file:
        try:
            overrides["session_secret"] = Path(secret_file).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise OSError(
                f"cannot read {SECRET_FILE_VARIABLE}={secret_file!r}: {exc.strerror}"
            ) from None
    return AuthSettings(_env_file=env_file, **overrides)  # type: ignore[arg-type]
