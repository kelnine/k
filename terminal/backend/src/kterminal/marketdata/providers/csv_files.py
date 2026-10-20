"""The ``csv`` provider: bars from imported files, for instruments without a free 1m API.

Each instrument is one file, ``<csv_dir>/<INSTRUMENT>.csv`` (generic layout or a
TradingView chart export, read by :func:`~kterminal.marketdata.csv_import.read_bars_csv`).
Nothing is downloaded: ``latest`` only sees new bars when the file is replaced with a
newer export, so for live paper trading such an instrument is as fresh as its file.
A file is re-read only when its size or modification time changes.
"""

import asyncio
from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path

from kterminal.core.clock import Clock, SystemClock, ensure_utc
from kterminal.domain.market import Bar
from kterminal.domain.timeframes import M1
from kterminal.marketdata.base import MarketDataError
from kterminal.marketdata.csv_import import CsvImportError, read_bars_csv


class CsvProvider:
    """Serves closed 1m bars from one CSV file per canonical instrument."""

    name = "csv"

    def __init__(
        self,
        files: Mapping[str, Path],
        *,
        clock: Clock | None = None,
        close_delay_s: float = 2.0,
    ) -> None:
        self._files = dict(files)
        self._clock: Clock = clock or SystemClock()
        self._close_delay = timedelta(seconds=close_delay_s)
        self._cache: dict[str, tuple[tuple[int, int], list[Bar]]] = {}

    @classmethod
    def from_directory(
        cls,
        directory: Path,
        instruments: list[str],
        *,
        clock: Clock | None = None,
        close_delay_s: float = 2.0,
    ) -> "CsvProvider":
        files = {instrument: directory / f"{instrument}.csv" for instrument in instruments}
        return cls(files, clock=clock, close_delay_s=close_delay_s)

    def supports(self, instrument: str) -> bool:
        return instrument in self._files

    def path(self, instrument: str) -> Path:
        try:
            return self._files[instrument]
        except KeyError:
            raise MarketDataError(f"csv: no file configured for {instrument}") from None

    async def history(self, instrument: str, start: datetime, end: datetime) -> list[Bar]:
        start, end = ensure_utc(start), ensure_utc(end)
        closed_before = M1.floor(self._clock.now() - self._close_delay)
        bars = await self._bars(instrument)
        return [
            bar for bar in bars if start <= bar.open_time < end and bar.close_time <= closed_before
        ]

    async def latest(self, instrument: str, since: datetime) -> list[Bar]:
        return await self.history(instrument, since, self._clock.now())

    async def aclose(self) -> None:
        self._cache.clear()

    async def _bars(self, instrument: str) -> list[Bar]:
        path = self.path(instrument)
        try:
            stat = path.stat()
        except OSError:
            raise MarketDataError(
                f"csv: {path} does not exist (import 1m bars for {instrument} there)"
            ) from None
        key = (stat.st_size, stat.st_mtime_ns)
        cached = self._cache.get(instrument)
        if cached is not None and cached[0] == key:
            return cached[1]
        try:
            bars = await asyncio.to_thread(read_bars_csv, path, instrument, source=self.name)
        except CsvImportError as exc:
            raise MarketDataError(f"csv: {exc}") from None
        self._cache[instrument] = (key, bars)
        return bars


__all__ = ["CsvProvider"]
