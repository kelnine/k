import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from kterminal.indicators import Ema, Macd, MacdValue, Rsi, WaveTrend, feed
from tests.unit.indicators.reference import (
    assert_series_close,
    ref_ema,
    ref_rsi,
    ref_wavetrend,
)

NAN = math.nan
prices = st.integers(900, 1100).map(lambda x: x / 4)
series_with_gaps = st.lists(st.one_of(prices, prices, prices, st.just(NAN)), max_size=60)


def test_rsi_hand_vector() -> None:
    # changes +1 +1 -1 | -1 +1 +1 0 0; Wilder averages with length 3:
    # bar 3: up 2/3, down 1/3 → RS 2 → 66.67; bar 4: up 4/9, down 5/9 → RS 0.8 → 44.44;
    # bar 5: 17/27 vs 10/27 → 62.96; bar 6: 61/81 vs 20/81 → RS 3.05 → 75.31; bar 7: same RS
    out = feed(Rsi(3).update, [1.0, 2.0, 3.0, 2.0, 1.0, 2.0, 3.0, 3.0])
    expected = [NAN, NAN, NAN, 200 / 3, 400 / 9, 100 - 100 / 2.7, 100 - 100 / 4.05]
    assert_series_close(out, [*expected, 100 - 100 / 4.05], tol=1e-12)


def test_rsi_saturates_without_losses_or_gains() -> None:
    assert_series_close(feed(Rsi(3).update, [5.0] * 6), [NAN, NAN, NAN, 100.0, 100.0, 100.0])
    assert_series_close(feed(Rsi(2).update, [5.0, 4.0, 3.0, 2.0]), [NAN, NAN, 0.0, 0.0])
    # a loss decayed below Pine's 1e-10 counts as no loss: exactly 100
    out = feed(Rsi(2).update, [2.0, 1.0] + [float(i) for i in range(2, 50)])
    assert out[-1] == 100.0


def test_rsi_skips_na_and_measures_change_from_the_last_defined_close() -> None:
    out = feed(Rsi(2).update, [NAN, 1.0, 2.0, NAN, 3.0, 2.0])
    assert_series_close(out, [NAN, NAN, NAN, NAN, 100.0, 50.0])


def test_rsi_length_must_be_positive() -> None:
    with pytest.raises(ValueError, match="length must be >= 1"):
        Rsi(0)


@given(series_with_gaps, st.integers(1, 6))
def test_rsi_matches_reference(xs: list[float], n: int) -> None:
    assert_series_close(feed(Rsi(n).update, xs), ref_rsi(xs, n), tol=1e-7)


def test_macd_hand_vector() -> None:
    # EMA2: -, 1.5, 2.5, 3.5, 4.5; EMA3: -, -, 2, 3, 4 → MACD 0.5; signal EMA2 seeded on bar 3
    out = feed(Macd(2, 3, 2).update, [1.0, 2.0, 3.0, 4.0, 5.0])
    assert all(math.isnan(v) for v in out[0] + out[1])
    assert out[2].macd == 0.5 and math.isnan(out[2].signal) and math.isnan(out[2].hist)
    assert out[3] == MacdValue(0.5, 0.5, 0.0)
    assert out[4] == MacdValue(0.5, 0.5, 0.0)


@given(series_with_gaps)
def test_macd_is_the_composition_of_emas(xs: list[float]) -> None:
    out = feed(Macd(3, 6, 4).update, xs)
    fast, slow = ref_ema(xs, 3), ref_ema(xs, 6)
    macd = [f - s for f, s in zip(fast, slow, strict=True)]
    signal = ref_ema(macd, 4)
    assert_series_close([v.macd for v in out], macd)
    assert_series_close([v.signal for v in out], signal)
    assert_series_close([v.hist for v in out], [m - s for m, s in zip(macd, signal, strict=True)])


def test_elitealgo_pulse_is_a_macd_histogram() -> None:
    # script 9: pulse = EMA5 - EMA60, pHist = pulse - EMA20(pulse)
    closes = [100 + math.sin(i / 7) * 3 + i * 0.01 for i in range(300)]
    fast, slow, smooth, macd = Ema(5), Ema(60), Ema(20), Macd(5, 60, 20)
    for close in closes:
        pulse = fast.update(close) - slow.update(close)
        hist = pulse - smooth.update(pulse)
        value = macd.update(close)
        assert (math.isnan(hist) and math.isnan(value.hist)) or value.hist == hist


def test_wavetrend_on_a_constant_series_is_zero_not_na() -> None:
    # de is 0 (or still na) → ci = 0 from the first bar, so wt1 exists after n2 bars
    out = feed(WaveTrend(3, 4, 2).update, [10.0] * 8)
    assert_series_close([v.wt1 for v in out], [NAN, NAN, NAN, 0.0, 0.0, 0.0, 0.0, 0.0])
    assert_series_close([v.wt2 for v in out], [NAN, NAN, NAN, NAN, 0.0, 0.0, 0.0, 0.0])


def test_wavetrend_seeds_wt1_with_zeros_during_warm_up() -> None:
    # n1 = 5: esa exists from bar 4 and de = EMA5(|src - esa|) from bar 8; until then ci = 0,
    # so wt1 = EMA2(ci) exists from bar 1 and is 0 (a NaN-propagating port starts at bar 9)
    xs = [1.0, 2.0, 3.0, 4.0, 5.0, 7.0, 6.0, 8.0, 7.0, 9.0]
    out = feed(WaveTrend(5, 2, 1).update, xs)
    assert math.isnan(out[0].wt1)
    assert [v.wt1 for v in out[1:8]] == [0.0] * 7
    assert out[8].wt1 != 0.0 and out[8].wt2 == out[8].wt1  # signal length 1


@given(series_with_gaps)
def test_wavetrend_matches_reference(xs: list[float]) -> None:
    out = feed(WaveTrend(4, 6, 3).update, xs)
    wt1, wt2 = ref_wavetrend(xs, 4, 6, 3)
    assert_series_close([v.wt1 for v in out], wt1, tol=1e-6)
    assert_series_close([v.wt2 for v in out], wt2, tol=1e-6)
