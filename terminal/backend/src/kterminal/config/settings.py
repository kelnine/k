"""Typed application settings.

All configuration comes from environment variables prefixed ``KT_`` with
``__`` separating nested groups, e.g. ``KT_DATABASE__URL`` or
``KT_TRADING__LIVE_ENABLED``. A local ``.env`` file is read for development.

Secrets are ``SecretStr`` (they print as ``**********``). In containers,
any variable may instead be supplied as a file: ``KT_DATABASE__PASSWORD_FILE=
/run/secrets/postgres_password`` sets ``KT_DATABASE__PASSWORD`` from that
file's contents (the Docker-secrets convention).

LIVE trading safety (interlocks 1-3 of docs/09-security.md §9.3):

1. ``trading.default_mode`` can never be ``LIVE``;
2. LIVE requires ``trading.live_enabled = true``; and
3. ``trading.live_acknowledgement`` must equal :data:`LIVE_TRADING_ACKNOWLEDGEMENT`.

An enabled-but-unacknowledged configuration is rejected at start-up rather
than silently treated as disabled, so a half-configured LIVE setup is noticed.
"""

import os
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from kterminal.core.enums import TradingMode

ENV_PREFIX = "KT_"
NESTED_DELIMITER = "__"
FILE_SUFFIX = "_FILE"

LIVE_TRADING_ACKNOWLEDGEMENT = "I UNDERSTAND THAT LIVE TRADING RISKS REAL MONEY"

# Default development credentials; refused in production.
_DEV_PASSWORD = "kterminal"  # noqa: S105 - documented local-development default, rejected in production


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class LogFormat(StrEnum):
    JSON = "json"
    CONSOLE = "console"


class DatabaseSettings(BaseModel):
    """PostgreSQL connection.

    ``url`` may omit the password; when ``password`` is set it replaces any password
    in the URL, so the URL can live in plain config while the password comes from a
    Docker secret (``KT_DATABASE__PASSWORD_FILE``).
    """

    url: SecretStr = SecretStr(
        f"postgresql+asyncpg://kterminal:{_DEV_PASSWORD}@localhost:5432/kterminal"
    )
    password: SecretStr | None = None
    pool_size: int = Field(default=10, ge=1, le=100)
    max_overflow: int = Field(default=5, ge=0, le=100)
    pool_timeout_s: float = Field(default=10.0, gt=0)
    connect_timeout_s: float = Field(default=5.0, gt=0)
    echo: bool = False

    @field_validator("url")
    @classmethod
    def _normalize_driver(cls, value: SecretStr) -> SecretStr:
        """Accept ``postgres://`` / ``postgresql://`` URLs and use the asyncpg driver."""
        try:
            url = make_url(value.get_secret_value())
        except ArgumentError:
            raise ValueError("database URL is not a valid SQLAlchemy URL") from None
        if url.get_backend_name() not in ("postgresql", "postgres"):
            raise ValueError("only PostgreSQL is supported")
        if url.drivername != "postgresql+asyncpg":
            url = url.set(drivername="postgresql+asyncpg")
        return SecretStr(url.render_as_string(hide_password=False))

    def dsn(self) -> str:
        """Full connection URL including the password. Never log this value."""
        url = make_url(self.url.get_secret_value())
        if self.password is not None and self.password.get_secret_value():
            url = url.set(password=self.password.get_secret_value())
        return url.render_as_string(hide_password=False)

    def effective_password(self) -> str | None:
        url = make_url(self.dsn())
        return url.password if isinstance(url.password, str) else None


class LoggingSettings(BaseModel):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    format: LogFormat = LogFormat.JSON


class ApiSettings(BaseModel):
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    docs_enabled: bool = True
    # Peers whose X-Forwarded-For / X-Forwarded-Proto headers are trusted (IPs or CIDRs):
    # only the reverse proxy. The webhook IP allow-list depends on this being correct.
    trusted_proxies: list[str] = Field(default_factory=lambda: ["127.0.0.1"])


