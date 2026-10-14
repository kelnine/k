"""Reading and writing bar CSV files: generic OHLCV and TradingView chart exports."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from kterminal.domain.market import Bar
from kterminal.domain.timeframes import M1, M5, Timeframe
from kterminal.marketdata.csv_import import (
    CsvImportError,
    read_bars_csv,
    read_tradingview_export,
    write_bars_csv,
)

T0 = datetime(2026, 10, 5, 13, 30, tzinfo=UTC)
U0 = int(T0.timestamp())

# A TradingView "Export chart data" file (UNIX time format) of a 1m chart with volume and
# three plotted series — two of them both titled "Plot" — and an na value.
TRADINGVIEW = f"""time,open,high,low,close,Volume,Plot,Plot,EMA 200
{U0},20100.25,20101.00,20099.75,20100.50,1520,20100.1,NaN,20090.123456
{U0 + 60},20100.50,20102.25,20100.00,20102.00,1834,20100.9,1,20090.2
{U0 + 120},20102.00,20102.50,20101.25,20101.50,1101,20101.2,2,20090.31
"""


def write(tmp_path: Path, text: str, name: str = "bars.csv") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def read(path: Path, **kwargs: object) -> list[Bar]:
    return read_bars_csv(path, "MNQ", source="tradingview", **kwargs)  # type: ignore[arg-type]


# ── TradingView exports ──────────────────────────────────────────────────────
def test_tradingview_export_reads_bars_and_every_plotted_series(tmp_path: Path) -> None:
    export = read_tradingview_export(write(tmp_path, TRADINGVIEW), "MNQ")
    assert [b.open_time for b in export.bars] == [
        T0,
        T0 + timedelta(minutes=1),
        T0 + timedelta(minutes=2),
    ]
    first = export.bars[0]
    assert (first.open, first.high, first.low, first.close, first.volume) == (
        Decimal("20100.25"),
        Decimal("20101.00"),
        Decimal("20099.75"),
        Decimal("20100.50"),
        Decimal(1520),
    )
    assert first.source == "tradingview"
    assert first.timeframe == M1
    assert first.close_time == T0 + timedelta(minutes=1)
    assert export.columns == ("Plot", "Plot (2)", "EMA 200")
    assert export.extras[0] == {
        "Plot": Decimal("20100.1"),
        "Plot (2)": None,
        "EMA 200": Decimal("20090.123456"),
    }
    assert export.series("Plot (2)") == [None, Decimal(1), Decimal(2)]
    with pytest.raises(KeyError, match="no column 'RSI'"):
        export.series("RSI")


def test_read_bars_csv_ignores_the_indicator_columns(tmp_path: Path) -> None:
    path = write(tmp_path, TRADINGVIEW)
    assert read(path) == list(read_tradingview_export(path, "MNQ").bars)


def test_tradingview_export_without_volume_and_with_a_bom(tmp_path: Path) -> None:
    text = f"﻿time,open,high,low,close,Basis\n{U0},1.1,1.2,1.0,1.15,1.12\n"
    export = read_tradingview_export(write(tmp_path, text), "EURUSD", source="tv")
    assert export.bars[0].volume == 0
    assert export.bars[0].source == "tv"
    assert export.columns == ("Basis",)


def test_tradingview_export_with_iso_times_in_the_exchange_zone(tmp_path: Path) -> None:
    text = "time,open,high,low,close\n2026-10-05T09:30:00-04:00,1,2,0.5,1.5\n"
    (bar,) = read_tradingview_export(write(tmp_path, text), "MNQ").bars
    assert bar.open_time == T0


def test_tradingview_export_without_an_instrument_is_named_after_the_file(
    tmp_path: Path,
) -> None:
    export = read_tradingview_export(write(tmp_path, TRADINGVIEW, "CME_MINI_MNQ1!, 1_a1b2c.csv"))
    assert {b.instrument for b in export.bars} == {"CME_MINI_MNQ1!"}
    assert len(export.extras) == len(export.bars) == 3
    plain = read_tradingview_export(write(tmp_path, TRADINGVIEW, "mnq.csv"))
    assert plain.bars[0].instrument == "mnq"


def test_a_generic_file_is_not_a_tradingview_export(tmp_path: Path) -> None:
    path = write(tmp_path, "timestamp,open,high,low,close\n")
    with pytest.raises(CsvImportError, match="not a TradingView chart export"):
        read_tradingview_export(path, "MNQ")


# ── generic files ────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "time",
    [
        str(U0),
        str(U0 * 1000),
        f"{U0}.0",
        "2026-10-05T13:30:00Z",
        "2026-10-05 13:30:00",
        "2026-10-05T13:30:00.000+00:00",
        "2026-10-05T15:30:00+02:00",
    ],
)
def test_generic_time_formats(tmp_path: Path, time: str) -> None:
    (bar,) = read(write(tmp_path, f"time,open,high,low,close,volume\n{time},1,2,0.5,1.5,7\n"))
    assert bar.open_time == T0


def test_generic_header_any_order_and_case_with_extra_columns(tmp_path: Path) -> None:
    text = (
        "Symbol,Close,Volume,Low,High,Open,Timestamp\n"
        f"MNQ,1.5,3.25,0.5,2,1,{U0}\n"
        f"MNQ,1.6,,0.5,2,1.5,{U0 + 60}\n"
    )
    bars = read(write(tmp_path, text))
    assert [(b.open, b.high, b.low, b.close, b.volume) for b in bars] == [
        (Decimal(1), Decimal(2), Decimal("0.5"), Decimal("1.5"), Decimal("3.25")),
        (Decimal("1.5"), Decimal(2), Decimal("0.5"), Decimal("1.6"), Decimal(0)),
    ]


def test_naive_iso_times_are_read_in_the_given_zone(tmp_path: Path) -> None:
    path = write(tmp_path, "time,open,high,low,close\n2026-10-05 09:30,1,2,0.5,1.5\n")
    (bar,) = read(path, tz="America/New_York")
    assert bar.open_time == T0


@pytest.mark.parametrize(
    ("local", "problem"),
    [
        ("2026-11-01 01:30", "is ambiguous"),  # New York falls back: 01:30 happens twice
        ("2026-03-08 02:30", "does not exist"),  # spring forward: 02:30 is skipped
    ],
)
def test_local_times_inside_a_dst_change_are_refused(
    tmp_path: Path, local: str, problem: str
) -> None:
    path = write(tmp_path, f"time,open,high,low,close\n{local},1,2,0.5,1.5\n")
    with pytest.raises(CsvImportError, match=problem):
        read(path, tz="America/New_York")


def test_other_timeframes(tmp_path: Path) -> None:
    rows = "".join(f"{U0 + i * 300},1,2,0.5,1.5\n" for i in range(3))
    bars = read(write(tmp_path, "time,open,high,low,close\n" + rows), timeframe="5m")
    assert [b.timeframe for b in bars] == [M5] * 3
    assert bars[0].close_time == T0 + timedelta(minutes=5)
    daily = read(
        write(tmp_path, "time,open,high,low,close\n2026-10-05,1,2,0.5,1.5\n", "d.csv"),
        timeframe="1D",
    )
    assert daily[0].close_time - daily[0].open_time == timedelta(days=1)


def test_gaps_are_kept(tmp_path: Path) -> None:
    rows = "".join(f"{U0 + i * 60},1,2,0.5,1.5\n" for i in (0, 1, 5, 6))
    bars = read(write(tmp_path, "time,open,high,low,close\n" + rows))
    assert [int((b.open_time - T0).total_seconds() // 60) for b in bars] == [0, 1, 5, 6]


def test_blank_lines_are_skipped(tmp_path: Path) -> None:
    text = f"time,open,high,low,close\n\n{U0},1,2,0.5,1.5\n,,,,\n"
    assert len(read(write(tmp_path, text))) == 1


# ── errors name the file and line ────────────────────────────────────────────
HEADER = "time,open,high,low,close,volume\n"


def row(
    time: object, o: str = "1", h: str = "2", low: str = "0.5", c: str = "1.5", v: str = "1"
) -> str:
    return f"{time},{o},{h},{low},{c},{v}\n"


@pytest.mark.parametrize(
    ("rows", "problem"),
    [
        (row(U0) + row(U0), r":3: duplicate time 2026-10-05T13:30:00\+00:00 \(also on line 2\)"),
        (row(U0 + 60) + row(U0), r":3: time .* is before line 2 .*oldest first"),
        (row(U0, h="0.9"), r":2: inconsistent OHLC"),
        (row(U0, v="-1"), r":2: bar volume cannot be negative"),
        (row(U0, o=""), r":2: open is missing"),
        (row(U0, low="NaN"), r":2: low is missing"),
        (row(U0, c="1.5x"), r":2: close '1.5x' is not a number"),
        (row(U0, c="Infinity"), r":2: close 'Infinity' is not finite"),
        (f"{U0},1,2,0.5,1.5\n", r":2: expected 6 fields, got 5"),
        (row(U0 + 30), r"is not on a whole minute"),
        (row(U0 * 1000 + 5), r"ms is not on a whole second"),
        (row(U0 * 1_000_000), r"neither unix seconds nor milliseconds"),
        (row("05/10/2026 13:30"), r"unrecognised time '05/10/2026 13:30'"),
        (
            row(U0) + row("2026-10-05T13:31:00Z"),
            r":3: time .* is ISO 8601, earlier rows are unix seconds",
        ),
        (row(U0) + row(U0 + 60, v="lots"), r":3: volume 'lots' is not a number"),
    ],
)
def test_invalid_rows_are_reported_with_their_line(tmp_path: Path, rows: str, problem: str) -> None:
    path = write(tmp_path, HEADER + rows)
    with pytest.raises(CsvImportError, match=problem) as caught:
        read(path)
    assert str(caught.value).startswith(str(path))


def test_timeframe_grid_and_overlaps(tmp_path: Path) -> None:
    with pytest.raises(CsvImportError, match="not on the 5m grid"):
        read(write(tmp_path, f"time,open,high,low,close\n{U0 + 60},1,2,0.5,1.5\n"), timeframe="5m")
    two_days = (
        "time,open,high,low,close\n2026-10-05 00:00,1,2,0.5,1.5\n2026-10-05 12:00,1,2,0.5,1.5\n"
    )
    with pytest.raises(CsvImportError, match="overlaps the 1D bar on line 2"):
        read(write(tmp_path, two_days, "d.csv"), timeframe="1D")


def test_session_anchored_bars_may_shift_an_hour_across_dst(tmp_path: Path) -> None:
    # 4h bars anchored at 17:00 New York: 21:00 UTC in summer, 22:00 UTC in winter
    text = (
        "time,open,high,low,close\n"
        "2026-10-30T21:00:00Z,1,2,0.5,1.5\n"
        "2026-11-02T01:00:00Z,1,2,0.5,1.5\n"  # after a weekend
        "2026-11-02T22:00:00Z,1,2,0.5,1.5\n"
        "2026-11-03T02:00:00Z,1,2,0.5,1.5\n"
    )
    assert len(read(write(tmp_path, text), timeframe="4h")) == 4
    # a 24/7 series anchored in New York: the spring change makes one step 3 hours long
    spring = "time,open,high,low,close\n2026-03-08T05:00:00Z,1,2,0.5,1.5\n"
    spring += "2026-03-08T08:00:00Z,1,2,0.5,1.5\n2026-03-08T12:00:00Z,1,2,0.5,1.5\n"
    assert len(read(write(tmp_path, spring, "s.csv"), timeframe="4h")) == 3
    short = "time,open,high,low,close\n2026-03-09T21:00:00Z,1,2,0.5,1.5\n"
    short += "2026-03-09T23:00:00Z,1,2,0.5,1.5\n"
    with pytest.raises(CsvImportError, match="overlaps the 4h bar"):
        read(write(tmp_path, short, "x.csv"), timeframe="4h")


def test_a_longer_timeframe_read_as_1m_is_caught(tmp_path: Path) -> None:
    rows = "".join(f"{U0 + i * 300},1,2,0.5,1.5\n" for i in range(12))
    with pytest.raises(CsvImportError, match="no two consecutive rows are 1m apart"):
        read(write(tmp_path, "time,open,high,low,close\n" + rows))


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("", "empty file"),
        ("time,open,high,close\n", "lacks low"),
        ("date_time,o,h,l,c\n", "lacks time, open, high, low, close"),
        ('time,open\n"unterminated', "malformed CSV|expected"),
    ],
)
def test_unusable_files(tmp_path: Path, text: str, problem: str) -> None:
    with pytest.raises(CsvImportError, match=problem):
        read(write(tmp_path, text))


def test_bad_arguments_and_files(tmp_path: Path) -> None:
    path = write(tmp_path, TRADINGVIEW)
    with pytest.raises(CsvImportError, match="unknown time zone"):
        read(path, tz="Mars/Olympus")
    with pytest.raises(CsvImportError, match="monthly bars"):
        read(path, timeframe="1M")
    with pytest.raises(CsvImportError, match="unrecognised timeframe"):
        read(path, timeframe="7x")
    with pytest.raises(CsvImportError, match="cannot read"):
        read(tmp_path / "missing.csv")
    binary = tmp_path / "binary.csv"
    binary.write_bytes(b"time,open,high,low,close\n\xff\xfe\x00\n")
    with pytest.raises(CsvImportError, match="not UTF-8"):
        read(binary)


# ── writing ──────────────────────────────────────────────────────────────────
def test_written_files_read_back_identically(tmp_path: Path) -> None:
    later = T0 + timedelta(minutes=3)
    tiny = "0.0000013"
    bars = [
        Bar.of("PUMPUSD", "1m", T0, "0.0000012", "0.0000015", "0.00000100", tiny, "1E+9", "x"),
        Bar.of("PUMPUSD", "1m", later, tiny, tiny, tiny, tiny, "0", "x"),
    ]
    path = tmp_path / "out" / "pump.csv"
    assert write_bars_csv(path, bars) == 2
    assert path.read_text().splitlines() == [
        "time,open,high,low,close,volume",
        "2026-10-05T13:30:00Z,0.0000012,0.0000015,0.00000100,0.0000013,1000000000",
        "2026-10-05T13:33:00Z,0.0000013,0.0000013,0.0000013,0.0000013,0",
    ]
    assert read_bars_csv(path, "PUMPUSD", source="x") == bars
    assert [p.name for p in path.parent.iterdir()] == ["pump.csv"]  # no temporary left


def test_a_failed_write_leaves_no_file(tmp_path: Path) -> None:
    def broken() -> object:
        yield Bar.of("X", "1m", T0, 1, 1, 1, 1)
        raise RuntimeError("source failed")

    with pytest.raises(RuntimeError):
        write_bars_csv(tmp_path / "x.csv", broken())  # type: ignore[arg-type]
    assert list(tmp_path.iterdir()) == []
    assert Timeframe.parse("1m") == M1
