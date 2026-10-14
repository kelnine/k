"""The live bar feed of a forward paper session: one closed minute at a time.

:class:`LiveFeed` turns polled market-data providers into **minute batches**:
all base (1m) bars that opened in one minute, across the session's
instruments. For minute ``M`` (bars ``[M, M+1m)``) it

1. waits until shortly after the minute has closed (``poll_delay_s``);
2. polls each provider for that instrument's bars since its newest bar
   (``MarketDataProvider.latest``), keeping bars of the current and later
   minutes;
3. hands out the batch as soon as every instrument it waits for has delivered
   minute ``M`` — or a later bar, which proves ``M`` is a gap at the venue —
   or when ``batch_timeout_s`` after the close has passed.

It waits only for instruments whose market is open at ``M`` (catalog trading
calendars) and whose provider is not backing off after an error. A bar that
arrives after its minute was handed out is **dropped and logged**: the lab
never processes bars out of order. A failing provider is retried with
exponential back-off; its instrument is reported ``stale`` while everyone
else carries on. After a restart the feed starts at the first unprocessed
minute and catches up without waiting (every past minute's deadline has
already passed).

Time comes from an injected clock and every wait goes through an injected
``wait`` (which returns ``True`` when the runtime is stopping), so tests drive
the feed with a fake clock.
"""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from kterminal.core.clock import Clock
from kterminal.domain.market import Bar
from kterminal.domain.sessions import TradingCalendar
from kterminal.domain.timeframes import M1
from kterminal.marketdata.base import MarketDataProvider
from kterminal.observability.logging import get_logger

_log = get_logger(__name__)

MINUTE = timedelta(minutes=1)

type Wait = Callable[[float], Awaitable[bool]]
"""Sleep for up to N seconds; True means "stop requested"."""


@dataclass(frozen=True, slots=True)
class FeedConfig:
    """Timing of the live loop (``forward:`` in lab.yaml sets the first three)."""

    poll_delay_s: float = 2.0  # first poll this long after the minute closed
    poll_interval_s: float = 1.0  # between polls while instruments are missing
    batch_timeout_s: float = 20.0  # after the close: process without the missing ones
    late_window_minutes: int = 10  # bars this far before the cursor are re-requested
    backoff_initial_s: float = 5.0
    backoff_max_s: float = 300.0


@dataclass
class InstrumentFeed:
    symbol: str
    provider: MarketDataProvider | None
    calendar: TradingCalendar | None
    newest_open: datetime | None = None  # newest bar received (processed or buffered)
    last_bar_open: datetime | None = None  # newest bar handed out
    state: str = "ok"  # ok | stale | closed | no_provider
    last_error: str | None = None
    failures: int = 0
    retry_at: datetime | None = None
    polled_at: datetime | None = None
    buffer: dict[datetime, Bar] = field(default_factory=dict)

    @property
    def provider_name(self) -> str | None:
        return None if self.provider is None else self.provider.name

    def is_open(self, minute: datetime) -> bool:
        return self.calendar is None or self.calendar.is_open(minute)


@dataclass(frozen=True, slots=True)
class MinuteBatch:
    minute: datetime  # open time of the minute's bars
    bars: tuple[Bar, ...]  # one per instrument that delivered, by instrument
    missing: tuple[str, ...] = ()  # waited for, not delivered in time
    late: tuple[Bar, ...] = ()  # arrived after their minute was handed out (dropped)

    @property
    def close_time(self) -> datetime:
        return self.minute + MINUTE