class TradingSettings(BaseModel):
    default_mode: TradingMode = TradingMode.PAPER
    live_enabled: bool = False
    live_acknowledgement: str | None = None

    @field_validator("default_mode")
    @classmethod
    def _never_live_by_default(cls, value: TradingMode) -> TradingMode:
        if value is TradingMode.LIVE:
            raise ValueError(
                "default_mode may never be LIVE; LIVE must be enabled explicitly per account"
            )
        if value is TradingMode.BACKTEST:
            raise ValueError("default_mode must be PAPER or DEMO (BACKTEST accounts are ephemeral)")
        return value

    @model_validator(mode="after")
    def _live_requires_acknowledgement(self) -> "TradingSettings":
        if self.live_enabled and self.live_acknowledgement != LIVE_TRADING_ACKNOWLEDGEMENT:
            raise ValueError(
                "live_enabled=true requires live_acknowledgement to be exactly "
                f"{LIVE_TRADING_ACKNOWLEDGEMENT!r}"
            )
        return self

    @property
    def live_trading_permitted(self) -> bool:
        """Global LIVE interlocks satisfied. Per-account/strategy interlocks are checked later."""
        return self.live_enabled and self.live_acknowledgement == LIVE_TRADING_ACKNOWLEDGEMENT


class RuntimeSettings(BaseModel):
    """Long-running process roles (engine, worker)."""

    heartbeat_interval_s: float = Field(default=10.0, gt=0)
    leader_retry_interval_s: float = Field(default=5.0, gt=0)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        env_nested_delimiter=NESTED_DELIMITER,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    environment: Environment = Environment.DEVELOPMENT
    service_name: str = "kterminal"
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    api: ApiSettings = Field(default_factory=ApiSettings)
    trading: TradingSettings = Field(default_factory=TradingSettings)
    runtime: RuntimeSettings = Field(default_factory=RuntimeSettings)

    @model_validator(mode="after")
    def _production_safety(self) -> "Settings":
        if self.environment is not Environment.PRODUCTION:
            return self
        if self.database.effective_password() in (None, "", _DEV_PASSWORD):
            raise ValueError(
                "production requires a real database password (KT_DATABASE__PASSWORD[_FILE])"
            )
        if self.logging.format is not LogFormat.JSON:
            raise ValueError("production requires JSON logs (KT_LOGGING__FORMAT=json)")
        return self

    @property
    def is_production(self) -> bool:
        return self.environment is Environment.PRODUCTION

    @property
    def expose_api_docs(self) -> bool:
        return self.api.docs_enabled and not self.is_production

    def redacted(self) -> dict[str, Any]:
        """Settings as JSON-safe data with every secret masked — safe to print or log."""
        return self.model_dump(mode="json")


def _file_overrides(environ: dict[str, str]) -> dict[str, Any]:
    """Translate ``KT_X__Y_FILE=/path`` variables into nested init kwargs read from the files."""
    overrides: dict[str, Any] = {}
    for name, path in environ.items():
        upper = name.upper()
        if not (upper.startswith(ENV_PREFIX) and upper.endswith(FILE_SUFFIX)):
            continue
        field_path = upper[len(ENV_PREFIX) : -len(FILE_SUFFIX)].lower().split(NESTED_DELIMITER)
        if not all(field_path):
            continue
        try:
            value = Path(path).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise OSError(f"cannot read {name}={path!r}: {exc.strerror}") from None
        node = overrides
        for part in field_path[:-1]:
            node = node.setdefault(part, {})
        node[field_path[-1]] = value
    return overrides


def load_settings(*, env_file: str | Path | None = ".env", **overrides: Any) -> Settings:
    """Build :class:`Settings` from the environment, ``*_FILE`` secrets and explicit overrides.

    Precedence (highest first): ``overrides`` → ``*_FILE`` files → environment → ``.env``
    → defaults.
    """
    init: dict[str, Any] = _file_overrides(dict(os.environ))
    _deep_merge(init, overrides)
    return Settings(_env_file=env_file, **init)


def _deep_merge(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = value
