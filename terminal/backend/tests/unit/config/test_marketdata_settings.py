"""The ``marketdata`` settings section (KT_MARKETDATA__*)."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from kterminal.config.settings import OandaEnvironment, Settings, load_settings


def test_defaults_are_read_only_practice_without_credentials() -> None:
    md = Settings(_env_file=None).marketdata
    assert md.oanda_token is None
    assert md.oanda_configured is False
    assert md.oanda_environment is OandaEnvironment.PRACTICE
    assert md.disabled_providers == []
    assert md.base_urls == {}
    assert md.csv_dir is None
    assert md.sources_file is None
    assert (md.request_timeout_s, md.max_retries, md.close_delay_s) == (10.0, 5, 2.0)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("binance_usdm,bybit_linear", ["binance_usdm", "bybit_linear"]),
        (" binance_usdm , ", ["binance_usdm"]),
        ('["coinbase"]', ["coinbase"]),
        ("", []),
    ],
)
def test_disabled_providers_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, raw: str, expected: list[str]
) -> None:
    monkeypatch.setenv("KT_MARKETDATA__DISABLED_PROVIDERS", raw)
    assert load_settings(env_file=None).marketdata.disabled_providers == expected


def test_the_oanda_token_comes_from_a_secret_file_and_is_masked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    secret = tmp_path / "oanda_token"
    secret.write_text("abc-123-token\n")
    monkeypatch.setenv("KT_MARKETDATA__OANDA_TOKEN_FILE", str(secret))
    monkeypatch.setenv("KT_MARKETDATA__OANDA_ENVIRONMENT", "live")
    monkeypatch.setenv("KT_MARKETDATA__BASE_URLS", '{"binance_spot": "https://data.example"}')
    settings = load_settings(env_file=None)
    md = settings.marketdata
    assert md.oanda_token is not None
    assert md.oanda_token.get_secret_value() == "abc-123-token"
    assert md.oanda_configured
    assert md.oanda_environment is OandaEnvironment.LIVE
    assert md.base_urls == {"binance_spot": "https://data.example"}
    shown = settings.redacted()["marketdata"]
    assert shown["oanda_token"] == "**********"
    assert "abc-123-token" not in repr(settings)
    # reading prices from OANDA's live host has nothing to do with LIVE trading
    assert settings.trading.live_trading_permitted is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"oanda_environment": "production"},
        {"request_timeout_s": 0},
        {"max_retries": -1},
        {"close_delay_s": 120},
    ],
)
def test_invalid_values_are_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, marketdata=overrides)  # type: ignore[arg-type]
