import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from kterminal.indicators import Atr, Stdev, TrueRange, Variance, feed
from tests.unit.indicators.reference import (
    assert_series_close,
    ref_atr,
    ref_tr,
    ref_variance,
)
from tests.unit.indicators.strategies import Ohlc, ohlc_bars

NAN = math.nan
values = st.floats(min_value=-1e3, max_value=1e3, allow_nan=False, allow_infinity=False)
series_with_gaps = st.lists(st.one_of(values, st.just(NAN)), max_size=60)

# three bars: (high, low, close)
HIGHS, LOWS, CLOSES = [10.0, 12.0, 11.0, 15.0], [8.0, 9.0, 7.0, 14.0], [9.0, 11.0, 8.0, 14.5]


def test_stdev_is_the_population_standard_deviation() -> None:
    xs = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]  # the textbook example: σ = 2
    assert feed(Stdev(8).update, xs)[-1] == 2.0
    assert feed(Stdev(8, biased=False).update, xs)[-1] == pytest.approx(math.sqrt(32 / 7))
    # window 3: [2, 4, 4] → 12 - (10/3)² = 8/9; [4, 4, 4] → exactly 0;
    # [4, 4, 5] → 19 - (13/3)² = 2/9
    out = feed(Variance(3).update, xs[:5])
    assert_series_close(out, [NAN, NAN, 8 / 9, 0.0, 2 / 9], tol=1e-12)


def test_variance_skips_na_and_is_clamped_at_zero() -> None:
    assert_series_close(feed(Variance(2).update, [1.0, NAN, 3.0]), [NAN, NAN, 1.0])
    assert feed(Stdev(3).update, [2.5] * 6)[2:] == [0.0] * 4  # constant: exactly 0
    # the one-pass formula (as on TradingView) cancels at large magnitudes: the true
    # variance of [0.3, 0.1, 0.7] is 0.0622, around 1e8 it computes as a negative
    # number, which is clamped to 0 instead of giving a NaN standard deviation
    out = feed(Stdev(3).update, [1e8 + 0.3, 1e8 + 0.1, 1e8 + 0.7])
    assert out[2] == 0.0


@given(st.lists(st.floats(1e7, 1e9), min_size=3, max_size=30))
def test_variance_is_never_negative(xs: list[float]) -> None:
    assert all(v >= 0.0 for v in feed(Variance(3).update, xs)[2:])


def test_variance_length_one() -> None:
    assert feed(Variance(1).update, [3.0, 4.0]) == [0.0, 0.0]
    assert all(math.isnan(v) for v in feed(Variance(1, biased=False).update, [3.0, 4.0]))
    assert all(math.isnan(v) for v in feed(Stdev(1, biased=False).update, [3.0, 4.0]))


@given(series_with_gaps, st.integers(1, 8), st.booleans())
def test_variance_matches_numpy(xs: list[float], n: int, biased: bool) -> None:
    out = feed(Variance(n, biased).update, xs)
    assert_series_close(out, ref_variance(xs, n, biased), tol=1e-6)
    stdev = feed(Stdev(n, biased).update, xs)
    assert_series_close(stdev, [math.sqrt(v) if not math.isnan(v) else NAN for v in out], 1e-12)


def test_true_range_hand_vector() -> None:
    # bar 1: max(3, |12-9|, |9-9|) = 3; bar 2: max(4, |11-11|, |7-11|) = 4; bar 3 gaps: |15-8| = 7
    plain = feed(TrueRange().update, HIGHS, LOWS, CLOSES)
    assert_series_close(plain, [NAN, 3.0, 4.0, 7.0])
    handled = feed(TrueRange(handle_na=True).update, HIGHS, LOWS, CLOSES)
    assert handled == [2.0, 3.0, 4.0, 7.0]


def test_true_range_na_inputs() -> None:
    tr = TrueRange(handle_na=True)
    assert math.isnan(tr.update(NAN, 1.0, 1.0))  # na high: na; its close still counts
    assert tr.update(5.0, 3.0, NAN) == 4.0  # |5 - 1|
    assert tr.update(6.0, 5.0, 5.5) == 1.0  # close[1] is na again: high - low


def test_atr_hand_vector() -> None:
    # TR = 2, 3, 4, 7 → seed (2 + 3) / 2 = 2.5; (2.5 + 4) / 2 = 3.25; (3.25 + 7) / 2 = 5.125
    out = feed(Atr(2).update, HIGHS, LOWS, CLOSES)
    assert_series_close(out, [NAN, 2.5, 3.25, 5.125])


@given(ohlc_bars(), st.integers(1, 15))
def test_true_range_and_atr_match_reference(bars: Ohlc, n: int) -> None:
    highs, lows, closes = bars
    for handle_na in (False, True):
        out = feed(TrueRange(handle_na).update, highs, lows, closes)
        assert_series_close(out, ref_tr(highs, lows, closes, handle_na))
    assert_series_close(feed(Atr(n).update, highs, lows, closes), ref_atr(highs, lows, closes, n))
