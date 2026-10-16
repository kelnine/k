"""Shared machinery of the HTTP market-data providers.

Every provider pages through its venue's candle endpoint in **windows** of at most
``window_bars`` minutes, so a request can never ask for more candles than the venue
returns in one response, whatever the venue's ordering (Bybit and Coinbase answer
newest first) or its inclusive/exclusive reading of the end bound. Whatever a venue
sends outside the window — the forming candle, a neighbouring one — is ignored, and
the pieces are merged by open time (a minute delivered twice with different values is
an error, never a silent choice).

Closedness is decided against an injected :class:`~kterminal.core.clock.Clock`: a bar
is closed once its minute has ended plus ``close_delay_s`` (clock skew between this host
and the venue, late prints). Requests never reach past that point, and venue flags such
as OANDA's ``complete`` are honoured on top.

Requests go through a client-side :class:`RequestBudget` sized well below each venue's
published limits, and are retried with exponential backoff on HTTP 429, any 5xx and
network errors, honouring ``Retry-After``. Other HTTP statuses (including redirects, which
are not followed) fail at once with the venue's own error message. Nothing here logs
request headers, so API tokens never reach the logs.
"""

import asyncio
import json
import math
import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, NoReturn

import httpx

from kterminal import __version__
from kterminal.config.settings import MarketDataSettings
from kterminal.core.clock import Clock, SystemClock, ensure_utc
from kterminal.domain.market import Bar
from kterminal.domain.timeframes import M1
from kterminal.marketdata.base import MarketDataError
from kterminal.observability.logging import get_logger

MINUTE = timedelta(minutes=1)
MINUTE_MS = 60_000

Sleep = Callable[[float], Awaitable[None]]
Monotonic = Callable[[], float]

# Retried: rate limiting and every server-side error (5xx, including CDN errors such as
# Cloudflare's 52x). Other statuses fail at once.
RATE_LIMITED = 429
# A Retry-After longer than this is not waited out: the call fails and says so.
MAX_RETRY_AFTER_S = 300.0

_log = get_logger("kterminal.marketdata")


@dataclass(frozen=True, slots=True)
class ProviderOptions:
    """Timeouts, retries and the closed-bar delay shared by every provider."""

    timeout_s: float = 10.0
    max_retries: int = 5
    backoff_initial_s: float = 0.5
    backoff_max_s: float = 30.0
    close_delay_s: float = 2.0

    @classmethod
    def from_settings(cls, settings: MarketDataSettings) -> "ProviderOptions":
        return cls(
            timeout_s=settings.request_timeout_s,
            max_retries=settings.max_retries,
            backoff_initial_s=settings.backoff_initial_s,
            backoff_max_s=settings.backoff_max_s,
            close_delay_s=settings.close_delay_s,
        )

    def backoff(self, attempt: int) -> float:
        """Delay before retry ``attempt`` (0-based): initial × 2^attempt, capped."""
        return min(self.backoff_max_s, self.backoff_initial_s * 2.0**attempt)


