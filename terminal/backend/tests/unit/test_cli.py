import json

import pytest
from typer.testing import CliRunner

from kterminal import __version__
from kterminal.cli import EXIT_CONFIG_ERROR, app
from kterminal.config.settings import LIVE_TRADING_ACKNOWLEDGEMENT

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.output.strip() == __version__


def test_config_check_passes_with_defaults() -> None:
    result = runner.invoke(app, ["config", "check"])
    assert result.exit_code == 0, result.output
    assert "default trading mode   : PAPER" in result.output
    assert "live trading permitted : no" in result.output


def test_config_check_rejects_live_default_without_echoing_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KT_TRADING__DEFAULT_MODE", "LIVE")
    monkeypatch.setenv("KT_TRADING__LIVE_ACKNOWLEDGEMENT", "my-typo-ack")
    result = runner.invoke(app, ["config", "check"])
    assert result.exit_code == EXIT_CONFIG_ERROR
    assert "trading.default_mode" in result.output
    assert "never be LIVE" in result.output
    assert "my-typo-ack" not in result.output


def test_config_check_flags_live_when_fully_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KT_TRADING__LIVE_ENABLED", "true")
    monkeypatch.setenv("KT_TRADING__LIVE_ACKNOWLEDGEMENT", LIVE_TRADING_ACKNOWLEDGEMENT)
    result = runner.invoke(app, ["config", "check"])
    assert result.exit_code == 0
    assert "YES — real money at risk" in result.output


def test_config_show_masks_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KT_DATABASE__URL", "postgresql://u:url-secret@db/x")
    monkeypatch.setenv("KT_DATABASE__PASSWORD", "field-secret")
    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0
    shown = json.loads(result.output)
    assert shown["database"]["url"] == "**********"
    assert "url-secret" not in result.output
    assert "field-secret" not in result.output


def test_missing_secret_file_exits_cleanly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KT_DATABASE__PASSWORD_FILE", "/nonexistent/secret")
    result = runner.invoke(app, ["config", "check"])
    assert result.exit_code == EXIT_CONFIG_ERROR
    assert "KT_DATABASE__PASSWORD_FILE" in result.output
