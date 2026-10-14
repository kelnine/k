"""The ``csv`` provider: closed 1m bars from imported files."""

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from kterminal.core.clock import SimulatedClock
from kterminal.marketdata.base import MarketDataError, MarketDataProvider
from kterminal.marketdata.providers import CsvProvider

T0 = datetime(2026, 10, 9, 11, 50, tzinfo=UTC)
MINUTE = timedelta(minutes=1)


def export(path: Path, minutes: int) -> None:
    rows = [
        f"{int((T0 + i * MINUTE).timestamp())},{100 + i},{101 + i},{99 + i},{100.5 + i},{i}"
        for i in range(minutes)
    ]
    path.write_text("time,open,high,low,close,Volume\n" + "\n".join(rows) + "\n")


async def test_history_and_latest_serve_closed_bars_from_the_file(tmp_path: Path) -> None:
    export(tmp_path / "MNQ.csv", 11)  # 11:50 … 12:00, the last one still forming at 12:00:30
    clock = SimulatedClock(datetime(2026, 10, 9, 12, 0, 30, tzinfo=UTC))
    provider = CsvProvider.from_directory(tmp_path, ["MNQ"], clock=clock)
    assert isinstance(provider, MarketDataProvider)
    assert provider.supports("MNQ")
    assert not provider.supports("NQ")
    bars = await provider.history("MNQ", T0, T0 + 60 * MINUTE)
    assert [b.open_time for b in bars] == [T0 + i * MINUTE for i in range(10)]
    assert {b.source for b in bars} == {"csv"}
    latest = await provider.latest("MNQ", T0 + 8 * MINUTE)
    assert [b.open_time for b in latest] == [T0 + 8 * MINUTE, T0 + 9 * MINUTE]
    clock.set(datetime(2026, 10, 9, 12, 1, 5, tzinfo=UTC))
    assert (await provider.latest("MNQ", T0 + 10 * MINUTE))[0].open_time == T0 + 10 * MINUTE
    await provider.aclose()


async def test_a_replaced_file_is_read_again(tmp_path: Path) -> None:
    path = tmp_path / "MNQ.csv"
    export(path, 3)
    clock = SimulatedClock(datetime(2026, 10, 9, 13, 0, tzinfo=UTC))
    provider = CsvProvider({"MNQ": path}, clock=clock)
    assert len(await provider.history("MNQ", T0, T0 + 60 * MINUTE)) == 3
    export(path, 5)
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    assert len(await provider.history("MNQ", T0, T0 + 60 * MINUTE)) == 5


async def test_missing_and_invalid_files_are_market_data_errors(tmp_path: Path) -> None:
    provider = CsvProvider.from_directory(tmp_path, ["MNQ"])
    with pytest.raises(MarketDataError, match=r"MNQ\.csv does not exist"):
        await provider.history("MNQ", T0, T0 + MINUTE)
    (tmp_path / "MNQ.csv").write_text("time,open,high,low,close\nnot-a-time,1,1,1,1\n")
    with pytest.raises(MarketDataError, match=r"csv: .*unrecognised time"):
        await provider.history("MNQ", T0, T0 + MINUTE)
    with pytest.raises(MarketDataError, match="no file configured for NQ"):
        await provider.history("NQ", T0, T0 + MINUTE)
