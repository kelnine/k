import math
from collections.abc import Callable

import pytest
from hypothesis import given
from hypothesis import strategies as st

from kterminal.indicators import BarIndex, BarsSince, Change, Cum, History, ValueWhen, feed
from tests.unit.indicators.reference import assert_series_close, ref_change

NAN = math.nan
series_with_gaps = st.lists(
    st.one_of(st.integers(-5, 5).map(float), st.just(NAN)), min_size=0, max_size=60
)


def test_history_offsets_like_pine() -> None:
    h = History(3)
    assert math.isnan(h[0]) and math.isnan(h.value) and len(h) == 0
    for x in (1.0, 2.0, 3.0, 4.0):
        assert h.update(x) == x
    assert (h[0], h[1], h[2]) == (4.0, 3.0, 2.0)
    assert math.isnan(h[3])  # beyond maxlen: na
    assert h.value == 4.0 and len(h) == 3
    with pytest.raises(IndexError, match=">= 0"):
        h[-1]


def test_bar_index_counts_from_zero() -> None:
    bi = BarIndex()
    assert bi.value == -1
    assert [bi.update() for _ in range(3)] == [0, 1, 2]


def test_change_hand_vector() -> None:
    # ta.change(x) and ta.change(x, 2); na on the first bars and around the na
    xs = [1.0, 4.0, 2.0, NAN, 5.0, 6.0]
    assert_series_close(feed(Change().update, xs), [NAN, 3.0, -2.0, NAN, NAN, 1.0])
    assert_series_close(feed(Change(2).update, xs), [NAN, NAN, 1.0, NAN, 3.0, NAN])


def test_change_of_a_supertrend_direction_is_plus_minus_two() -> None:
    assert feed(Change().update, [1.0, 1.0, -1.0, -1.0, 1.0])[1:] == [0.0, -2.0, 0.0, 2.0]


@given(series_with_gaps, st.integers(1, 5))
def test_change_matches_reference(xs: list[float], n: int) -> None:
    assert_series_close(feed(Change(n).update, xs), ref_change(xs, n))


def test_barssince_hand_vector() -> None:
    out = feed(BarsSince().update, [False, False, True, False, False, True, True, False])
    assert_series_close(out, [NAN, NAN, 0.0, 1.0, 2.0, 0.0, 0.0, 1.0])


def test_valuewhen_hand_vector() -> None:
    conditions = [False, True, False, True, True, False]
    sources = [10.0, 11.0, 12.0, NAN, 14.0, 15.0]
    latest = feed(ValueWhen().update, conditions, sources)
    assert_series_close(latest, [NAN, 11.0, 11.0, NAN, 14.0, 14.0])
    # occurrence 1 = the true bar before the latest: bar 1's 11 on bar 3, bar 3's recorded na after
    previous = feed(ValueWhen(1).update, conditions, sources)
    assert_series_close(previous, [NAN, NAN, NAN, 11.0, NAN, NAN])


@given(st.lists(st.tuples(st.booleans(), st.integers(0, 99).map(float)), max_size=40))
def test_valuewhen_matches_definition(rows: list[tuple[bool, float]]) -> None:
    for occurrence in range(3):
        out = feed(ValueWhen(occurrence).update, [c for c, _ in rows], [s for _, s in rows])
        for t, value in enumerate(out):
            hits = [s for c, s in rows[: t + 1] if c]
            expected = hits[-1 - occurrence] if len(hits) > occurrence else NAN
            assert (math.isnan(value) and math.isnan(expected)) or value == expected


def test_cum_skips_na() -> None:
    out = feed(Cum().update, [1.0, 2.0, NAN, 3.5, math.inf])
    assert_series_close(out, [1.0, 3.0, NAN, 6.5, NAN])


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: History(0), "maxlen must be >= 1"),
        (lambda: Change(0), "length must be >= 1"),
        (lambda: Change(True), "must be an integer"),
        (lambda: ValueWhen(-1), "occurrence must be >= 0"),
    ],
)
def test_invalid_arguments(factory: Callable[[], object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        factory()
