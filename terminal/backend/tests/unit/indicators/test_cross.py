import math

from hypothesis import given
from hypothesis import strategies as st

from kterminal.indicators import Cross, Crossover, Crossunder, feed
from tests.unit.indicators.reference import ref_cross, ref_crossover

NAN = math.nan
ticks = st.integers(-3, 3).map(float)
pairs = st.lists(st.tuples(st.one_of(ticks, ticks, st.just(NAN)), ticks), max_size=60)


def test_crossover_hand_vector() -> None:
    a = [1.0, 2.0, 3.0, 2.0, 3.0]
    assert feed(Crossover().update, a, [2.0] * 5) == [False, False, True, False, True]
    assert feed(Crossunder().update, a, [2.0] * 5) == [False] * 5  # never strictly below
    mirror = [3.0, 2.0, 1.0, 2.0, 1.0]
    assert feed(Crossunder().update, mirror, [2.0] * 5) == [False, False, True, False, True]


def test_an_equality_plateau_entered_from_above_arms_the_crossover() -> None:
    assert feed(Crossover().update, [3.0, 2.0, 3.0], [2.0] * 3) == [False, False, True]
    assert feed(Crossunder().update, [1.0, 2.0, 1.0], [2.0] * 3) == [False, False, True]


def test_the_first_defined_bar_never_crosses() -> None:
    assert feed(Crossover().update, [NAN, 3.0], [2.0, 2.0]) == [False, False]
    assert Crossunder().update(1.0, 2.0) is False


def test_na_bars_are_skipped_not_reset() -> None:
    # bar 2 is compared with bar 0, the last bar where both values were defined
    assert feed(Crossover().update, [1.0, NAN, 3.0], [2.0, 2.0, 2.0]) == [False, False, True]
    assert feed(Crossunder().update, [3.0, 1.0, 0.0], [2.0, NAN, 2.0]) == [False, False, True]


def test_history_is_kept_as_passed() -> None:
    # Smart Money Suite: ta.crossover(close, lsh) runs before lsh is updated on the same bar,
    # so its [1] side is lsh as passed on the previous bar (12), not the updated level (10.5)
    cross = Crossover()
    lsh = NAN
    out = []
    for close, new_level in [(10.0, 12.0), (10.0, 10.5), (11.0, 10.5)]:
        out.append(cross.update(close, lsh))  # the call, with the level as it is now
        lsh = new_level  # the script updates the level after the call
    assert out == [False, False, True]


def test_cross_hand_vectors() -> None:
    zero = [0.0] * 6
    assert feed(Cross().update, [1.0, 0.0, -1.0, 0.0, 1.0, 1.0], zero) == [
        False, False, True, False, True, False,
    ]  # fmt: skip
    # above → equal → above is no cross (crossover/crossunder see one)
    assert feed(Cross().update, [1.0, 0.0, 1.0], zero[:3]) == [False, False, False]
    assert feed(Crossover().update, [1.0, 0.0, 1.0], zero[:3]) == [False, False, True]
    # starting equal: no known side, so the first separation is no cross
    assert feed(Cross().update, [0.0, 0.0, 1.0], zero[:3]) == [False, False, False]


def test_cross_remembers_sides_with_the_pine_tolerance() -> None:
    # 5e-11 above zero is "equal" for Pine: ta.cross has no side yet, ta.crossunder fires
    assert feed(Cross().update, [5e-11, -1.0], [0.0, 0.0]) == [False, False]
    assert feed(Crossunder().update, [5e-11, -1.0], [0.0, 0.0]) == [False, True]
    assert feed(Cross().update, [1.0, NAN, -1.0], [0.0, 0.0, 0.0]) == [False, False, True]


def test_value_attribute() -> None:
    cross = Crossover()
    cross.update(1.0, 2.0)
    cross.update(3.0, 2.0)
    assert cross.value is True
    cross.update(NAN, 2.0)
    assert cross.value is False


@given(pairs)
def test_crosses_match_reference(rows: list[tuple[float, float]]) -> None:
    a, b = [x for x, _ in rows], [y for _, y in rows]
    assert feed(Crossover().update, a, b) == ref_crossover(a, b)
    assert feed(Crossunder().update, a, b) == ref_crossover(a, b, under=True)
    assert feed(Cross().update, a, b) == ref_cross(a, b)
