"""The paper CLI's local helpers: the minimal CSV reader and the status summary."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from kterminal.cli import _format_runtime_status, _read_bars_csv


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "bars.csv"
    path.write_text(text, encoding="utf-8")
    return path


def test_the_csv_reader_accepts_iso_and_unix_times(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "Date,Open,High,Low,Close\n"
        "1767623520000,4001.5,4002,4001,4001.25\n"  # Unix milliseconds, 14:32 UTC
        "2026-01-05T14:30:00+00:00,4000.1,4001,3999.5,4000.8\n"
        "2026-01-05 15:31,4000.8,4002,4000,4001.5\n",  # local time (UTC+1 below)
    )
    bars = _read_bars_csv(path, "XAUUSD", source="tv", tz="Europe/Berlin")
    assert [b.open_time for b in bars] == [
        datetime(2026, 1, 5, 14, 30, tzinfo=UTC),
        datetime(2026, 1, 5, 14, 31, tzinfo=UTC),
        datetime(2026, 1, 5, 14, 32, tzinfo=UTC),
    ]
    assert bars[0].close == Decimal("4000.8") and bars[0].volume == 0
    assert {b.source for b in bars} == {"tv"}


@pytest.mark.parametrize(
    ("text", "error"),
    [
        ("open,high,low,close\n1,1,1,1\n", "needs a time column"),
        ("time,open,high,close\n2026-01-05T14:30:00Z,1,1,1\n", "missing: low"),
        ("time,open,high,low,close\n2026-01-05T14:30:10Z,1,1,1,1\n", "not on a 1m boundary"),
        ("time,open,high,low,close\n2026-01-05T14:30Z,1,0.5,1,1\n", "line 2: inconsistent OHLC"),
        ("time,open,high,low,close\n2026-01-05T14:30Z,x,1,1,1\n", "line 2"),
        (
            "time,open,high,low,close\n2026-01-05T14:30Z,1,1,1,1\n2026-01-05T14:30Z,1,1,1,1\n",
            "duplicate bar",
        ),
    ],
)
def test_the_csv_reader_reports_bad_rows(tmp_path: Path, text: str, error: str) -> None:
    with pytest.raises(ValueError, match=error):
        _read_bars_csv(write(tmp_path, text), "XAUUSD", source="tv")


def test_the_status_summary_lists_instruments_instances_and_switches() -> None:
    lines = _format_runtime_status(
        {
            "status": "running",
            "updated_at": "2026-01-05T14:31:02+00:00",
            "run_id": "r1",
            "last_batch_close": "2026-01-05T14:31:00+00:00",
            "instruments": {
                "XAUUSD": {
                    "provider": "oanda",
                    "state": "stale",
                    "last_bar_open": "2026-01-05T14:29:00+00:00",
                    "lag_seconds": 62.0,
                    "last_error": "MarketDataError: HTTP 503",
                }
            },
            "instances": {"sma": {"state": "FAULTED", "account_id": "a1", "fault": "Boom: x"}},
            "kill_switch": {"global": True, "accounts": [], "strategies": ["sma"]},
        }
    )
    text = "\n".join(lines)
    assert "Paper runtime: running" in text
    assert "kill switch: global ON; accounts —; strategies sma" in text
    assert "XAUUSD     oanda          stale" in text and "(MarketDataError: HTTP 503)" in text
    assert "FAULT Boom: x" in text
    assert _format_runtime_status(None) == ["Paper runtime: never started"]
