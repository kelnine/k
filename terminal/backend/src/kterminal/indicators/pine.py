"""Pine language primitives: ``na``, ``nz``, ``fixnan``, division, rounding, comparisons.

Pine has a single "missing" value, ``na``. Here it is ``math.nan``; ``None``
and the infinities are accepted as ``na`` too, because Pine has no infinities
(``1 / 0`` is ``na`` there), so an infinite intermediate in a port stands for a
Pine ``na``.

Pine compares floats with an absolute tolerance: two values whose difference
is at most ``EPSILON`` (1e-10) are equal, so ``a > b`` means ``a - b > 1e-10``.
Built-in ``ta.*`` functions mostly compare exactly; the classes in this
package say which rule they follow. Strategy code that must reproduce a Pine
expression such as ``close > ema200`` uses :func:`gt` and friends. Every
comparison involving ``na`` is false — ``!=`` included — which is why a Pine
script's ``de != 0 ? x : 0`` takes the ``0`` branch while ``de`` is still
``na``.
"""

import math
from decimal import Decimal
from fractions import Fraction

__all__ = [
    "EPSILON",
    "FixNan",
    "div",
    "eq",
    "ge",
    "gt",
    "le",
    "lt",
    "na",
    "ne",
    "nz",
    "pine_round",
    "round_to_mintick",
]

#: Pine's absolute float-comparison tolerance; a difference of exactly 1e-10 is "equal".
EPSILON = 1e-10

_NEAR_TIE = Fraction(1, 2) - Fraction(1, 10**10)
_EXACT_INTEGERS = 2.0**52  # from here on every double is an integer


def na(value: float | None) -> bool:
    """Pine ``na(x)``: true for ``nan``, ``None`` and ±infinity."""
    return value is None or not math.isfinite(value)


def nz(value: float | None, replacement: float = 0.0) -> float:
    """Pine ``nz(x, replacement)``: ``x``, or ``replacement`` (default 0) when ``x`` is na."""
    if value is None or not math.isfinite(value):
        return replacement
    return value


def div(numerator: float, denominator: float) -> float:
    """Pine division: ``na`` when either side is na or the denominator is zero.

    Python raises on ``x / 0``; Pine returns ``na``. Use this wherever a ported
    expression can divide by zero (ranges of flat bars, empty volume sums …).
    """
    if na(numerator) or na(denominator) or denominator == 0.0:
        return math.nan
    result = numerator / denominator
    return result if math.isfinite(result) else math.nan


class FixNan:
    """Pine ``fixnan(x)``: replaces na with the last non-na value seen by this object.

    Returns na until the first non-na value. One object per call site, updated
    once per bar, exactly like the Pine built-in keeps one history per call.
    """

    __slots__ = ("value",)

    def __init__(self) -> None:
        self.value = math.nan

    def update(self, value: float) -> float:
        if not na(value):
            self.value = value
        return self.value


def pine_round(value: float, precision: int | None = None) -> float:
    """Pine ``math.round(x)`` / ``math.round(x, precision)``.

    Ties round **away from zero** (2.5 → 3, −2.5 → −3). Pine's reference
    describes this as "ties rounding up", which is the same thing for the
    non-negative values the received scripts round; Python's built-in
    ``round()`` (ties to even) is *not* the same: ``round(4.5) == 4`` but
    ``pine_round(4.5) == 5``.

    Without a precision (or with ``precision <= 0``) the result is an integer
    valued float, decided on the exact double: ``0.49999999999999994`` rounds
    down. With a positive precision the integer part is kept and only the
    fraction is rounded to ``precision`` decimals; a fraction that lies within
    1e-10 (in units of the last kept decimal) below a tie counts as the tie,
    so ``pine_round(2.675, 2) == 2.68`` although the double is just below
    2.675. The precision is capped at 16. ``na`` in, ``na`` out.
    """
    if na(value):
        return math.nan
    negative = value < 0.0
    magnitude = -value if negative else value
    if magnitude >= _EXACT_INTEGERS:
        return value
    whole = math.floor(magnitude)
    fraction = magnitude - whole  # exact for finite doubles
    if precision is None or precision <= 0:
        rounded = whole + 1.0 if fraction >= 0.5 else float(whole)
    else:
        scale = 10 ** min(precision, 16)
        scaled = Fraction(fraction) * scale
        steps = math.floor(scaled)
        if scaled - steps >= _NEAR_TIE:
            steps += 1
        rounded = float(whole + Fraction(steps, scale))  # the double nearest the decimal
    return 0.0 - rounded if negative else rounded


def round_to_mintick(value: float, mintick: Decimal | float) -> float:
    """Pine ``math.round_to_mintick(x)``: ``x`` rounded to the instrument's tick grid.

    ``mintick`` is the instrument's tick size (``ctx.instrument.tick_size``).
    Ties go away from zero; as with :func:`pine_round`, a value within 1e-10
    of a tie (in tick units, computed on the exact value) counts as the tie.
    ``na`` in, ``na`` out.
    """
    if na(value):
        return math.nan
    tick = Fraction(mintick if isinstance(mintick, Decimal) else Decimal(repr(mintick)))
    if tick <= 0:
        raise ValueError("mintick must be positive")
    negative = value < 0.0
    scaled = Fraction(-value if negative else value) / tick
    steps = math.floor(scaled)
    if scaled - steps >= _NEAR_TIE:
        steps += 1
    rounded = float(steps * tick)
    return 0.0 - rounded if negative else rounded


# ── tolerant comparisons (Pine's ``>``, ``>=``, ``<``, ``<=``, ``==``, ``!=``) ──────────────


def gt(a: float | None, b: float | None) -> bool:
    """Pine ``a > b``: ``a - b > 1e-10``; false if either side is na."""
    if a is None or b is None or na(a) or na(b):
        return False
    return a - b > EPSILON


def lt(a: float | None, b: float | None) -> bool:
    """Pine ``a < b``: ``a - b < -1e-10``; false if either side is na."""
    if a is None or b is None or na(a) or na(b):
        return False
    return a - b < -EPSILON


def ge(a: float | None, b: float | None) -> bool:
    """Pine ``a >= b``: ``a - b >= -1e-10``; false if either side is na."""
    if a is None or b is None or na(a) or na(b):
        return False
    return a >= b or a - b >= -EPSILON


def le(a: float | None, b: float | None) -> bool:
    """Pine ``a <= b``: ``a - b <= 1e-10``; false if either side is na."""
    if a is None or b is None or na(a) or na(b):
        return False
    return a <= b or a - b <= EPSILON


def eq(a: float | None, b: float | None) -> bool:
    """Pine ``a == b``: ``|a - b| <= 1e-10``; false if either side is na."""
    if a is None or b is None or na(a) or na(b):
        return False
    return a == b or abs(a - b) <= EPSILON


def ne(a: float | None, b: float | None) -> bool:
    """Pine ``a != b``: ``|a - b| > 1e-10``; **false** if either side is na.

    So ``ne(x, 0)`` is not ``not eq(x, 0)``: with ``x`` na both are false.
    """
    if a is None or b is None or na(a) or na(b):
        return False
    return abs(a - b) > EPSILON
