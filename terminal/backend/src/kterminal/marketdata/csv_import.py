"""Bars from CSV files: generic OHLCV files and TradingView chart exports.

Two layouts are read:

* **Generic** — a header naming ``time``, ``open``, ``high``, ``low``, ``close`` and
  optionally ``volume``, in any order and any letter case (``timestamp``, ``datetime``,
  ``date`` and ``open_time`` also name the time column, ``vol`` the volume). Other
  columns are ignored. :func:`write_bars_csv` writes this layout.
* **TradingView "Export chart data"** — ``time,open,high,low,close`` first, then
  ``Volume`` when the chart shows volume, then one column per plotted indicator series
  (titles may repeat; ``NaN`` where a series has no value). :func:`read_bars_csv` ignores
  the indicator columns; :func:`read_tradingview_export` returns them per bar for the
  parity harness.

Times are unix seconds (TradingView's default export format) or milliseconds, or
ISO 8601. ISO times with an offset or ``Z`` are exact; naive ISO times are read in the
``tz`` time zone and must be unambiguous there (a local time inside a DST change is an
error rather than a guess). One file uses one time format throughout.

Validation is strict and every error names the file and line: rows must be strictly
increasing in time with no duplicates or overlaps, times must sit on whole minutes and,
for timeframes up to 1h, on the timeframe's UTC grid (longer bars may be session-anchored,
so one step may be an hour short across a DST change); OHLC must be consistent and volume
non-negative. Missing minutes are **not** filled in. Volume left empty or ``NaN`` reads
as 0. A TradingView export taken while the market was open ends with the bar still
forming — export after the last wanted bar has closed, or drop it.
"""

import csv
import itertools
import os
import re
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from kterminal.domain.market import Bar
from kterminal.domain.timeframes import H1, Timeframe, TimeUnit

TIME_COLUMNS = ("time", "timestamp", "datetime", "date", "open_time")
PRICE_COLUMNS = ("open", "high", "low", "close")
VOLUME_COLUMNS = ("volume", "vol")
TRADINGVIEW_PREFIX = ("time", "open", "high", "low", "close")

_UNIX = re.compile(r"^(\d+)(?:\.0+)?$")
_MS_THRESHOLD = 10**11  # 1e11 s is the year 5138, 1e11 ms is 1973
_MAX_MS = 10**14
_MISSING = frozenset({"", "nan", "NaN", "NAN"})
_SPACING_MIN_ROWS = 10


class CsvImportError(ValueError):
    """A CSV file cannot be imported; the message names the file and line."""


@dataclass(frozen=True, slots=True)
class TradingViewExport:
    """A TradingView chart export: the bars and, per bar, the plotted series' values."""

    bars: tuple[Bar, ...]
    columns: tuple[str, ...]  # indicator columns in file order; repeats renamed "Plot (2)"
    extras: tuple[Mapping[str, Decimal | None], ...]  # aligned with ``bars``

    def series(self, column: str) -> list[Decimal | None]:
        if column not in self.columns:
            raise KeyError(f"no column {column!r} (columns: {', '.join(self.columns)})")
        return [row[column] for row in self.extras]


@dataclass(frozen=True, slots=True)
class _Layout:
    time: int
    prices: tuple[int, int, int, int]
    volume: int | None
    extras: tuple[tuple[int, str], ...]


def read_bars_csv(
    path: str | Path,
    instrument: str,
    *,
    source: str,
    timeframe: str | Timeframe = "1m",
    tz: str = "UTC",
) -> list[Bar]:
    """Read a generic OHLCV CSV or a TradingView chart export into bars, oldest first."""
    bars, _columns, _extras = _read(Path(path), instrument, source, timeframe, tz, False)
    return bars


