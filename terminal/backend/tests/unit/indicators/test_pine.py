import math
from collections.abc import Callable
from decimal import ROUND_HALF_UP, Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from kterminal.indicators import (
    EPSILON,
    FixNan,
    div,
    eq,
    feed,
    ge,
    gt,
    le,
    lt,
    na,
    ne,
    nz,
    pine_round,
    round_to_mintick,
)

NAN = math.nan
finite = st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False)


@pytest.mark.parametrize("value", [NAN, None, math.inf, -math.inf])
def test_na_values(value: float | None) -> None:
    assert na(value)
    assert nz(value) == 0.0
    assert nz(value, 7.5) == 7.5


@pytest.mark.parametrize("value", [0.0, -0.0, 1.5, -3.0, 1e300])
def test_defined_values(value: float) -> None:
    assert not na(value)
    assert nz(value, 7.5) == value


@pytest.mark.parametrize(
    ("numerator", "denominator", "expected"),
    [
        (6.0, 3.0, 2.0),
        (1.0, 0.0, NAN),  # Pine: x / 0 is na, not an error and not infinity
        (0.0, 0.0, NAN),
        (NAN, 1.0, NAN),
        (1.0, NAN, NAN),
        (1e308, 1e-308, NAN),  # overflow to infinity is na too
    ],
)
def test_div(numerator: float, denominator: float, expected: float) -> None:
    result = div(numerator, denominator)
    assert (na(result) and na(expected)) or result == expected


def test_fixnan_carries_the_last_defined_value() -> None:
    out = feed(FixNan().update, [NAN, 1.0, NAN, math.inf, 2.0, NAN])
    assert out[0] != out[0]
    assert out[1:] == [1.0, 1.0, 1.0, 2.0, 2.0]


# ── math.round ───────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.5, 1.0),
        (1.5, 2.0),
        (2.5, 3.0),  # Python's round(2.5) == 2
        (4.5, 5.0),  # the Wyckoff script's trendEnd for liveLen 6: Pine 5, round() 4
        (-0.5, -1.0),  # ties go away from zero
        (-2.5, -3.0),
        (2.4999999999, 2.0),
        (0.49999999999999994, 0.0),  # just below the tie: floor(x + 0.5) would say 1
        (-7.2, -7.0),
        (2.0**53 + 2, 2.0**53 + 2),  # already an integer
    ],
)
def test_pine_round_ties_away_from_zero(value: float, expected: float) -> None:
    assert pine_round(value) == expected


@pytest.mark.parametrize(
    ("value", "precision", "expected"),
    [
        (2.675, 2, 2.68),  # the double is 2.67499999999999982…: a near-tie counts as the tie
        (1.005, 2, 1.01),
        (-2.675, 2, -2.68),
        (2.674, 2, 2.67),
        (1.23456, 3, 1.235),
        (12.5, 0, 13.0),  # precision <= 0 is integer rounding
        (12.5, -2, 13.0),
        (123.456, 40, 123.456),  # precision capped at 16
    ],
)
def test_pine_round_with_precision(value: float, precision: int, expected: float) -> None:
    assert pine_round(value, precision) == pytest.approx(expected, abs=1e-12)


def test_pine_round_na_and_negative_zero() -> None:
    assert na(pine_round(NAN))
    assert na(pine_round(math.inf, 2))
    result = pine_round(-0.001, 2)
    assert result == 0.0
    assert math.copysign(1.0, result) == 1.0  # not -0.0


@given(finite)
def test_pine_round_matches_exact_half_away_from_zero(value: float) -> None:
    exact = Decimal(value).quantize(Decimal(1), rounding=ROUND_HALF_UP)  # exact double value
    assert pine_round(value) == float(exact)


@given(finite, st.integers(min_value=1, max_value=6))
def test_pine_round_precision_lands_on_the_grid(value: float, precision: int) -> None:
    result = pine_round(value, precision)
    step = 10.0**-precision
    assert abs(result - value) <= step / 2 + 1e-9 * max(1.0, abs(value))
    exponent = Decimal(repr(result)).as_tuple().exponent
    assert isinstance(exponent, int)
    assert exponent >= -precision  # the shortest repr has at most `precision` decimals


# ── math.round_to_mintick ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("value", "tick", "expected"),
    [
        (1.005, 0.01, 1.01),
        (19999.585, Decimal("0.01"), 19999.59),
        (-1.075, 0.01, -1.08),
        (101.12, Decimal("0.25"), 101.0),
        (101.125, Decimal("0.25"), 101.25),  # exact tie, away from zero
        (101.124, Decimal("0.25"), 101.0),
        (0.0, 0.01, 0.0),
        (1.23456789, Decimal("0.00001"), 1.23457),
    ],
)
def test_round_to_mintick(value: float, tick: Decimal | float, expected: float) -> None:
    assert round_to_mintick(value, tick) == expected


def test_round_to_mintick_rejects_bad_ticks_and_passes_na() -> None:
    assert na(round_to_mintick(NAN, 0.01))
    with pytest.raises(ValueError, match="positive"):
        round_to_mintick(1.0, 0.0)
    with pytest.raises(ValueError, match="positive"):
        round_to_mintick(1.0, Decimal("-0.25"))


@given(finite, st.sampled_from([Decimal("0.01"), Decimal("0.25"), Decimal("0.00001"), 0.5]))
def test_round_to_mintick_is_on_the_grid(value: float, tick: Decimal | float) -> None:
    result = round_to_mintick(value, tick)
    step = Decimal(str(tick))
    assert abs(result - value) <= float(step) / 2 + 1e-9
    assert Decimal(repr(result)) % step == 0  # the shortest repr is the grid value itself


# ── tolerant comparisons ─────────────────────────────────────────────────────────────


def test_comparisons_use_the_1e10_tolerance() -> None:
    assert EPSILON == 1e-10
    a, b = 1.0, 1.0 + 5e-11  # equal for Pine
    assert eq(a, b) and not ne(a, b)
    assert not gt(b, a) and not lt(a, b)
    assert ge(a, b) and le(b, a)
    # the boundary belongs to equality: a difference of exactly 1e-10
    assert eq(0.0, 1e-10) and not lt(0.0, 1e-10) and ge(0.0, 1e-10) and le(1e-10, 0.0)
    assert gt(1.0, 0.0) and lt(0.0, 1.0) and ne(0.0, 1.0)


@pytest.mark.parametrize("compare", [gt, ge, lt, le, eq, ne])
@pytest.mark.parametrize(("a", "b"), [(NAN, 0.0), (0.0, NAN), (None, 0.0), (0.0, math.inf)])
def test_every_comparison_with_na_is_false(
    compare: Callable[[float | None, float | None], bool], a: float | None, b: float | None
) -> None:
    assert compare(a, b) is False


def test_ne_with_na_is_false_unlike_not_eq() -> None:
    # script 10: ``ci = de != 0 ? … : 0`` takes the 0 branch while de is na
    assert not ne(NAN, 0.0)
    assert not eq(NAN, 0.0)


@given(finite, finite)
def test_comparisons_are_consistent(a: float, b: float) -> None:
    assert [lt(a, b), eq(a, b), gt(a, b)].count(True) == 1
    assert ge(a, b) == (gt(a, b) or eq(a, b))
    assert le(a, b) == (lt(a, b) or eq(a, b))
    assert ne(a, b) == (not eq(a, b))
    assert gt(a, b) == lt(b, a)