class LiveFeed:
    def __init__(
        self,
        instruments: Sequence[str],
        providers: Mapping[str, MarketDataProvider],
        calendars: Mapping[str, TradingCalendar],
        *,
        start: datetime,
        clock: Clock,
        wait: Wait,
        config: FeedConfig | None = None,
        last_bars: Mapping[str, datetime] | None = None,
        unavailable: Mapping[str, str] | None = None,
    ) -> None:
        """``unavailable``: why an instrument has no provider (e.g. no OANDA token),
        reported as its ``last_error``."""
        if not M1.is_aligned(start):
            raise ValueError(f"the feed must start on a minute: {start.isoformat()}")
        self.cursor = start  # the next minute to hand out
        self._start = start
        self.clock = clock
        self.config = config or FeedConfig()
        self._wait = wait
        self._late: list[Bar] = []
        last = last_bars or {}
        reasons = unavailable or {}
        self.instruments: dict[str, InstrumentFeed] = {}
        for symbol in instruments:
            provider = providers.get(symbol)
            reason = None
            if provider is not None and not provider.supports(symbol):
                _log.warning("paper.feed.unsupported", instrument=symbol, provider=provider.name)
                reason = f"{provider.name} does not support {symbol}"
                provider = None
            elif provider is None:
                reason = reasons.get(symbol, "no market-data provider configured")
            feed = InstrumentFeed(
                symbol,
                provider,
                calendars.get(symbol),
                newest_open=last.get(symbol),
                last_bar_open=last.get(symbol),
                state="ok" if provider is not None else "no_provider",
                last_error=reason,
            )
            self.instruments[symbol] = feed

    # ── the loop ────────────────────────────────────────────────────────────
    async def next_batch(self) -> MinuteBatch | None:
        """The next minute's bars, or ``None`` when the runtime is stopping."""
        minute = self.cursor
        close = minute + MINUTE
        if await self._sleep_until(close + timedelta(seconds=self.config.poll_delay_s)):
            return None
        deadline = close + timedelta(seconds=self.config.batch_timeout_s)
        while True:
            await self._poll(minute)
            waiting = self._waiting_for(minute)
            if not waiting or self.clock.now() >= deadline:
                break
            pause = min(self.config.poll_interval_s, (deadline - self.clock.now()).total_seconds())
            if await self._wait(max(pause, 0.0)):
                return None
        return self._hand_out(minute, waiting)

    # ── status ──────────────────────────────────────────────────────────────
    def status(self) -> dict[str, dict[str, object]]:
        """Per instrument: provider, newest processed bar, lag, state, last error."""
        now = self.clock.now()
        result: dict[str, dict[str, object]] = {}
        for symbol, feed in sorted(self.instruments.items()):
            last = feed.last_bar_open
            result[symbol] = {
                "provider": feed.provider_name,
                "last_bar_open": None if last is None else last.isoformat(),
                "lag_seconds": None
                if last is None
                else round((now - (last + MINUTE)).total_seconds(), 1),
                "state": self._state(feed),
                "last_error": feed.last_error,
            }
        return result

    def last_bars(self) -> dict[str, datetime]:
        return {
            s: f.last_bar_open for s, f in self.instruments.items() if f.last_bar_open is not None
        }

    # ── internals ───────────────────────────────────────────────────────────
    def _state(self, feed: InstrumentFeed) -> str:
        if feed.provider is None:
            return "no_provider"
        if feed.retry_at is not None:
            return "stale"  # backing off after a provider error
        if not feed.is_open(self.cursor):
            return "closed"
        return feed.state  # ok, or stale while it misses minutes

    def _expected(self, feed: InstrumentFeed, minute: datetime) -> bool:
        """Whether the batch waits for this instrument: it has a working provider and
        its market is open in this minute."""
        if feed.provider is None or not feed.is_open(minute):
            return False
        return feed.retry_at is None or feed.retry_at <= self.clock.now()

    def _waiting_for(self, minute: datetime) -> list[str]:
        return [
            symbol
            for symbol, feed in self.instruments.items()
            if self._expected(feed, minute)
            and (feed.newest_open is None or feed.newest_open < minute)
        ]

    async def _poll(self, minute: datetime) -> None:
        now = self.clock.now()
        interval = timedelta(seconds=self.config.poll_interval_s)
        for symbol in self._waiting_for(minute):
            feed = self.instruments[symbol]
            if feed.polled_at is not None and now - feed.polled_at < interval:
                continue  # it had nothing new a moment ago: ask again after the interval
            await self._poll_one(feed)

    async def _poll_one(self, feed: InstrumentFeed) -> None:
        provider = feed.provider
        if provider is None:  # pragma: no cover - only expected instruments are polled
            return
        # Since its newest bar, but never before the feed's start (warm-up bars and minutes
        # processed before a restart are not asked for again) nor further back than the
        # late window (an instrument that was closed for days).
        floor = self.cursor - timedelta(minutes=self.config.late_window_minutes)
        newest = feed.newest_open
        since = max(self._start, floor, self._start if newest is None else newest + MINUTE)
        try:
            bars = await provider.latest(feed.symbol, since)
        except Exception as exc:  # a provider failure must never stop the others
            self._failed(feed, exc)
            return
        feed.failures = 0
        feed.retry_at = None
        feed.last_error = None
        for bar in bars:
            self._receive(feed, bar, provider.name)
        # Throttle only an instrument that had nothing new; one that delivered (a page of
        # a catch-up, say) is asked again at once.
        feed.polled_at = self.clock.now() if feed.newest_open == newest else None

    def _receive(self, feed: InstrumentFeed, bar: Bar, provider: str) -> None:
        if bar.instrument != feed.symbol or bar.timeframe != M1 or not M1.is_aligned(bar.open_time):
            _log.warning(
                "paper.feed.unexpected_bar",
                instrument=feed.symbol,
                got=bar.instrument,
                timeframe=bar.timeframe.code,
                open_time=bar.open_time.isoformat(),
            )
            return
        if not bar.source:
            bar = Bar(
                instrument=bar.instrument,
                timeframe=bar.timeframe,
                open_time=bar.open_time,
                close_time=bar.close_time,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                source=provider,
            )
        if feed.newest_open is None or bar.open_time > feed.newest_open:
            feed.newest_open = bar.open_time
        if bar.open_time >= self.cursor:
            feed.buffer[bar.open_time] = bar  # a re-delivered, not yet processed bar: newest wins
            return
        if feed.last_bar_open is not None and bar.open_time <= feed.last_bar_open:
            return  # already processed (re-delivered by an overlapping poll)
        self._late.append(bar)
        _log.warning(
            "paper.feed.late_bar_dropped",
            instrument=feed.symbol,
            bar_open=bar.open_time.isoformat(),
            processed_through=self.cursor.isoformat(),
        )

    def _failed(self, feed: InstrumentFeed, exc: Exception) -> None:
        feed.failures += 1
        delay = min(
            self.config.backoff_initial_s * 2 ** (feed.failures - 1), self.config.backoff_max_s
        )
        feed.retry_at = self.clock.now() + timedelta(seconds=delay)
        feed.state = "stale"
        feed.last_error = f"{type(exc).__name__}: {exc}"[:500]
        _log.warning(
            "paper.feed.provider_error",
            instrument=feed.symbol,
            provider=feed.provider_name,
            error=feed.last_error,
            retry_in_s=delay,
        )

    def _hand_out(self, minute: datetime, waiting: Sequence[str]) -> MinuteBatch:
        bars: list[Bar] = []
        for symbol in sorted(self.instruments):
            feed = self.instruments[symbol]
            bar = feed.buffer.pop(minute, None)
            if bar is not None:
                bars.append(bar)
                feed.last_bar_open = minute
                feed.state = "ok"
        missing = tuple(sorted(waiting))
        for symbol in missing:
            feed = self.instruments[symbol]
            feed.state = "stale"
            _log.warning("paper.feed.minute_missing", instrument=symbol, minute=minute.isoformat())
        late, self._late = tuple(self._late), []
        self.cursor = minute + MINUTE
        return MinuteBatch(minute, tuple(bars), missing, late)

    async def _sleep_until(self, when: datetime) -> bool:
        seconds = (when - self.clock.now()).total_seconds()
        if seconds <= 0:
            return False
        return await self._wait(seconds)


__all__ = ["FeedConfig", "InstrumentFeed", "LiveFeed", "MinuteBatch", "Wait"]
