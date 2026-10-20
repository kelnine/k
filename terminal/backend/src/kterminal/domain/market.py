"""Market data value types: bars and quotes.

Both are immutable, so the same bar object can be handed to every strategy in
the lab without any strategy being able to alter what another one sees.
Prices are ``Decimal``; strategies get float arrays for indicator maths via
``BarSeries`` in the strategy engine.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from kterminal.core.clock import ensure_utc
from kterminal.domain.timeframes import Timeframe


@dataclass(frozen=True, slots=True)
class Bar:
    """One OHLCV bar of a canonical instrument. ``open_time`` is inclusive,
    ``close_time`` exclusive; a bar is only ever delivered once it has closed."""

    instrument: str
    timeframe: Timeframe
    open_time: datetime
    close_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal = Decimal(0)
    source: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "open_time", ensure_utc(self.open_time))
        object.__setattr__(self, "close_time", ensure_utc(self.close_time))
        if self.close_time <= self.open_time:
            raise ValueError(f"bar close_time must be after open_time ({self.instrument})")
        if self.high < max(self.open, self.close, self.low) or self.low > min(
            self.open, self.close, self.high
        ):
            raise ValueError(
                f"inconsistent OHLC for {self.instrument} {self.timeframe} at "
                f"{self.open_time.isoformat()}: O={self.open} H={self.high} L={self.low} "
                f"C={self.close}"
            )
        if self.volume < 0:
            raise ValueError("bar volume cannot be negative")

    @classmethod
    def of(
        cls,
        instrument: str,
        timeframe: Timeframe | str,
        open_time: datetime,
        open: Decimal | str | int | float,
        high: Decimal | str | int | float,
        low: Decimal | str | int | float,
        close: Decimal | str | int | float,
        volume: Decimal | str | int | float = 0,
        source: str = "",
    ) -> "Bar":
        """Convenience constructor for fixed-length bars (close = open + duration)."""
        tf = Timeframe.parse(timeframe)
        start = ensure_utc(open_time)
        return cls(
            instrument=instrument,
            timeframe=tf,
            open_time=start,
            close_time=start + tf.duration,
            open=_dec(open),
            high=_dec(high),
            low=_dec(low),
            close=_dec(close),
            volume=_dec(volume),
            source=source,
        )


@dataclass(frozen=True, slots=True)
class Quote:
    instrument: str
    ts: datetime
    bid: Decimal
    ask: Decimal
    source: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "ts", ensure_utc(self.ts))
        if self.ask < self.bid:
            raise ValueError(
                f"crossed quote for {self.instrument}: bid {self.bid} > ask {self.ask}"
            )

    @property
    def mid(self) -> Decimal:
        return (self.bid + self.ask) / 2

    @property
    def spread(self) -> Decimal:
        return self.ask - self.bid


def _dec(value: Decimal | str | int | float) -> Decimal:
    """Convert to Decimal; floats go through ``str`` so 0.1 stays 0.1."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(value)
