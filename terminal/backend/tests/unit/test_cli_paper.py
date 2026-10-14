"""The paper CLI's status summary."""

from kterminal.cli import _format_runtime_status


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
