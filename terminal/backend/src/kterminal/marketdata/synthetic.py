"""Deterministic synthetic market data for demos and tests.

A seeded random walk — by default a *pure* one, on which no strategy has an
edge: any consistent profit on it reveals a bias (look-ahead, favourable
fills) rather than skill. ``regime_change_probability > 0`` adds persistent
trend regimes, which flatter trend-following strategies by construction. The
same seed always produces the same bars. This is not market data and is
never used for any result that claims to be real.
"""

from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from decimal import Decimal

import numpy as np

from kterminal.core.clock import ensure_utc
from kterminal.domain.instruments import quantize_to_step
from kterminal.domain.market import Bar
from kterminal.domain.timeframes import M1, Timeframe


def synthetic_bars(
    instrument: str,
    *,
    start: datetime,
    count: int,
    start_price: Decimal,
    tick_size: Decimal,
    timeframe: Timeframe = M1,
    volatility: float = 0.0006,
    seed: int = 7,
    regime_change_probability: float = 0.0,
    is_open: Callable[[datetime], bool] | None = None,
    source: str = "synthetic",
) -> Iterator[Bar]:
    """Yield ``count`` bars (skipping instants where ``is_open`` is False)."""
    if count < 0:
        raise ValueError("count must be >= 0")
    rng = np.random.default_rng(seed)
    t = timeframe.floor(ensure_utc(start))
    price = float(start_price)
    drift = 0.0
    produced = 0
    step = timeframe.duration
    guard = 0
    while produced < count:
        guard += 1
        if guard > count * 20 + 10_000:
            raise RuntimeError("calendar closed for too long while generating bars")
        if is_open is not None and not is_open(t):
            t += step
            continue
        if rng.random() < regime_change_probability:  # occasional trend regime change
            drift = float(rng.normal(0.0, volatility / 3))
        returns = rng.normal(drift, volatility, size=4)
        path = price * np.cumprod(1 + returns)
        open_ = price
        close = float(path[-1])
        wick_up, wick_down = (abs(float(x)) for x in rng.normal(0, volatility / 4, size=2))
        high = max(open_, close, float(path.max())) * (1 + wick_up)
        low = min(open_, close, float(path.min())) * (1 - wick_down)
        o, h, low_d, c = (
            quantize_to_step(Decimal(repr(v)), tick_size) for v in (open_, high, low, close)
        )
        h = max(h, o, c)
        low_d = min(low_d, o, c)
        yield Bar(
            instrument=instrument,
            timeframe=timeframe,
            open_time=t,
            close_time=t + step,
            open=o,
            high=h,
            low=low_d,
            close=c,
            volume=Decimal(int(rng.integers(50, 500))),
            source=source,
        )
        price = float(c)
        produced += 1
        t += step


def merge_streams(*streams: Iterator[Bar]) -> list[Bar]:
    """Merge per-instrument streams into one time-ordered list (ties by instrument)."""
    merged = [bar for stream in streams for bar in stream]
    merged.sort(key=lambda b: (b.open_time, b.instrument))
    return merged


def minutes(n: int) -> timedelta:
    return timedelta(minutes=n)
