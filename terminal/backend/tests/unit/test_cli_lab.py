from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from kterminal.cli import EXIT_CONFIG_ERROR, app
from tests.fixtures.catalog import write_catalog_dir

runner = CliRunner()

LAB = {
    "defaults": {"account": {"starting_balance": 50000}},
    "instances": [
        {
            "id": "demo_sma_fast",
            "strategy": "demo_sma_cross",
            "params": {"fast": 9, "slow": 21},
            "instruments": ["XAUUSD"],
            "timeframe": "5m",
            "context_timeframes": ["15m", "1h"],
        },
        {
            "id": "demo_breakout_xau",
            "strategy": "demo_breakout",
            "instruments": ["XAUUSD"],
            "timeframe": "5m",
        },
    ],
}


@pytest.fixture
def config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    write_catalog_dir(tmp_path)
    (tmp_path / "lab.yaml").write_text(yaml.safe_dump(LAB))
    monkeypatch.setenv("KT_PATHS__CONFIG_DIR", str(tmp_path))
    return tmp_path


def test_catalog_validate(config_dir: Path) -> None:
    result = runner.invoke(app, ["catalog", "validate"])
    assert result.exit_code == 0, result.output
    assert "4 instruments" in result.output
    assert "catalog OK" in result.output


def test_catalog_validate_reports_every_problem(config_dir: Path) -> None:
    path = config_dir / "catalog" / "venue_profiles.yaml"
    path.write_text(path.read_text().replace("generic_mt5_cfd:XAUUSD", "nowhere:XAUUSD"))
    result = runner.invoke(app, ["catalog", "validate"])
    assert result.exit_code == EXIT_CONFIG_ERROR
    assert "unknown listing 'nowhere:XAUUSD'" in result.output


def test_catalog_show_and_resolve(config_dir: Path) -> None:
    shown = runner.invoke(app, ["catalog", "show", "MNQ1!"])
    assert shown.exit_code == 0, shown.output
    assert "MNQ — Micro E-mini Nasdaq-100" in shown.output
    assert "cme" in shown.output
    resolved = runner.invoke(app, ["catalog", "resolve", "BINANCE:NEARUSDT.P"])
    assert resolved.output.strip() == "NEARUSD"
    unknown = runner.invoke(app, ["catalog", "resolve", "XAUUSDX"])
    assert unknown.exit_code == 1
    assert "Did you mean" in unknown.output


def test_strategies_list(config_dir: Path) -> None:
    result = runner.invoke(app, ["strategies", "list"])
    assert result.exit_code == 0, result.output
    assert "demo_sma_cross" in result.output
    assert "demo_breakout_xau" in result.output
    assert "Paper 50K" in result.output


def test_lab_demo_in_memory(config_dir: Path) -> None:
    result = runner.invoke(app, ["lab", "demo", "--days", "3"])
    assert result.exit_code == 0, result.output
    assert "Paper 50K · demo_sma_fast" in result.output
    assert "Paper 50K · demo_breakout_xau" in result.output
    audit, _, solo = result.output.partition("Alone vs. together")
    assert audit.count("[OK ]") == 2  # isolation audit from the recorded rows
    assert solo.count("[OK ]") == 2  # each instance alone == alongside the other
    assert "identical" in solo
    assert "FAIL" not in result.output
