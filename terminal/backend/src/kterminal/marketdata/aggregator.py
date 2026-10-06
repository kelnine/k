"""Multi-timeframe bar aggregation.

One base stream (e.g. 1-minute bars) is turned into every timeframe the lab
needs (5m, 15m, 1h …) by a single aggregator, so every strategy instance sees
exactly the same bars. A higher-timeframe bar is emitted only when its period
is complete — when the base bar that ends exactly at the period boundary
arrives, or, if data is missing at the end of a period (market closed, feed
gap), as soon as a later base bar proves the period is over. Partial bars are
never emitted.

Intraday timeframes are aligned to the UTC epoch (``Timeframe.floor``);
session-anchored daily bars arrive with the market-data layer in Phase 3/5.
"""

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal

from kterminal.domain.market import Bar
from kterminal.domain.timeframes import Timeframe


@dataclass(frozen=True, slots=True)
class _Partial:
    bar: Bar  # running OHLCV; close_time is the period end


class BarAggregator:
    def __init__(self, base: Timeframe, targets: Iterable[Timeframe]) -> None:
        if not base.is_intraday:
            raise ValueError("the base timeframe must be intraday")
        self.base = base
        self.targets = tuple(sorted({t for t in targets if t != base}))
        for target in self.targets:
            if not target.is_intraday:
                raise ValueError(f"{target}: only intraday aggregation is supported so far")
            if not base.divides(target):
                raise ValueError(f"{target} is not a whole multiple of the base timeframe {base}")
        self._partials: dict[tuple[str, Timeframe], _Partial] = {}
        self._last_open: dict[str, datetime] = {}

    @property
    def timeframes(self) -> tuple[Timeframe, ...]:
        return (self.base, *self.targets)

    def add(self, bar: Bar) -> list[Bar]:
        """Add one closed base bar; return every bar (base included) that is now closed,
        ordered by close time."""
        if bar.timeframe != self.base:
            raise ValueError(f"expected {self.base} bars, got {bar.timeframe}")
        if not self.base.is_aligned(bar.open_time):
            raise ValueError(f"base bar not aligned to {self.base}: {bar.open_time.isoformat()}")
        last = self._last_open.get(bar.instrument)
        if last is not None and bar.open_time <= last:
            raise ValueError(
                f"{bar.instrument}: base bars must be strictly increasing in time "
                f"({bar.open_time.isoformat()} after {last.isoformat()})"
            )
        self._last_open[bar.instrument] = bar.open_time

        closed: list[Bar] = [bar]
        for target in self.targets:
            key = (bar.instrument, target)
            bucket_open = target.floor(bar.open_time)
            partial = self._partials.get(key)
            if partial is not None and partial.bar.open_time != bucket_open:
                closed.append(partial.bar)  # period ended without its last base bar (gap)
                partial = None
            if partial is None:
                merged = Bar(
                    instrument=bar.instrument,
                    timeframe=target,
                    open_time=bucket_open,
                    close_time=bucket_open + target.duration,
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=bar.volume,
                    source=bar.source,
                )
            else:
                previous = partial.bar
                merged = replace(
                    previous,
                    high=max(previous.high, bar.high),
                    low=min(previous.low, bar.low),
                    close=bar.close,
                    volume=previous.volume + bar.volume,
                )
            if bar.close_time >= merged.close_time:
                closed.append(merged)
                self._partials.pop(key, None)
            else:
                self._partials[key] = _Partial(merged)
        closed.sort(key=lambda b: (b.close_time, b.timeframe))
        return closed


def batches_by_close(bars: Iterable[Bar]) -> Iterator[list[Bar]]:
    """Group an ordered stream of bars into lists that closed at the same instant."""
    batch: list[Bar] = []
    for bar in bars:
        if batch and bar.close_time != batch[0].close_time:
            yield batch
            batch = []
        batch.append(bar)
    if batch:
        yield batch


def aggregate_stream(
    base_bars: Iterable[Bar], base: Timeframe, targets: Sequence[Timeframe]
) -> Iterator[list[Bar]]:
    """Base bars (possibly several instruments, time-ordered) → batches of closed bars.

    Bars of different instruments that close at the same instant land in the
    same batch, which is how the lab keeps every instance on the same clock.
    """
    aggregator = BarAggregator(base, targets)
    pending: dict[datetime, list[Bar]] = {}

    def flush(up_to: datetime | None) -> Iterator[list[Bar]]:
        for close_time in sorted(t for t in pending if up_to is None or t <= up_to):
            yield sorted(pending.pop(close_time), key=lambda b: (b.instrument, b.timeframe))

    for bar in base_bars:
        # A base bar opening at T proves every period ending at or before T is complete
        # for all instruments (bars of the same instant share a batch).
        yield from flush(bar.open_time)
        for closed in aggregator.add(bar):
            pending.setdefault(closed.close_time, []).append(closed)
    yield from flush(None)


def total_volume(bars: Iterable[Bar]) -> Decimal:
    return sum((b.volume for b in bars), Decimal(0))
