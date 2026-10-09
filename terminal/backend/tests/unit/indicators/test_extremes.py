import math

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from kterminal.indicators import Highest, HighestBars, History, Lowest, LowestBars, feed
from tests.unit.indicators.reference import assert_series_close, ref_extreme

NAN = math.nan
# small integers: equal values (ties) are frequent
ticks = st.integers(-6, 6).map(float)
series_with_gaps = st.lists(st.one_of(ticks, ticks, ticks, st.just(NAN)), max_size=70)

CLASSES = [(Highest, True, False), (Lowest, False, False), (HighestBars, True, True)]
CLASSES += [(LowestBars, False, True)]


def test_highest_hand_vector_with_tie_and_na_reset() -> None:
    xs = [1.0, 3.0, 2.0, 3.0, NAN, 1.0, 2.0]
    # bar 4 is na → na, and bars 5-6 look back only to bar 5
    assert_series_close(feed(Highest(3).update, xs), [NAN, NAN, 3.0, 3.0, NAN, 1.0, 2.0])
    # bar 3 has equal highs on bars 1 and 3: the oldest one (-2) wins; na bar → 0
    assert_series_close(feed(HighestBars(3).update, xs), [NAN, NAN, -1.0, -2.0, 0.0, 0.0, 0.0])


def test_lowest_hand_vector_with_ties() -> None:
    xs = [5.0, 2.0, 4.0, 2.0, 6.0, 7.0, 8.0]
    assert_series_close(feed(Lowest(3).update, xs), [NAN, NAN, 2.0, 2.0, 2.0, 2.0, 6.0])
    assert_series_close(feed(LowestBars(3).update, xs), [NAN, NAN, -1.0, -2.0, -1.0, -2.0, -2.0])


def test_previous_bars_range_idiom() -> None:
    # Pine `ta.highest(high, 3)[1]`: the range of the three bars *before* this one
    highest, previous = Highest(3), History(2)
    out = []
    for high in [1.0, 5.0, 2.0, 3.0, 4.0]:
        previous.update(highest.update(high))
        out.append(previous[1])
    assert_series_close(out, [NAN, NAN, NAN, 5.0, 5.0])


def test_per_bar_length_rereads_older_bars_when_it_grows() -> None:
    highest = Highest(max_length=5)
    xs = [5.0, 1.0, 4.0, 3.0, 2.0, 6.0]
    lengths = [1, 2, 3, 2, 5, 5]
    out = [highest.update(x, length=n) for x, n in zip(xs, lengths, strict=True)]
    assert out == [5.0, 5.0, 5.0, 4.0, 5.0, 6.0]
    gated = Lowest(max_length=4)
    assert math.isnan(gated.update(1.0, length=1)) is False
    assert math.isnan(gated.update(2.0, length=3))  # only 2 bars seen: warm-up


def test_length_one_and_na() -> None:
    assert_series_close(feed(Highest(1).update, [3.0, NAN, -1.0]), [3.0, NAN, -1.0])
    assert feed(HighestBars(1).update, [3.0, NAN, -1.0]) == [0.0, 0.0, 0.0]


def test_offsets_are_never_negative_zero() -> None:
    value = HighestBars(2).update(1.0)
    assert math.isnan(value)
    value = HighestBars(1).update(1.0)
    assert value == 0.0 and math.copysign(1.0, value) == 1.0


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({}, "give a length, or max_length"),
        ({"length": 0}, "length must be >= 1"),
        ({"max_length": 0}, "max_length must be >= 1"),
        ({"length": 5, "max_length": 3}, "exceeds max_length"),
    ],
)
def test_invalid_construction(kwargs: dict[str, int], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        Highest(**kwargs)


def test_invalid_per_bar_lengths() -> None:
    per_bar = Highest(max_length=3)
    with pytest.raises(ValueError, match="pass length= each bar"):
        per_bar.update(1.0)
    with pytest.raises(ValueError, match="exceeds max_length"):
        per_bar.update(1.0, length=4)
    with pytest.raises(ValueError, match="length must be >= 1"):
        per_bar.update(1.0, length=0)
    fixed = Highest(3, max_length=10)  # a fixed length may still be overridden per bar
    assert fixed.update(2.0, length=1) == 2.0


@pytest.mark.parametrize(("cls", "is_max", "offset"), CLASSES)
@given(xs=series_with_gaps, n=st.integers(1, 8))
def test_fixed_length_matches_reference(
    cls: type[Highest], is_max: bool, offset: bool, xs: list[float], n: int
) -> None:
    expected = ref_extreme(xs, [n] * len(xs), is_max, offset)
    assert_series_close(feed(cls(n).update, xs), expected, tol=0.0)


@pytest.mark.parametrize(("cls", "is_max", "offset"), CLASSES)
@given(data=st.data(), xs=series_with_gaps)
def test_per_bar_length_matches_reference(
    cls: type[Highest], is_max: bool, offset: bool, data: st.DataObject, xs: list[float]
) -> None:
    lengths = data.draw(st.lists(st.integers(1, 9), min_size=len(xs), max_size=len(xs)))
    indicator = cls(max_length=9)
    out = [indicator.update(x, length=n) for x, n in zip(xs, lengths, strict=True)]
    assert_series_close(out, ref_extreme(xs, lengths, is_max, offset), tol=0.0)


def test_long_runs_compact_the_candidate_list() -> None:
    # a falling series keeps every bar a candidate, so the list must be trimmed as bars expire
    noise = np.random.default_rng(7).choice([0.0, 0.5], size=3_000)
    xs = [1e4 - i + float(noise[i]) for i in range(3_000)]
    xs[1_500] = NAN
    for cls, is_max, offset in CLASSES:
        expected = ref_extreme(xs, [300] * len(xs), is_max, offset)
        assert_series_close(feed(cls(300).update, xs), expected, tol=0.0)
