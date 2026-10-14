"""The paper / data / killswitch commands against PostgreSQL."""

import asyncio
from datetime import timedelta
from pathlib import Path

import pytest
import yaml
from sqlalchemy import func, select
from typer.testing import CliRunner

from kterminal.cli import app
from kterminal.db import models as m
from kterminal.db.locks import AdvisoryLock
from kterminal.db.session import Database
from kterminal.paper.config import LabConfig
from kterminal.paper.runtime import PAPER_RUNTIME_LOCK
from tests.fixtures.catalog import write_catalog_dir
from tests.fixtures.forward import FakeTime
from tests.integration.paper.forward_helpers import MIN, START, run_runtime

pytestmark = pytest.mark.integration

runner = CliRunner()

DEMO = LabConfig.model_validate(
    {
        "instances": [
            {
                "id": "sma_gold",
                "strategy": "demo_sma_cross",
                "params": {"fast": 3, "slow": 8},
                "instruments": ["XAUUSD"],
                "timeframe": "1m",
            },
            {
                "id": "breakout_near",
                "strategy": "demo_breakout",
                "params": {"channel_bars": 5, "trend_filter": False},
                "instruments": ["NEARUSD"],
                "timeframe": "5m",
            },
        ]
    }
)


@pytest.fixture
def config_dir(tmp_path: Path, fresh_url: str, monkeypatch: pytest.MonkeyPatch) -> Path:
    write_catalog_dir(tmp_path)
    (tmp_path / "lab.yaml").write_text(yaml.safe_dump(DEMO.model_dump(mode="json")))
    monkeypatch.setenv("KT_PATHS__CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("KT_DATABASE__URL", fresh_url)
    return tmp_path


async def invoke(*args: str) -> tuple[int, str]:
    """Run a command in a thread (it runs its own event loop, as from a shell)."""
    result = await asyncio.to_thread(runner.invoke, app, list(args))
    return result.exit_code, result.output


async def test_import_csv_loads_bars_into_the_candles_table(
    config_dir: Path, database: Database
) -> None:
    csv = config_dir / "gold.csv"
    csv.write_text(
        "time,open,high,low,close,volume\n"
        "2026-01-05T14:30:00Z,4000.10,4001.00,3999.50,4000.80,12\n"
        "1767623460,4000.80,4002.00,4000.00,4001.50,7\n"  # 14:31 UTC as Unix seconds
        "2026-01-05 09:32:00,4001.50,4001.60,4000.90,4001.00,\n",  # New York time (--tz)
        encoding="utf-8",
    )
    code, output = await invoke(
        "data", "import-csv", str(csv), "--instrument", "GOLD", "--source", "tv-export",
        "--tz", "America/New_York",
    )  # fmt: skip
    assert code == 0, output
    assert "XAUUSD 1m from tv-export: 3 bars" in output
    assert "3 inserted, 0 already stored" in output
    code, output = await invoke(
        "data", "import-csv", str(csv), "--instrument", "XAUUSD", "--source", "tv-export",
        "--tz", "America/New_York",
    )  # fmt: skip
    assert "0 inserted, 3 already stored" in output
    async with database.session() as session:
        stored = (await session.scalars(select(m.CandleRow).order_by(m.CandleRow.ts))).all()
    assert [(c.instrument, c.source, c.ts.isoformat()) for c in stored] == [
        ("XAUUSD", "tv-export", "2026-01-05T14:30:00+00:00"),
        ("XAUUSD", "tv-export", "2026-01-05T14:31:00+00:00"),
        ("XAUUSD", "tv-export", "2026-01-05T14:32:00+00:00"),
    ]
    bad = config_dir / "bad.csv"
    bad.write_text("time,open,high,low,close\n2026-01-05T14:30:30Z,1,1,1,1\n", encoding="utf-8")
    code, output = await invoke(
        "data", "import-csv", str(bad), "--instrument", "XAUUSD", "--source", "x"
    )
    assert code == 1 and "not on a 1m boundary" in output


async def test_kill_switch_commands_record_and_audit_every_change(
    config_dir: Path, database: Database
) -> None:
    clock = FakeTime(START + timedelta(seconds=5))
    await run_runtime(database, clock, DEMO, until=START + 3 * MIN)  # registers the instances

    code, output = await invoke("killswitch", "status")
    assert code == 0 and "no kill switch is active" in output
    code, output = await invoke("killswitch", "on", "--reason", "news spike", "--close-positions")
    assert code == 0, output
    assert "kill switch GLOBAL: ON — open positions will be closed at the next bar" in output
    code, output = await invoke(
        "killswitch", "on", "--scope", "strategy", "--id", "sma_gold", "--reason", "review"
    )
    assert code == 0 and "STRATEGY sma_gold: ON" in output
    code, output = await invoke(
        "killswitch", "on", "--scope", "strategy", "--id", "nope_x", "--reason", "x"
    )
    assert code == 1 and "unknown strategy instance 'nope_x'" in output
    code, output = await invoke(
        "killswitch", "on", "--scope", "account", "--id", "1", "--reason", "x"
    )
    assert code == 1 and "is not an account id" in output
    code, output = await invoke("killswitch", "status")
    assert "GLOBAL" in output and "ON  close positions by cli" in output
    assert "STRATEGY sma_gold" in output
    code, output = await invoke("killswitch", "off")
    assert code == 0 and "kill switch GLOBAL: off" in output

    async with database.session() as session:
        actions = (
            await session.scalars(
                select(m.AuditLogRow.action)
                .where(m.AuditLogRow.entity_type == "kill_switch")
                .order_by(m.AuditLogRow.seq)
            )
        ).all()
        active = await session.scalar(
            select(func.count()).select_from(m.KillSwitchRow).where(m.KillSwitchRow.active)
        )
    assert actions == ["killswitch.activate", "killswitch.activate", "killswitch.deactivate"]
    assert active == 1  # the strategy switch is still on


async def test_paper_sessions_and_status_show_the_session(
    config_dir: Path, database: Database
) -> None:
    code, output = await invoke("paper", "status")
    assert code == 0 and "Paper runtime: never started" in output
    clock = FakeTime(START + timedelta(seconds=5))
    runtime = await run_runtime(database, clock, DEMO, until=START + 10 * MIN)
    assert runtime.session is not None
    run_id = str(runtime.session.run_id)

    code, output = await invoke("paper", "sessions")
    assert code == 0, output
    assert run_id in output and "RUNNING" in output and "breakout_near, sma_gold" in output
    code, output = await invoke("paper", "status")
    assert code == 0, output
    assert (
        f"Paper runtime: stopped (updated {(START + 10 * MIN + timedelta(seconds=2)).isoformat()}"
        in output
    )
    assert f"Open session {run_id}" in output
    assert "Paper 50K · sma_gold" in output and "balance" in output
    assert "XAUUSD     fake-fx" in output


async def test_paper_start_refuses_a_changed_configuration_and_a_second_runtime(
    config_dir: Path, database: Database
) -> None:
    clock = FakeTime(START + timedelta(seconds=5))
    await run_runtime(database, clock, DEMO, until=START + 5 * MIN)
    changed = DEMO.model_dump(mode="json")
    changed["instances"][0]["params"]["fast"] = 4
    (config_dir / "lab.yaml").write_text(yaml.safe_dump(changed))
    code, output = await invoke("paper", "start")
    assert code == 1
    assert "sma_gold has a new strategy version" in output
    assert "kterminal paper start --new-session" in output

    lock = AdvisoryLock(database.engine, PAPER_RUNTIME_LOCK)
    assert await lock.try_acquire()
    try:
        code, output = await invoke("paper", "start", "--new-session")
        assert code == 1 and "already running" in output
    finally:
        await lock.release()
