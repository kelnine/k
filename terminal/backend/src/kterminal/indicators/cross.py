"""Crosses: ``ta.crossover``, ``ta.crossunder`` and ``ta.cross``.

Each object keeps its *own* history of the two values passed to it, exactly
like a Pine built-in keeps the history of its arguments as passed at each
call. That matters when an argument is a variable the script reassigns later
on the same bar: Smart Money Suite's ``ta.crossover(close, lsh)`` runs before
``lsh`` is updated, so its ``[1]`` side is ``lsh`` as passed on the previous
bar, not the variable's end-of-bar value. Call ``update`` at the point where
the Pine script calls the function, with the values it has there.

A bar on which either value is na returns false and is skipped: the next
defined bar is compared with the last bar on which both values were defined.
The first defined bar never crosses.
"""

from kterminal.indicators.pine import EPSILON, na

__all__ = ["Cross", "Crossover", "Crossunder"]


class Crossover:
    """Pine ``ta.crossover(a, b)``: ``a > b`` now and ``a <= b`` on the previous defined bar.

    Both comparisons are exact (no 1e-10 tolerance). An equality plateau
    arms the cross, whichever side it was entered from.
    """

    __slots__ = ("_was_at_or_below", "value")

    def __init__(self) -> None:
        self._was_at_or_below = False
        self.value = False

    def update(self, a: float, b: float) -> bool:
        if na(a) or na(b):
            self.value = False
            return False
        self.value = a > b and self._was_at_or_below
        self._was_at_or_below = a <= b
        return self.value


class Crossunder:
    """Pine ``ta.crossunder(a, b)``: ``a < b`` now and ``a >= b`` on the previous defined bar."""

    __slots__ = ("_was_at_or_above", "value")

    def __init__(self) -> None:
        self._was_at_or_above = False
        self.value = False

    def update(self, a: float, b: float) -> bool:
        if na(a) or na(b):
            self.value = False
            return False
        self.value = a < b and self._was_at_or_above
        self._was_at_or_above = a >= b
        return self.value


class Cross:
    """Pine ``ta.cross(a, b)``: ``a`` crossed ``b`` in either direction.

    This is *not* ``crossover or crossunder``. It remembers the side ``a``
    was last strictly on — "strictly" with Pine's tolerance: ``|a - b| > 1e-10``
    — and fires when ``a`` is now exactly on the other side. An equality run
    keeps the remembered side, so above → equal → below fires on the "below"
    bar, but above → equal → above never fires. It starts with no remembered
    side, so a series that starts equal and then separates does not fire.
    (Behaviour reported as measured by the PyneCore project; unverified by us.)
    """

    __slots__ = ("_side", "value")

    def __init__(self) -> None:
        self._side = 0  # -1: last strictly below, +1: last strictly above, 0: unknown
        self.value = False

    def update(self, a: float, b: float) -> bool:
        if na(a) or na(b):
            self.value = False
            return False
        self.value = (self._side < 0 and a > b) or (self._side > 0 and a < b)
        difference = a - b
        if difference < -EPSILON:
            self._side = -1
        elif difference > EPSILON:
            self._side = 1
        return self.value
