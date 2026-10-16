import numpy as np
import pytest

from kterminal.domain.timeframes import M5
from kterminal.strategy_engine.series import BarSeries
from tests.fixtures.instruments import bars


def make_series(n: int, max_bars: int = 5) -> BarSeries:
    series = BarSeries("XAUUSD", M5, max_bars=max_bars)
    for bar in bars("XAUUSD", "5m", [(i, i + 1, i - 1, i + 0.5) for i in range(1, n + 1)]):
        series._append(bar)
    return series


def test_arrays_oldest_to_newest_and_capped() -> None:
    series = make_series(12, max_bars=5)
    assert len(series) == 5
    assert list(series.close) == [8.5, 9.5, 10.5, 11.5, 12.5]
    assert series.bar(-1).close == series.close[-1]
    assert [b.open for b in series.last(2)] == [11, 12]
    assert series.open_times.dtype == np.dtype("datetime64[us]")


def test_compaction_preserves_data_across_many_appends() -> None:
    series = make_series(1_000, max_bars=7)
    assert list(series.open) == [float(i) for i in range(994, 1001)]


def test_arrays_are_read_only() -> None:
    series = make_series(3)
    with pytest.raises(ValueError, match="read-only"):
        series.close[0] = 0.0


def test_rejects_out_of_order_and_foreign_bars() -> None:
    series = make_series(3)
    first = bars("XAUUSD", "5m", [(1, 2, 0, 1)])[0]
    with pytest.raises(ValueError, match="in order"):
        series._append(first)
    other = bars("XAGUSD", "5m", [(1, 2, 0, 1)])[0]
    with pytest.raises(ValueError, match="does not belong"):
        series._append(other)
