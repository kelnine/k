"""Strategy interface: a strategy looks at OHLCV history and emits a signal."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import pandas as pd

LONG = 1
FLAT = 0
SHORT = -1


@dataclass(frozen=True)
class Signal:
    """Desired direction after this bar, plus context for the journal."""

    direction: int          # LONG, FLAT or SHORT
    reason: str = ""

    @property
    def is_entry(self) -> bool:
        return self.direction != FLAT


class Strategy(ABC):
    """Stateless: each call re-derives the signal from the data it is given.

    `current_direction` lets a strategy distinguish entries from exits
    (e.g. mean reversion exits at the mean, which is not an entry level).
    """

    #: minimum number of bars of history required before signals are valid
    warmup: int = 50

    @abstractmethod
    def signal(self, df: pd.DataFrame, current_direction: int = FLAT) -> Signal:
        """`df` columns: open, high, low, close, volume. Last row = latest bar."""
