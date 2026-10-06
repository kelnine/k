from pathlib import Path

import pytest
from pydantic import ValidationError

from kterminal.config.settings import (
    LIVE_TRADING_ACKNOWLEDGEMENT,
    Environment,
    LogFormat,
    Settings,
    load_settings,
)
from kterminal.core.enums import TradingMode


def make(**kwargs: object) -> Settings:
    return Settings(_env_file=None, **kwargs)  # type: ignore[arg-type]


# ── LIVE-trading interlocks ────────────────────────────────────────────────
def test_defaults_are_paper_and_live_disabled() -> None:
    settings = make()
    assert settings.trading.default_mode is TradingMode.PAPER
    assert settings.trading.live_enabled is False
    assert settings.trading.live_trading_permitted is False


def test_live_can_never_be_the_default_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KT_TRADING__DEFAULT_MODE", "LIVE")
    with pytest.raises(ValidationError, match="default_mode may never be LIVE"):
        make()


def test_live_cannot_be_default_even_with_full_acknowledgement() -> None:
    with pytest.raises(ValidationError, match="never be LIVE"):
        make(
            trading={
                "default_mode": "LIVE",
                "live_enabled": True,
                "live_acknowledgement": LIVE_TRADING_ACKNOWLEDGEMENT,
            }
        )


def test_backtest_is_not_a_valid_default_mode() -> None:
    with pytest.raises(ValidationError, match="PAPER or DEMO"):
        make(trading={"default_mode": "BACKTEST"})


@pytest.mark.parametrize("ack", [None, "", "yes", LIVE_TRADING_ACKNOWLEDGEMENT.lower()])
def test_enabling_live_requires_the_exact_acknowledgement(ack: str | None) -> None:
    with pytest.raises(ValidationError, match="live_acknowledgement"):
        make(trading={"live_enabled": True, "live_acknowledgement": ack})


def test_live_permitted_only_with_switch_and_acknowledgement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KT_TRADING__LIVE_ENABLED", "true")
    monkeypatch.setenv("KT_TRADING__LIVE_ACKNOWLEDGEMENT", LIVE_TRADING_ACKNOWLEDGEMENT)
    settings = make()
    assert settings.trading.live_trading_permitted is True
    assert settings.trading.default_mode is TradingMode.PAPER  # still not the default


def test_acknowledgement_alone_does_not_enable_live() -> None:
    settings = make(trading={"live_acknowledgement": LIVE_TRADING_ACKNOWLEDGEMENT})
    assert settings.trading.live_trading_permitted is False


# ── environment parsing ─────────────────────────────────────────────────────
def test_nested_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KT_ENVIRONMENT", "staging")
    monkeypatch.setenv("KT_API__PORT", "9001")
    monkeypatch.setenv("KT_LOGGING__FORMAT", "console")
    monkeypatch.setenv("KT_TRADING__DEFAULT_MODE", "DEMO")
    settings = make()
    assert settings.environment is Environment.STAGING
    assert settings.api.port == 9001
    assert settings.logging.format is LogFormat.CONSOLE
    assert settings.trading.default_mode is TradingMode.DEMO


def test_dotenv_file_is_read(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("KT_API__PORT=8123\n")
    assert load_settings(env_file=env_file).api.port == 8123


def test_file_secrets_convention(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    secret = tmp_path / "postgres_password"
    secret.write_text("s3cr3t-from-docker\n")
    monkeypatch.setenv("KT_DATABASE__URL", "postgresql://kterminal@db:5432/kterminal")
    monkeypatch.setenv("KT_DATABASE__PASSWORD_FILE", str(secret))
    settings = load_settings(env_file=None)
    assert settings.database.password is not None
    assert settings.database.password.get_secret_value() == "s3cr3t-from-docker"
    assert (
        settings.database.dsn()
        == "postgresql+asyncpg://kterminal:s3cr3t-from-docker@db:5432/kterminal"
    )


def test_missing_secret_file_is_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KT_DATABASE__PASSWORD_FILE", "/nonexistent/secret")
    with pytest.raises(OSError, match="KT_DATABASE__PASSWORD_FILE"):
        load_settings(env_file=None)


def test_explicit_overrides_win(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KT_API__PORT", "9001")
    assert load_settings(env_file=None, api={"port": 9002}).api.port == 9002


# ── database URL handling ───────────────────────────────────────────────────
@pytest.mark.parametrize(
    "url",
    [
        "postgres://u:p@h:5432/d",
        "postgresql://u:p@h:5432/d",
        "postgresql+psycopg://u:p@h:5432/d",
        "postgresql+asyncpg://u:p@h:5432/d",
    ],
)
def test_database_url_uses_asyncpg(url: str) -> None:
    assert make(database={"url": url}).database.dsn() == "postgresql+asyncpg://u:p@h:5432/d"


def test_non_postgres_databases_are_rejected() -> None:
    with pytest.raises(ValidationError, match="only PostgreSQL"):
        make(database={"url": "sqlite+aiosqlite:///x.db"})


def test_password_field_overrides_url_password() -> None:
    settings = make(database={"url": "postgresql://u:old@h/d", "password": "new"})
    assert settings.database.dsn() == "postgresql+asyncpg://u:new@h/d"


# ── production guard rails ──────────────────────────────────────────────────
def test_production_refuses_default_database_password() -> None:
    with pytest.raises(ValidationError, match="real database password"):
        make(environment="production")


def test_production_requires_json_logs() -> None:
    with pytest.raises(ValidationError, match="JSON logs"):
        make(
            environment="production",
            database={"password": "a-real-password"},
            logging={"format": "console"},
        )


def test_production_hides_api_docs() -> None:
    settings = make(environment="production", database={"password": "a-real-password"})
    assert settings.is_production
    assert settings.expose_api_docs is False
    assert make().expose_api_docs is True


# ── secrets never leak ──────────────────────────────────────────────────────
def test_redacted_dump_and_repr_hide_secrets() -> None:
    settings = make(database={"url": "postgresql://u:url-pass@h/d", "password": "field-pass"})
    dumped = str(settings.redacted())
    for text in (dumped, repr(settings), str(settings)):
        assert "url-pass" not in text
        assert "field-pass" not in text
