"""A fake market-data provider and a fake clock for the forward paper runtime.

``FakeProvider`` follows the ``MarketDataProvider`` port: it serves only bars
that have *closed* (plus a delivery delay) by the fake clock, oldest first,
and can be told to fail, to deliver a bar late or to page its answers.
``FakeTime`` is the clock plus the runtime's ``wait``: waiting advances time,
runs scheduled actions (e.g. flip a kill switch at 10:15) and stops the
runtime at a given instant. Nothing here touches the network.
"""

from collections.abc import Awaitable, Callable, Iterable
from datetime import datetime, timedelta
from decimal import Decimal

from kterminal.core.clock import Clock
from kterminal.domain.market import Bar
from kterminal.marketdata.base import MarketDataError
from kterminal.marketdata.synthetic import synthetic_bars

type Action = Callable[[], Awaitable[None]]


class FakeTime:
    def __init__(self, start: datetime) -> None:
        self.current = start
        self.stop_at: datetime | None = None
        self.actions: list[tuple[datetime, Action]] = []

    def now(self) -> datetime:
        return self.current

    def at(self, when: datetime, action: Action) -> None:
        self.actions.append((when, action))
        self.actions.sort(key=lambda item: item[0])

    async def wait(self, seconds: float) -> bool:
        """Advance the clock (runs due actions); True once the stop time is reached."""
        target = self.current + timedelta(seconds=seconds)
        while self.actions and self.actions[0][0] <= target:
            when, action = self.actions.pop(0)
            self.current = max(self.current, when)
            await action()
        self.current = target
        return self.stop_at is not None and self.current >= self.stop_at


class FakeProvider:
    def __init__(
        self, name: str, bars: Iterable[Bar], clock: Clock, *, delay_s: float = 1.0
    ) -> None:
        self.name = name
        self.clock = clock
        self.delay = timedelta(seconds=delay_s)
        self.bars: dict[str, list[Bar]] = {}
        for bar in sorted(bars, key=lambda b: b.open_time):
            self.bars.setdefault(bar.instrument, []).append(bar)
        self.failures: dict[str, int] = {}  # instrument → calls that will raise
        self.held: dict[tuple[str, datetime], datetime] = {}  # bar → available from
        self.page: int | None = None  # at most this many bars per call
        self.calls: list[tuple[str, str, datetime]] = []
        self.closed = False

    def supports(self, instrument: str) -> bool:
        return instrument in self.bars

    def hold(self, instrument: str, open_time: datetime, until: datetime) -> None:
        """Deliver this bar only from ``until`` on (a late bar)."""
        self.held[(instrument, open_time)] = until

    def _available(self, bar: Bar) -> bool:
        ready = self.held.get((bar.instrument, bar.open_time), bar.close_time + self.delay)
        return self.clock.now() >= ready

    def _check(self, call: str, instrument: str, at: datetime) -> None:
        self.calls.append((call, instrument, at))
        if self.failures.get(instrument, 0) > 0:
            self.failures[instrument] -= 1
            raise MarketDataError(f"{self.name}: HTTP 503 for {instrument}")

    async def history(self, instrument: str, start: datetime, end: datetime) -> list[Bar]:
        self._check("history", instrument, start)
        return [
            b
            for b in self.bars.get(instrument, [])
            if start <= b.open_time < end and self._available(b)
        ]

    async def latest(self, instrument: str, since: datetime) -> list[Bar]:
        self._check("latest", instrument, since)
        found = [
            b for b in self.bars.get(instrument, []) if b.open_time >= since and self._available(b)
        ]
        return found if self.page is None else found[: self.page]

    async def aclose(self) -> None:
        self.closed = True


def market_bars(
    symbol: str,
    *,
    start: datetime,
    minutes: int,
    price: str,
    tick: str,
    seed: int,
    is_open: Callable[[datetime], bool] | None = None,
    source: str,
) -> list[Bar]:
    """Synthetic 1m bars for ``minutes`` wall-clock minutes from ``start`` (only while open)."""
    end = start + timedelta(minutes=minutes)
    generated = synthetic_bars(
        symbol,
        start=start,
        count=minutes,
        start_price=Decimal(price),
        tick_size=Decimal(tick),
        seed=seed,
        is_open=is_open,
        source=source,
        volatility=0.002,
    )
    return [b for b in generated if b.open_time < end]