class RequestBudget:
    """A client-side token bucket: ``per_minute`` units refill continuously, at most
    ``burst`` are banked. A request costs the venue's weight for it (1 for venues that
    count requests). ``pause`` stops all requests for a while (e.g. when a venue reports
    that the IP's budget is nearly used up)."""

    def __init__(
        self,
        per_minute: float,
        burst: float,
        *,
        monotonic: Monotonic = time.monotonic,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        if per_minute <= 0 or burst <= 0:
            raise ValueError("a request budget needs a positive rate and burst")
        self._rate = per_minute / 60
        self._capacity = float(burst)
        self._tokens = float(burst)
        self._monotonic = monotonic
        self._sleep = sleep
        self._updated = monotonic()
        self._paused_until = -math.inf
        self._lock = asyncio.Lock()

    async def acquire(self, cost: float = 1.0) -> None:
        cost = min(cost, self._capacity)
        async with self._lock:
            while True:
                now = self._monotonic()
                refill = (now - self._updated) * self._rate
                self._tokens = min(self._capacity, self._tokens + refill)
                self._updated = now
                wait = self._paused_until - now
                if wait <= 0:
                    if self._tokens >= cost - 1e-9:
                        self._tokens -= cost
                        return
                    wait = (cost - self._tokens) / self._rate
                await self._sleep(wait)

    def pause(self, seconds: float) -> None:
        self._paused_until = max(self._paused_until, self._monotonic() + seconds)


class PayloadError(ValueError):
    """A response is not shaped as the venue documents it."""


class HttpProvider(ABC):
    """Base class of the REST providers. Subclasses describe the venue (class attributes)
    and implement :meth:`_fetch_window`; paging, merging, closedness, pacing and retries
    live here."""

    name: str
    default_base_url: str
    window_bars: int  # minutes per request; never above the venue's per-response maximum
    budget_per_minute: float  # request cost units per minute (well below the venue limit)
    budget_burst: float
    history_depth: timedelta | None = None  # how far back the venue keeps 1m bars

    def __init__(
        self,
        symbols: Mapping[str, str],
        *,
        options: ProviderOptions | None = None,
        clock: Clock | None = None,
        base_url: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Sleep = asyncio.sleep,
        monotonic: Monotonic = time.monotonic,
    ) -> None:
        self._symbols = dict(symbols)
        self._options = options or ProviderOptions()
        self._clock: Clock = clock or SystemClock()
        self._sleep = sleep
        self._budget = RequestBudget(
            self.budget_per_minute, self.budget_burst, monotonic=monotonic, sleep=sleep
        )
        self._client = httpx.AsyncClient(
            base_url=base_url or self.default_base_url,
            timeout=self._options.timeout_s,
            transport=transport,
            headers={
                "User-Agent": f"kterminal/{__version__}",
                "Accept": "application/json",
                **self._headers(),
            },
            follow_redirects=False,
        )
        self._closed = False

    # ── the MarketDataProvider port ─────────────────────────────────────────
    def supports(self, instrument: str) -> bool:
        return instrument in self._symbols

    @property
    def instruments(self) -> tuple[str, ...]:
        return tuple(self._symbols)

    def symbol(self, instrument: str) -> str:
        try:
            return self._symbols[instrument]
        except KeyError:
            served = ", ".join(sorted(self._symbols)) or "nothing"
            raise MarketDataError(
                f"{self.name} does not serve {instrument} (configured: {served})"
            ) from None

    async def history(self, instrument: str, start: datetime, end: datetime) -> list[Bar]:
        symbol = self.symbol(instrument)
        start, end = ensure_utc(start), ensure_utc(end)
        now = self._clock.now()
        first = ceil_minute(start)
        last = min(ceil_minute(end), self.closed_before(now)) - MINUTE  # inclusive open time
        if self.history_depth is not None:
            earliest = floor_minute(now) - self.history_depth
            if first < earliest and first <= last:
                _log.warning(
                    "marketdata.history_truncated",
                    provider=self.name,
                    instrument=instrument,
                    requested_from=first.isoformat(),
                    available_from=earliest.isoformat(),
                )
            first = max(first, earliest)
        merged: dict[datetime, Bar] = {}
        cursor = first
        while cursor <= last:
            window_last = min(cursor + (self.window_bars - 1) * MINUTE, last)
            try:
                batch = await self._fetch_window(instrument, symbol, cursor, window_last)
            except PayloadError as exc:
                raise MarketDataError(
                    f"{self.name}: unexpected response for {symbol}: {exc}"
                ) from None
            for bar in batch:
                if cursor <= bar.open_time <= window_last:
                    self._merge(merged, bar)
            cursor = window_last + MINUTE
        return [merged[key] for key in sorted(merged)]

    async def latest(self, instrument: str, since: datetime) -> list[Bar]:
        return await self.history(instrument, since, self._clock.now())

    async def aclose(self) -> None:
        if not self._closed:
            self._closed = True
            await self._client.aclose()

    # ── for subclasses ──────────────────────────────────────────────────────
    @abstractmethod
    async def _fetch_window(
        self, instrument: str, symbol: str, first: datetime, last: datetime
    ) -> list[Bar]:
        """Bars with ``first <= open_time <= last`` (≤ ``window_bars`` minutes), any order.
        Bars outside the window are ignored by the caller; unclosed ones must be dropped
        here when the venue flags them (closedness by time is already guaranteed)."""

    def _headers(self) -> dict[str, str]:
        """Extra default headers (e.g. authorization)."""
        return {}

    def _observe(self, response: httpx.Response) -> None:  # noqa: B027 - optional hook
        """Inspect every response (e.g. rate-limit headers). Default: nothing."""

    def _payload_retry_reason(self, payload: Any) -> str | None:
        """For venues that report errors inside a 200 response: a reason to retry, or
        ``None`` if the payload is usable. Raise :class:`MarketDataError` for a
        non-retryable venue error."""
        return None

    def _status_hint(self, status: int) -> str | None:
        """Extra explanation for an HTTP error status."""
        if status == 451:
            return (
                "the venue refuses requests from this location; set "
                f"KT_MARKETDATA__DISABLED_PROVIDERS={self.name} to use the instruments' "
                "alternative sources"
            )
        if status == 401:
            return "the credentials were rejected"
        return None

    def closed_before(self, now: datetime) -> datetime:
        """Bars opening before this instant have closed (their minute ended at least
        ``close_delay_s`` ago)."""
        return floor_minute(now - timedelta(seconds=self._options.close_delay_s))

    def _bar(
        self,
        instrument: str,
        open_time: datetime,
        open_: Decimal,
        high: Decimal,
        low: Decimal,
        close: Decimal,
        volume: Decimal,
    ) -> Bar:
        try:
            return Bar(
                instrument=instrument,
                timeframe=M1,
                open_time=open_time,
                close_time=open_time + MINUTE,
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=volume,
                source=self.name,
            )
        except ValueError as exc:
            raise PayloadError(str(exc)) from None

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str | int] | None = None,
        json_body: Any = None,
        cost: float = 1.0,
    ) -> Any:
        """One API call with pacing and retries; returns the decoded JSON (floats as
        ``Decimal``, so prices are exactly what the venue sent)."""
        where = f"{self.name} {method} {path}"
        attempt = 0
        while True:
            await self._budget.acquire(cost)
            retry_after: float | None = None
            try:
                response = await self._client.request(method, path, params=params, json=json_body)
            except httpx.TransportError as exc:
                reason = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
            except httpx.HTTPError as exc:
                raise MarketDataError(f"{where}: {type(exc).__name__}: {exc}") from None
            else:
                self._observe(response)
                status = response.status_code
                if status == RATE_LIMITED or status >= 500:
                    reason = f"HTTP {status}"
                    detail = venue_message(response)
                    if detail:
                        reason += f": {detail}"
                    retry_after = parse_retry_after(response)
                elif status >= 300:  # redirects are not followed: a moved API is an error
                    self._fail(where, response)
                else:
                    payload = decode_json(response, where)
                    payload_reason = self._payload_retry_reason(payload)
                    if payload_reason is None:
                        return payload
                    reason = payload_reason
            if attempt >= self._options.max_retries:
                tries = f"{attempt + 1} attempt" + ("s" if attempt else "")
                raise MarketDataError(f"{where}: {reason} (gave up after {tries})")
            if retry_after is not None and retry_after > MAX_RETRY_AFTER_S:
                raise MarketDataError(
                    f"{where}: {reason}; the venue asks to wait {retry_after:.0f} s — try later"
                )
            delay = max(self._options.backoff(attempt), retry_after or 0.0)
            _log.warning(
                "marketdata.retry",
                provider=self.name,
                path=path,
                reason=reason,
                attempt=attempt + 1,
                delay_s=round(delay, 3),
            )
            await self._sleep(delay)
            attempt += 1

    def _fail(self, where: str, response: httpx.Response) -> NoReturn:
        message = f"{where}: HTTP {response.status_code}"
        detail = venue_message(response)
        if detail:
            message += f": {detail}"
        hint = self._status_hint(response.status_code)
        if hint:
            message += f" — {hint}"
        raise MarketDataError(message)

    def _merge(self, merged: dict[datetime, Bar], bar: Bar) -> None:
        existing = merged.get(bar.open_time)
        if existing is not None and existing != bar:
            raise MarketDataError(
                f"{self.name}: two different {bar.instrument} bars for "
                f"{bar.open_time.isoformat()} ({existing} vs {bar})"
            )
        merged[bar.open_time] = bar


