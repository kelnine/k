import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from kterminal.indicators import Ema, Rma, Sma, Sum, feed
from tests.unit.indicators.reference import (
    assert_series_close,
    ref_ema,
    ref_rma,
    ref_sma,
    ref_sum,
)

NAN = math.nan
values = st.floats(min_value=-1e3, max_value=1e3, allow_nan=False, allow_infinity=False)
series_with_gaps = st.lists(st.one_of(values, st.just(NAN)), max_size=60)
lengths = st.integers(min_value=1, max_value=8)


def test_sum_and_sma_hand_vectors() -> None:
    xs = [1.0, 2.0, 3.0, 4.0, NAN, 5.0]
    # the na bar returns na and is skipped: the last window is [3, 4, 5]
    assert_series_close(feed(Sum(3).update, xs), [NAN, NAN, 6.0, 9.0, NAN, 12.0])
    assert_series_close(feed(Sma(3).update, xs), [NAN, NAN, 2.0, 3.0, NAN, 4.0])


def test_ema_is_seeded_with_the_sma() -> None:
    # alpha = 2 / (3 + 1) = 0.5; seed = (2 + 4 + 6) / 3 = 4; 4 + .5 * (10 - 4) = 7; 7 + .5 * (2 - 7)
    assert_series_close(feed(Ema(3).update, [2.0, 4.0, 6.0, 10.0, 2.0]), [NAN, NAN, 4.0, 7.0, 4.5])


def test_rma_is_seeded_with_the_sma() -> None:
    # alpha = 1/3; seed = 2; (2 * 2 + 4) / 3 = 8/3; (8/3 * 2 + 5) / 3 = 31/9
    out = feed(Rma(3).update, [1.0, 2.0, 3.0, 4.0, 5.0])
    assert_series_close(out, [NAN, NAN, 2.0, 8 / 3, 31 / 9], tol=1e-15)


def test_leading_na_only_delays_the_seed() -> None:
    # an input that is still warming up: the EMA starts after `length` defined values
    out = feed(Ema(2).update, [NAN, NAN, 1.0, 3.0, 5.0])
    assert_series_close(out, [NAN, NAN, NAN, 2.0, 2.0 + 2 / 3 * 3.0])


def test_na_in_the_middle_is_skipped_not_propagated() -> None:
    # seed 2 on bar 1; bar 2 is na (state untouched); bar 3 continues from 2
    assert_series_close(feed(Ema(2).update, [1.0, 3.0, NAN, 5.0]), [NAN, 2.0, NAN, 4.0])
    assert_series_close(feed(Rma(2).update, [1.0, 3.0, math.inf, 5.0]), [NAN, 2.0, NAN, 3.5])


@pytest.mark.parametrize("cls", [Sum, Sma, Ema, Rma])
def test_length_one_returns_the_source(cls: type[Sum | Sma | Ema | Rma]) -> None:
    xs = [0.1, 0.3, NAN, -7.25, 1e-9]
    assert_series_close(feed(cls(1).update, xs), xs, tol=0.0)


@pytest.mark.parametrize("cls", [Sma, Ema, Rma])
def test_constant_series(cls: type[Sma | Ema | Rma]) -> None:
    out = feed(cls(5).update, [2.5] * 30)
    assert all(math.isnan(x) for x in out[:4])
    assert out[4:] == [2.5] * 26  # 2.5 is exact in binary: no rounding at all


def test_value_attribute_tracks_the_last_result() -> None:
    ema = Ema(2)
    assert math.isnan(ema.value)
    ema.update(1.0)
    ema.update(3.0)
    assert ema.value == 2.0
    ema.update(NAN)
    assert math.isnan(ema.value)


@pytest.mark.parametrize("cls", [Sum, Sma, Ema, Rma])
@pytest.mark.parametrize("length", [0, -3])
def test_lengths_must_be_positive(cls: type[Sum | Sma | Ema | Rma], length: int) -> None:
    with pytest.raises(ValueError, match="length must be >= 1"):
        cls(length)


def test_lengths_must_be_integers() -> None:
    with pytest.raises(ValueError, match="must be an integer"):
        Sma(2.5)  # type: ignore[arg-type]


@given(series_with_gaps, lengths)
def test_sum_and_sma_match_reference(xs: list[float], n: int) -> None:
    assert_series_close(feed(Sum(n).update, xs), ref_sum(xs, n))
    assert_series_close(feed(Sma(n).update, xs), ref_sma(xs, n))


@given(series_with_gaps, lengths)
def test_ema_matches_closed_form(xs: list[float], n: int) -> None:
    assert_series_close(feed(Ema(n).update, xs), ref_ema(xs, n), tol=1e-9)


@given(series_with_gaps, lengths)
def test_rma_matches_closed_form(xs: list[float], n: int) -> None:
    assert_series_close(feed(Rma(n).update, xs), ref_rma(xs, n), tol=1e-9)


@given(st.lists(values, min_size=1, max_size=60), lengths)
def test_averages_stay_within_the_input_range(xs: list[float], n: int) -> None:
    low, high = min(xs) - 1e-9, max(xs) + 1e-9
    for cls in (Sma, Ema, Rma):
        assert all(math.isnan(v) or low <= v <= high for v in feed(cls(n).update, xs))
