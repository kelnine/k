import math

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from kterminal.indicators import PivotHigh, PivotLow, feed
from tests.unit.indicators.reference import assert_series_close, ref_pivot

NAN = math.nan
ticks = st.integers(-6, 6).map(float)
series_with_gaps = st.lists(st.one_of(ticks, ticks, ticks, st.just(NAN)), max_size=70)


def test_pivot_high_is_reported_right_bars_later() -> None:
    # bar 2 is a 2/2 pivot high (5 > 3, 4 on the left and 4, 1 on the right): known on bar 4
    out = feed(PivotHigh(2, 2).update, [3.0, 4.0, 5.0, 4.0, 1.0, 2.0])
    assert_series_close(out, [NAN, NAN, NAN, NAN, 5.0, NAN])


def test_equal_highs_the_newer_one_is_the_pivot() -> None:
    # bars 1 and 2 are equal: the pivot needs >= on the left and > on the right → bar 2
    assert_series_close(feed(PivotHigh(1, 1).update, [1.0, 3.0, 3.0, 1.0, 2.0, 1.0]),
                        [NAN, NAN, NAN, 3.0, NAN, 2.0])  # fmt: skip
    # a flat top of three: only its last bar
    assert_series_close(feed(PivotHigh(1, 1).update, [1.0, 2.0, 2.0, 2.0, 1.0]),
                        [NAN, NAN, NAN, NAN, 2.0])  # fmt: skip


def test_pivot_low_with_asymmetric_strengths_and_equal_lows() -> None:
    # bar 2 (3) is a 2/1 pivot low on bar 3; bars 5-6 are equal lows: bar 6 is the pivot, on bar 7
    out = feed(PivotLow(2, 1).update, [5.0, 4.0, 3.0, 4.0, 5.0, 2.0, 2.0, 3.0])
    assert_series_close(out, [NAN, NAN, NAN, 3.0, NAN, NAN, NAN, 2.0])


def test_zero_strengths() -> None:
    assert feed(PivotHigh(0, 0).update, [3.0, 1.0, 2.0]) == [3.0, 1.0, 2.0]
    # (2, 0): confirmed on the bar that makes it
    assert_series_close(feed(PivotHigh(2, 0).update, [1.0, 2.0, 3.0, 2.0, 4.0]),
                        [NAN, NAN, 3.0, NAN, 4.0])  # fmt: skip
    # (0, 2): the bar two back once nothing after it was as high
    assert_series_close(feed(PivotHigh(0, 2).update, [3.0, 1.0, 2.0, 5.0, 1.0, 0.0]),
                        [NAN, NAN, 3.0, NAN, NAN, 5.0])  # fmt: skip


def test_after_leading_na_the_left_side_may_be_short() -> None:
    # an oscillator that is na for three bars: the window starts at its first value, so bar 3
    # is confirmed on bar 5 with no defined bar on its left (TradingView behaves the same way)
    out = feed(PivotLow(2, 2).update, [NAN, NAN, NAN, 1.0, 2.0, 3.0, 4.0])
    assert_series_close(out, [NAN, NAN, NAN, NAN, NAN, 1.0, NAN])


def test_na_in_the_middle_resets_the_window() -> None:
    # bar 1 would be a 1/1 pivot, but the na on bar 2 cuts the window; na bars return na
    out = feed(PivotHigh(1, 1).update, [1.0, 5.0, NAN, 2.0, 1.0])
    assert_series_close(out, [NAN, NAN, NAN, NAN, 2.0])


def test_per_bar_strengths() -> None:
    pivot = PivotHigh(max_left=3, max_right=3)
    xs = [1.0, 2.0, 5.0, 3.0, 2.0, 1.0, 0.0]
    strengths = [(1, 1), (1, 1), (1, 1), (2, 1), (2, 2), (3, 3), (2, 3)]
    out = [pivot.update(x, left=lf, right=rt) for x, (lf, rt) in zip(xs, strengths, strict=True)]
    # bar 3 (2, 1): bar 2 is a pivot; bar 4 (2, 2): bar 2 again (Pine re-reports it, the
    # Wyckoff port de-duplicates by pivot bar); bar 5 (3, 3): only 6 of the 7 bars seen yet;
    # bar 6 (2, 3): the centre is bar 3, below bar 2
    assert_series_close(out, [NAN, NAN, NAN, 5.0, 5.0, NAN, NAN])


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({}, "give left and right, or max_left and max_right"),
        ({"left": 1, "right": 1, "max_left": 2, "max_right": 2}, "give left and right, or"),
        ({"left": 1}, "give both left and right"),
        ({"max_left": 2}, "give both max_left and max_right"),
        ({"left": -1, "right": 1}, "left must be >= 0"),
        ({"max_left": 1, "max_right": -2}, "max_right must be >= 0"),
    ],
)
def test_invalid_construction(kwargs: dict[str, int], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        PivotHigh(**kwargs)


def test_invalid_per_bar_strengths() -> None:
    pivot = PivotLow(max_left=2, max_right=2)
    with pytest.raises(ValueError, match="pass left= and right="):
        pivot.update(1.0)
    with pytest.raises(ValueError, match="pass both"):
        pivot.update(1.0, left=1)
    with pytest.raises(ValueError, match="exceed the maximum"):
        pivot.update(1.0, left=3, right=1)
    with pytest.raises(ValueError, match="right must be >= 0"):
        pivot.update(1.0, left=1, right=-1)
    fixed = PivotLow(2, 2)
    assert math.isnan(fixed.update(1.0, left=1, right=1))  # may shrink below its fixed strengths


@pytest.mark.parametrize(("cls", "is_high"), [(PivotHigh, True), (PivotLow, False)])
@given(xs=series_with_gaps, left=st.integers(0, 5), right=st.integers(0, 5))
def test_fixed_strengths_match_reference(
    cls: type[PivotHigh], is_high: bool, xs: list[float], left: int, right: int
) -> None:
    expected = ref_pivot(xs, [left] * len(xs), [right] * len(xs), is_high)
    assert_series_close(feed(cls(left, right).update, xs), expected, tol=0.0)


@pytest.mark.parametrize(("cls", "is_high"), [(PivotHigh, True), (PivotLow, False)])
@given(data=st.data(), xs=series_with_gaps)
def test_per_bar_strengths_match_reference(
    cls: type[PivotHigh], is_high: bool, data: st.DataObject, xs: list[float]
) -> None:
    strengths = st.integers(0, 4)
    lefts = data.draw(st.lists(strengths, min_size=len(xs), max_size=len(xs)))
    rights = data.draw(st.lists(strengths, min_size=len(xs), max_size=len(xs)))
    pivot = cls(max_left=4, max_right=4)
    out = [pivot.update(x, left=lf, right=rt) for x, lf, rt in zip(xs, lefts, rights, strict=True)]
    assert_series_close(out, ref_pivot(xs, lefts, rights, is_high), tol=0.0)


def test_forty_bar_swings_on_a_long_walk() -> None:
    # script 5's BOS swings: ta.pivothigh(high, 40, 40) on a random walk with tick-sized steps
    steps = np.random.default_rng(11).choice([-0.5, -0.25, 0.0, 0.25, 0.5], size=3_000)
    highs = [2000.0 + float(x) for x in np.cumsum(steps)]
    expected = ref_pivot(highs, [40] * len(highs), [40] * len(highs), is_high=True)
    out = feed(PivotHigh(40, 40).update, highs)
    assert_series_close(out, expected, tol=0.0)
    assert sum(not math.isnan(v) for v in out) > 5
