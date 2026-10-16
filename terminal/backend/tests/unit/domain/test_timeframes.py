from datetime import UTC, datetime, timedelta

import pytest

from kterminal.domain.timeframes import D1, H1, H4, M1, M5, M15, Timeframe, TimeUnit


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ("1m", "1m"),
        ("5m", "5m"),
        ("15m", "15m"),
        ("1h", "1h"),
        ("4h", "4h"),
        ("1D", "1D"),
        ("1W", "1W"),
        ("1M", "1M"),
        # TradingView {{interval}}
        ("1", "1m"),
        ("5", "5m"),
        ("15", "15m"),
        ("60", "1h"),
        ("240", "4h"),
        ("D", "1D"),
        ("W", "1W"),
        ("M", "1M"),
        ("3D", "3D"),
        # MetaTrader
        ("M1", "1m"),
        ("M15", "15m"),
        ("H1", "1h"),
        ("H4", "4h"),
        ("D1", "1D"),
        ("W1", "1W"),
        ("MN1", "1M"),
        # human
        ("5min", "5m"),
        ("1 hour", "1h"),
        ("2hrs", "2h"),
        ("1day", "1D"),
        ("1 week", "1W"),
        ("120", "2h"),
        ("1440", "1D"),
    ],
)
def test_parse_spellings(raw: str, code: str) -> None:
    assert Timeframe.parse(raw).code == code


def test_minute_and_month_are_case_sensitive() -> None:
    assert Timeframe.parse("1m").unit is TimeUnit.MINUTE
    assert Timeframe.parse("1M").unit is TimeUnit.MONTH


@pytest.mark.parametrize("raw", ["", "abc", "0m", "7m", "25h", "30S", "-5", "1y"])
def test_invalid(raw: str) -> None:
    with pytest.raises(ValueError):  # noqa: PT011 - several distinct messages
        Timeframe.parse(raw)


def test_ordering_and_duration() -> None:
    assert sorted([H1, M1, D1, M15, M5]) == [M1, M5, M15, H1, D1]
    assert H4.duration == timedelta(hours=4)
    with pytest.raises(ValueError, match="no fixed duration"):
        _ = Timeframe.parse("1M").duration


def test_floor_is_utc_epoch_aligned() -> None:
    ts = datetime(2026, 10, 5, 14, 37, 12, tzinfo=UTC)
    assert M5.floor(ts) == datetime(2026, 10, 5, 14, 35, tzinfo=UTC)
    assert M15.floor(ts) == datetime(2026, 10, 5, 14, 30, tzinfo=UTC)
    assert H4.floor(ts) == datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
    assert M5.is_aligned(datetime(2026, 10, 5, 14, 35, tzinfo=UTC))
    with pytest.raises(ValueError, match="session-anchored"):
        D1.floor(ts)


def test_divides() -> None:
    assert M1.divides(M5)
    assert M5.divides(H1)
    assert M15.divides(H4)
    assert not Timeframe.parse("10m").divides(M15)


def test_str_and_parse_roundtrip() -> None:
    for tf in (M1, M5, M15, H1, H4, D1):
        assert Timeframe.parse(str(tf)) == tf