# ── helpers ──────────────────────────────────────────────────────────────────
def floor_minute(ts: datetime) -> datetime:
    return M1.floor(ts)


def ceil_minute(ts: datetime) -> datetime:
    floored = M1.floor(ts)
    return floored if floored == ts else floored + MINUTE


def to_ms(ts: datetime) -> int:
    return int(ensure_utc(ts).timestamp()) * 1000


def from_ms(value: Any, field: str) -> datetime:
    """A minute-aligned epoch-milliseconds time (int, or a string of digits as Bybit sends)."""
    millis = int_field(value, field)
    if millis % MINUTE_MS:
        raise PayloadError(f"{field} {millis} is not on a whole minute")
    return datetime.fromtimestamp(millis // 1000, tz=UTC)


def int_field(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise PayloadError(f"{field} must be an integer, got {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    raise PayloadError(f"{field} must be an integer, got {value!r}")


def decimal_field(value: Any, field: str) -> Decimal:
    """A price or volume: a JSON string or number, converted without a float round-trip
    (responses are decoded with ``parse_float=Decimal``)."""
    if isinstance(value, bool):
        raise PayloadError(f"{field} must be a number, got {value!r}")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, int):
        result = Decimal(value)
    elif isinstance(value, str):
        try:
            result = Decimal(value)
        except InvalidOperation:
            raise PayloadError(f"{field} must be a number, got {value!r}") from None
    else:
        raise PayloadError(f"{field} must be a number, got {value!r}")
    if not result.is_finite():
        raise PayloadError(f"{field} must be finite, got {value!r}")
    return result


def require(value: Any, kind: type | tuple[type, ...], field: str) -> Any:
    if not isinstance(value, kind):
        raise PayloadError(f"{field}: expected {_kind_name(kind)}, got {type(value).__name__}")
    return value


def _kind_name(kind: type | tuple[type, ...]) -> str:
    names = {list: "a list", dict: "an object", str: "a string", bool: "a boolean"}
    kinds = kind if isinstance(kind, tuple) else (kind,)
    return " or ".join(names.get(k, k.__name__) for k in kinds)


def _reject_constant(name: str) -> NoReturn:
    raise ValueError(f"non-finite number {name} in JSON")


def decode_json(response: httpx.Response, where: str) -> Any:
    try:
        return json.loads(response.content, parse_float=Decimal, parse_constant=_reject_constant)
    except ValueError as exc:  # json.JSONDecodeError is a ValueError
        raise MarketDataError(
            f"{where}: response is not valid JSON (HTTP {response.status_code}, "
            f"{len(response.content)} bytes): {exc}"
        ) from None


_MESSAGE_KEYS = ("msg", "message", "retMsg", "errorMessage", "error")
_CODE_KEYS = ("code", "retCode", "errorCode")


def venue_message(response: httpx.Response, limit: int = 300) -> str:
    """The venue's own error text: ``msg``/``message``/``retMsg``/``errorMessage`` (+ code)
    from a JSON body, else the body text, whitespace-collapsed and truncated."""
    try:
        payload = json.loads(response.content, parse_float=Decimal)
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        present = {k: v for k, v in payload.items() if v not in (None, "")}
        text = next((str(present[k]) for k in _MESSAGE_KEYS if k in present), "")
        code = next((present[k] for k in _CODE_KEYS if k in present), None)
        if text or code is not None:
            return f"{text} (code {code})" if code is not None else text
    text = " ".join(response.text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def parse_retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("retry-after")
    if raw is None:
        return None
    try:
        seconds = float(raw)
    except ValueError:
        return None  # an HTTP date: fall back to the exponential backoff
    return seconds if math.isfinite(seconds) and seconds >= 0 else None


__all__ = [
    "MINUTE",
    "HttpProvider",
    "Monotonic",
    "PayloadError",
    "ProviderOptions",
    "RequestBudget",
    "Sleep",
    "ceil_minute",
    "decimal_field",
    "floor_minute",
    "from_ms",
    "int_field",
    "require",
    "to_ms",
]
