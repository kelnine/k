"""Swing pivots: ``ta.pivothigh`` and ``ta.pivotlow``.

``ta.pivothigh(source, leftbars, rightbars)`` is na on every bar except the
one that *confirms* a pivot: ``rightbars`` bars after the pivot bar, it
returns the pivot's value (``source[rightbars]``). The pivot bar is therefore
``bar_index - rightbars``. The window is the ``leftbars + rightbars + 1``
bars ending at the current bar.

Ties (equal highs, e.g. a flat double top): the pivot value must be **>=**
every value on its left and **strictly >** every value on its right, so of
two equal adjacent highs the *newer* one is the pivot (``pivotlow`` mirrors
this with ``<=`` / ``<``). This is the "newest of equal extremes" rule the
PyneCore project reports having measured on TradingView; it is unverified
by us (docs/14).

Warm-up: na until ``leftbars + rightbars + 1`` bars have been seen. A na
source returns na and resets the window like ``ta.highest`` does, so right
after a leading run of na (e.g. a pivot of an oscillator that is still
warming up) a pivot can be confirmed with fewer than ``leftbars`` defined
bars on its left — as on TradingView. Zero strengths are legal:
``PivotHigh(0, 0)`` returns every bar's own value.

Per-bar lengths (Pine accepts ``series int`` strengths, e.g. an ATR-adaptive
swing length): construct with ``max_left=``/``max_right=`` and pass ``left=``
and ``right=`` to every ``update``.
"""

import math
from typing import ClassVar

from kterminal.indicators._extreme import Extreme
from kterminal.indicators._validate import check_int

__all__ = ["PivotHigh", "PivotLow"]


class _Pivot:
    _IS_MAX: ClassVar[bool]

    __slots__ = ("_engine", "left", "max_left", "max_right", "right", "value")

    def __init__(
        self,
        left: int | None = None,
        right: int | None = None,
        *,
        max_left: int | None = None,
        max_right: int | None = None,
    ) -> None:
        fixed = left is not None or right is not None
        variable = max_left is not None or max_right is not None
        if fixed == variable:
            raise ValueError("give left and right, or max_left and max_right for per-bar lengths")
        if fixed:
            if left is None or right is None:
                raise ValueError("give both left and right")
            self.left: int | None = check_int("left", left, 0)
            self.right: int | None = check_int("right", right, 0)
            self.max_left, self.max_right = left, right
        else:
            if max_left is None or max_right is None:
                raise ValueError("give both max_left and max_right")
            self.left = self.right = None
            self.max_left = check_int("max_left", max_left, 0)
            self.max_right = check_int("max_right", max_right, 0)
        self._engine = Extreme(self.max_left + self.max_right + 1, self._IS_MAX, newest_wins=True)
        self.value = math.nan

    def update(self, source: float, left: int | None = None, right: int | None = None) -> float:
        n_left, n_right = self._strengths(left, right)
        self._engine.push(source)
        self.value = math.nan
        if self._engine.bar >= n_left + n_right and math.isfinite(source):
            extreme, offset = self._engine.query(n_left + n_right + 1)
            if offset == n_right:
                self.value = extreme
        return self.value

    def _strengths(self, left: int | None, right: int | None) -> tuple[int, int]:
        if left is None and right is None:
            if self.left is None or self.right is None:
                raise ValueError("this object takes per-bar lengths: pass left= and right=")
            return self.left, self.right
        if left is None or right is None:
            raise ValueError("pass both left= and right=")
        check_int("left", left, 0)
        check_int("right", right, 0)
        if left > self.max_left or right > self.max_right:
            raise ValueError(
                f"strengths ({left}, {right}) exceed the maximum "
                f"({self.max_left}, {self.max_right})"
            )
        return left, right


class PivotHigh(_Pivot):
    """Pine ``ta.pivothigh(source, leftbars, rightbars)``; see the module docstring."""

    _IS_MAX = True
    __slots__ = ()


class PivotLow(_Pivot):
    """Pine ``ta.pivotlow(source, leftbars, rightbars)``; see the module docstring."""

    _IS_MAX = False
    __slots__ = ()
