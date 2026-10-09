"""Window extremes: ``ta.highest``, ``ta.lowest``, ``ta.highestbars``, ``ta.lowestbars``.

Semantics (shared by all four, and by the pivots in ``pivots.py``):

* **Window** — the last ``length`` bars, *including the current one* (Pine's
  ``ta.highest(high, 26)[1]`` idiom — "the previous 26 bars" — is the value
  this object returned on the previous bar).
* **Warm-up** — na until ``length`` bars have been seen, counted in bars (calls),
  not in non-na values.
* **na** — a na source *resets* the window: that bar returns na (the ``bars``
  forms return 0), and the following bars look back only as far as the bar
  after the na. After a leading run of na the extreme is therefore taken over
  the shorter window since the last na. This differs from the moving
  averages, which skip na instead.
* **Ties** — ``highest``/``lowest`` and their ``bars`` forms report the
  **oldest** of equal extremes in the window.
* **Per-bar lengths** — Pine accepts a ``series int`` length (e.g. ``ta.highest
  (barsSinceReset)``). Construct with ``max_length=N`` (the largest length that
  will ever be asked) and pass ``length=`` to every ``update``; the window
  is then the last ``length`` bars, also when the length grows again.

The na-reset and tie rules follow behaviour the PyneCore project reports
having measured against TradingView output; they are recorded as unverified
in docs/14 until checked against our own TradingView exports.
"""

import math
from typing import ClassVar

from kterminal.indicators._extreme import Extreme
from kterminal.indicators._validate import check_int

__all__ = ["Highest", "HighestBars", "Lowest", "LowestBars"]


class _WindowExtreme:
    _IS_MAX: ClassVar[bool]
    _OFFSET: ClassVar[bool]

    __slots__ = ("_engine", "length", "max_length", "value")

    def __init__(self, length: int | None = None, *, max_length: int | None = None) -> None:
        self.length, self.max_length = _lengths(length, max_length)
        self._engine = Extreme(self.max_length, self._IS_MAX, newest_wins=False)
        self.value = math.nan

    def update(self, source: float, length: int | None = None) -> float:
        n = _resolve_length(length, self.length, self.max_length)
        self._engine.push(source)
        if self._engine.bar < n - 1:
            self.value = math.nan
        elif not math.isfinite(source):
            self.value = 0.0 if self._OFFSET else math.nan
        else:
            extreme, offset = self._engine.query(n)
            self.value = float(-offset) if self._OFFSET else extreme
        return self.value


def _lengths(length: int | None, max_length: int | None) -> tuple[int | None, int]:
    """Validate a fixed ``length`` and/or the ``max_length`` of a per-bar length."""
    if length is not None:
        check_int("length", length, 1)
    if max_length is None:
        if length is None:
            raise ValueError("give a length, or max_length for a per-bar length")
        return length, length
    check_int("max_length", max_length, 1)
    if length is not None and length > max_length:
        raise ValueError(f"length {length} exceeds max_length {max_length}")
    return length, max_length


def _resolve_length(length: int | None, fixed: int | None, max_length: int) -> int:
    if length is None:
        if fixed is None:
            raise ValueError("this object was built with max_length only: pass length= each bar")
        return fixed
    check_int("length", length, 1)
    if length > max_length:
        raise ValueError(f"length {length} exceeds max_length {max_length}")
    return length


class Highest(_WindowExtreme):
    """Pine ``ta.highest(source, length)``: the highest value of the last ``length`` bars.

    See the module docstring for the window, warm-up, na and per-bar-length
    rules.
    """

    _IS_MAX = True
    _OFFSET = False
    __slots__ = ()


class Lowest(_WindowExtreme):
    """Pine ``ta.lowest(source, length)``: the lowest value of the last ``length`` bars."""

    _IS_MAX = False
    _OFFSET = False
    __slots__ = ()


class HighestBars(_WindowExtreme):
    """Pine ``ta.highestbars(source, length)``: offset of the highest bar, ``-(length - 1)`` … 0.

    Equal highs: the offset of the **oldest** one. 0 on a bar whose source is
    na (after warm-up). Returned as a float.
    """

    _IS_MAX = True
    _OFFSET = True
    __slots__ = ()


class LowestBars(_WindowExtreme):
    """Pine ``ta.lowestbars(source, length)``: offset of the lowest bar, ``-(length - 1)`` … 0.

    Equal lows: the offset of the **oldest** one.
    """

    _IS_MAX = False
    _OFFSET = True
    __slots__ = ()
