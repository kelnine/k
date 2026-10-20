from datetime import UTC, datetime
from decimal import Decimal

import pytest

from kterminal.domain.market import Bar, Quote

T0 = datetime(2026, 10, 5, 14, 30, tzinfo=UTC)


def test_bar_of_computes_close_time_and_decimals() -> None:
    bar = Bar.of("XAUUSD", "5m", T0, 2678.4, "2679.10", 2677, 2678.9, 120)
    assert bar.close_time == datetime(2026, 10, 5, 14, 35, tzinfo=UTC)
    assert bar.open == Decimal("2678.4")  # float went through repr, not binary noise
    assert isinstance(bar.volume, Decimal)


def test_bar_rejects_inconsistent_ohlc_and_naive_times() -> None:
    with pytest.raises(ValueError, match="inconsistent OHLC"):
        Bar.of("XAUUSD", "5m", T0, 10, 9, 8, 9.5)
    with pytest.raises(ValueError, match="naive"):
        Bar.of("XAUUSD", "5m", datetime(2026, 1, 1), 1, 1, 1, 1)  # noqa: DTZ001


def test_bar_is_immutable() -> None:
    bar = Bar.of("XAUUSD", "5m", T0, 1, 2, 0.5, 1.5)
    with pytest.raises(AttributeError):
        bar.close = Decimal(3)  # type: ignore[misc]


def test_quote() -> None:
    quote = Quote("EURUSD", T0, Decimal("1.10000"), Decimal("1.10006"))
    assert quote.spread == Decimal("0.00006")
    assert quote.mid == Decimal("1.10003")
    with pytest.raises(ValueError, match="crossed"):
        Quote("EURUSD", T0, Decimal("1.2"), Decimal("1.1"))
