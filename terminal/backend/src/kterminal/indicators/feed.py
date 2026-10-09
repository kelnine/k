"""Run a streaming indicator over whole columns (tests, parity reports, notebooks)."""

from collections.abc import Callable, Iterable
from typing import Any


def feed[T](update: Callable[..., T], *columns: Iterable[Any]) -> list[T]:
    """Call ``update`` once per row of ``columns`` and collect the results.

    ``feed(Ema(9).update, closes)`` or ``feed(Atr(14).update, highs, lows, closes)``.
    The object behind ``update`` keeps its state, so feeding a second batch
    continues where the first stopped. Columns must have the same length.
    """
    if not columns:
        raise ValueError("feed needs at least one column")
    return [update(*row) for row in zip(*columns, strict=True)]