def read_tradingview_export(
    path: str | Path,
    instrument: str | None = None,
    *,
    source: str = "tradingview",
    timeframe: str | Timeframe = "1m",
    tz: str = "UTC",
) -> TradingViewExport:
    """Read a TradingView "Export chart data" CSV: bars plus every indicator column.

    ``instrument`` names the bars. Without it they are named after the file up to its first
    comma (TradingView saves exports as ``<EXCHANGE>_<SYMBOL>, <interval>….csv``): a label
    such as ``OANDA_XAUUSD``, not a canonical instrument — pass the canonical one for bars
    that feed the lab.
    """
    file = Path(path)
    name = instrument if instrument is not None else _export_label(file)
    bars, columns, extras = _read(file, name, source, timeframe, tz, True)
    return TradingViewExport(bars=tuple(bars), columns=columns, extras=tuple(extras))


def _export_label(path: Path) -> str:
    return path.stem.split(",", 1)[0].strip() or path.stem


def write_bars_csv(path: str | Path, bars: Iterable[Bar]) -> int:
    """Write bars in the generic layout (ISO UTC times, exact decimals); return the count.

    The file is replaced atomically, so a failed write never leaves half a file.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    count = 0
    try:
        with os.fdopen(handle, "w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file, lineterminator="\n")
            writer.writerow(["time", "open", "high", "low", "close", "volume"])
            for bar in bars:
                writer.writerow(
                    [
                        bar.open_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        *(format(v, "f") for v in (bar.open, bar.high, bar.low, bar.close)),
                        format(bar.volume, "f"),
                    ]
                )
                count += 1
        Path(temporary).replace(target)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return count


# ── reading ──────────────────────────────────────────────────────────────────
def _read(
    path: Path,
    instrument: str,
    source: str,
    timeframe: str | Timeframe,
    tz: str,
    tradingview: bool,
) -> tuple[list[Bar], tuple[str, ...], list[dict[str, Decimal | None]]]:
    tf = _timeframe(timeframe, path)
    zone = _zone(tz, path)
    try:
        file = path.open(newline="", encoding="utf-8-sig")
    except OSError as exc:
        raise CsvImportError(f"{path}: cannot read: {exc.strerror}") from None
    with file:
        reader = csv.reader(file)
        try:
            header = next(reader, None)
            if header is None:
                raise CsvImportError(f"{path}: empty file")
            layout = _tradingview_layout(header, path) if tradingview else _layout(header, path)
            numbered = ((reader.line_num, row) for row in reader)
            return _rows(numbered, header, layout, path, instrument, source, tf, zone)
        except csv.Error as exc:
            raise CsvImportError(f"{path}:{reader.line_num}: malformed CSV: {exc}") from None
        except UnicodeDecodeError:
            raise CsvImportError(f"{path}: not UTF-8 text") from None


def _rows(
    rows: Iterable[tuple[int, list[str]]],
    header: Sequence[str],
    layout: _Layout,
    path: Path,
    instrument: str,
    source: str,
    tf: Timeframe,
    zone: tzinfo,
) -> tuple[list[Bar], tuple[str, ...], list[dict[str, Decimal | None]]]:
    bars: list[Bar] = []
    extras: list[dict[str, Decimal | None]] = []
    lines: list[int] = []
    time_format: str | None = None
    check_grid = tf.is_intraday and tf <= H1
    # Bars above 1h are often session-anchored (17:00 New York): a DST change moves them an
    # hour in UTC, so one step may be an hour short of the nominal length.
    overlap_tolerance = timedelta(0) if check_grid else timedelta(hours=1)
    for line, row in rows:
        if not any(cell.strip() for cell in row):
            continue
        where = f"{path}:{line}"
        if len(row) != len(header):
            raise CsvImportError(f"{where}: expected {len(header)} fields, got {len(row)}")
        open_time, kind = _parse_time(row[layout.time], zone, where)
        if time_format is None:
            time_format = kind
        elif kind != time_format:
            raise CsvImportError(
                f"{where}: time {row[layout.time]!r} is {kind}, earlier rows are {time_format}"
            )
        if open_time.second or open_time.microsecond:
            raise CsvImportError(f"{where}: time {open_time.isoformat()} is not on a whole minute")
        if check_grid and not tf.is_aligned(open_time):
            raise CsvImportError(f"{where}: time {open_time.isoformat()} is not on the {tf} grid")
        o, h, low, c = (
            _price(row[i], name, where)
            for i, name in zip(layout.prices, PRICE_COLUMNS, strict=True)
        )
        volume = _volume(row[layout.volume], where) if layout.volume is not None else Decimal(0)
        try:
            bar = Bar(
                instrument=instrument,
                timeframe=tf,
                open_time=open_time,
                close_time=open_time + tf.duration,
                open=o,
                high=h,
                low=low,
                close=c,
                volume=volume,
                source=source,
            )
        except ValueError as exc:
            raise CsvImportError(f"{where}: {exc}") from None
        if bars:
            previous = bars[-1]
            if open_time == previous.open_time:
                raise CsvImportError(
                    f"{where}: duplicate time {open_time.isoformat()} (also on line {lines[-1]})"
                )
            if open_time < previous.open_time:
                raise CsvImportError(
                    f"{where}: time {open_time.isoformat()} is before line {lines[-1]} "
                    f"({previous.open_time.isoformat()}); rows must be oldest first"
                )
            if open_time < previous.close_time - overlap_tolerance:
                raise CsvImportError(
                    f"{where}: bar at {open_time.isoformat()} overlaps the {tf} bar on line "
                    f"{lines[-1]}"
                )
        bars.append(bar)
        lines.append(line)
        extras.append({name: _optional(row[i], name, where) for i, name in layout.extras})
    _check_spacing(bars, tf, path)
    return bars, tuple(name for _, name in layout.extras), extras


def _check_spacing(bars: Sequence[Bar], tf: Timeframe, path: Path) -> None:
    """Catch a file of longer bars read as ``tf`` (e.g. a 5m export imported as 1m): with
    enough rows, some consecutive bars of a ``tf`` series are exactly ``tf`` apart."""
    if len(bars) < _SPACING_MIN_ROWS:
        return
    step = min(b.open_time - a.open_time for a, b in itertools.pairwise(bars))
    if step > tf.duration:
        raise CsvImportError(
            f"{path}: no two consecutive rows are {tf} apart (smallest step {step}); "
            "is the file a longer timeframe? pass that timeframe instead"
        )


def _layout(header: Sequence[str], path: Path) -> _Layout:
    names = [cell.strip().lower() for cell in header]

    def find(candidates: Sequence[str]) -> int | None:
        for candidate in candidates:  # in order of preference; first matching column wins
            if candidate in names:
                return names.index(candidate)
        return None

    found = {"time": find(TIME_COLUMNS), **{name: find((name,)) for name in PRICE_COLUMNS}}
    columns = {name: index for name, index in found.items() if index is not None}
    if len(columns) != len(found):
        missing = ", ".join(name for name in found if name not in columns)
        raise CsvImportError(
            f"{path}: header {','.join(header)!r} lacks {missing} "
            "(expected time,open,high,low,close[,volume])"
        )
    time = columns["time"]
    o, h, low, c = (columns[name] for name in PRICE_COLUMNS)
    volume = find(VOLUME_COLUMNS)
    return _Layout(time=time, prices=(o, h, low, c), volume=volume, extras=())  # others ignored


def _tradingview_layout(header: Sequence[str], path: Path) -> _Layout:
    names = [cell.strip().lower() for cell in header]
    if tuple(names[:5]) != TRADINGVIEW_PREFIX:
        raise CsvImportError(
            f"{path}: not a TradingView chart export (the header must start with "
            f"time,open,high,low,close; got {','.join(header[:5])!r})"
        )
    volume = 5 if len(names) > 5 and names[5] == "volume" else None
    first_extra = 5 if volume is None else 6
    extras = _unique([(i, header[i].strip()) for i in range(first_extra, len(header))])
    return _Layout(time=0, prices=(1, 2, 3, 4), volume=volume, extras=extras)


def _unique(columns: list[tuple[int, str]]) -> tuple[tuple[int, str], ...]:
    """Repeated column titles (two plots both called "Plot") become "Plot", "Plot (2)"."""
    seen: dict[str, int] = {}
    result = []
    for index, name in columns:
        label = name or f"column {index + 1}"
        seen[label] = seen.get(label, 0) + 1
        result.append((index, label if seen[label] == 1 else f"{label} ({seen[label]})"))
    return tuple(result)


def _timeframe(timeframe: str | Timeframe, path: Path) -> Timeframe:
    try:
        tf = Timeframe.parse(timeframe)
    except ValueError as exc:
        raise CsvImportError(f"{path}: {exc}") from None
    if tf.unit is TimeUnit.MONTH:
        raise CsvImportError(f"{path}: monthly bars have no fixed length and cannot be imported")
    return tf


def _zone(tz: str, path: Path) -> tzinfo:
    if tz.upper() == "UTC":
        return UTC
    try:
        return ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        raise CsvImportError(f"{path}: unknown time zone {tz!r}") from None


def _parse_time(text: str, zone: tzinfo, where: str) -> tuple[datetime, str]:
    raw = text.strip()
    if match := _UNIX.fullmatch(raw):
        value = int(match[1])
        if value >= _MAX_MS:
            raise CsvImportError(f"{where}: time {raw} is neither unix seconds nor milliseconds")
        if value >= _MS_THRESHOLD:
            if value % 1000:
                raise CsvImportError(f"{where}: time {raw} ms is not on a whole second")
            return datetime.fromtimestamp(value // 1000, tz=UTC), "unix milliseconds"
        return datetime.fromtimestamp(value, tz=UTC), "unix seconds"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        raise CsvImportError(
            f"{where}: unrecognised time {raw!r} (expected unix seconds/milliseconds or ISO 8601)"
        ) from None
    if parsed.tzinfo is None:
        parsed = _localize(parsed, zone, where)
    return parsed.astimezone(UTC), "ISO 8601"


def _localize(naive: datetime, zone: tzinfo, where: str) -> datetime:
    first = naive.replace(tzinfo=zone, fold=0)
    second = naive.replace(tzinfo=zone, fold=1)
    if first.utcoffset() == second.utcoffset():
        return first
    if first.astimezone(UTC).astimezone(zone).replace(tzinfo=None) != naive:
        problem = "does not exist (skipped by a DST change)"
    else:
        problem = "is ambiguous (repeated by a DST change)"
    raise CsvImportError(
        f"{where}: local time {naive.isoformat()} {problem} in {zone}; "
        "export unix times or times with an offset"
    )


def _price(text: str, name: str, where: str) -> Decimal:
    value = _number(text, name, where)
    if value is None:
        raise CsvImportError(f"{where}: {name} is missing")
    return value


def _volume(text: str, where: str) -> Decimal:
    value = _number(text, "volume", where)
    return Decimal(0) if value is None else value


def _optional(text: str, name: str, where: str) -> Decimal | None:
    return _number(text, name, where)


def _number(text: str, name: str, where: str) -> Decimal | None:
    raw = text.strip()
    if raw in _MISSING:
        return None
    try:
        value = Decimal(raw)
    except InvalidOperation:
        raise CsvImportError(f"{where}: {name} {raw!r} is not a number") from None
    if not value.is_finite():
        raise CsvImportError(f"{where}: {name} {raw!r} is not finite")
    return value


__all__ = [
    "CsvImportError",
    "TradingViewExport",
    "read_bars_csv",
    "read_tradingview_export",
    "write_bars_csv",
]
