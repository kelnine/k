"""Fake venue APIs for market-data provider tests (served through ``httpx.MockTransport``).

Each fake answers its venue's candle endpoint with the response shape the venue
documents (field order, types, string vs number prices, sort order, error payloads) and
the documented range semantics:

* Binance ``/fapi/v1/klines`` and ``/api/v3/klines`` — oldest first, ``startTime`` ≤ open
  time ≤ ``endTime``, at most ``limit`` (max 1,500 / 1,000) from ``startTime``;
* Bybit v5 ``/v5/market/kline`` — newest first, ``start`` inclusive on the start time,
  ``end`` inclusive (or, with ``end_exclusive``, exclusive), max 1,000, errors as
  ``retCode``/``retMsg`` inside HTTP 200;
* Coinbase Exchange ``/products/{id}/candles`` — newest first, ``[time, low, high, open,
  close, volume]`` with JSON numbers, ``start``/``end`` inclusive, more than 300 buckets
  rejected with HTTP 400;
* Hyperliquid ``POST /info`` ``candleSnapshot`` — oldest first, dicts of strings, only the
  most recent 5,000 candles exist;
* OANDA v20 ``/v3/instruments/{instrument}/candles`` — bearer token, ``complete`` flag,
  RFC 3339 nanosecond times, ``count`` above 5,000 rejected.

Every fake holds the candles of one symbol up to and including the minute that is still
forming at the venue's "now", and returns it like the real venue does when a request
reaches it. ``loose`` makes a fake ignore the request's end bound (returning everything up
to the forming candle), to prove providers keep only what they asked for. ``script`` holds
canned responses (or exceptions) served before normal handling, for 429s, 5xx and
network failures.

These fakes are shaped after the venues' published documentation and SDKs; they are not
recordings of live traffic (the venues are unreachable from the test environment).
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx

from kterminal.core.clock import Clock
from kterminal.domain.market import Bar
from kterminal.domain.timeframes import M1

MINUTE = timedelta(minutes=1)


@dataclass(frozen=True)
class Candle:
    """One venue candle with prices as the exact text the venue would send."""

    t: datetime
    o: str
    h: str
    low: str
    c: str
    v: str

    @property
    def ms(self) -> int:
        return int(self.t.timestamp()) * 1000

    def bar(self, instrument: str, source: str) -> Bar:
        return Bar(
            instrument=instrument,
            timeframe=M1,
            open_time=self.t,
            close_time=self.t + MINUTE,
            open=Decimal(self.o),
            high=Decimal(self.h),
            low=Decimal(self.low),
            close=Decimal(self.c),
            volume=Decimal(self.v),
            source=source,
        )


def make_candles(
    start: datetime,
    end: datetime,
    *,
    skip: frozenset[datetime] = frozenset(),
    base: str = "2650.12345",
    step: str = "0.01001",
    volume: str = "1.00000001",
    integer_volume: bool = False,
) -> list[Candle]:
    """Candles for every minute in ``[start, end]`` except ``skip`` (deterministic values
    with many decimals, so any float round-trip would show)."""
    result = []
    t = start
    i = 0
    while t <= end:
        if t not in skip:
            price = Decimal(base) + Decimal(step) * (i % 97) - Decimal(step) * (i % 13)
            o, c = price, price + Decimal("0.125")
            vol = str(i % 50 + 1) if integer_volume else str(Decimal(volume) * (i % 7 + 1))
            result.append(
                Candle(
                    t,
                    str(o),
                    str(max(o, c) + Decimal("0.5")),
                    str(min(o, c) - Decimal("0.25")),
                    str(c),
                    vol,
                )
            )
        t += MINUTE
        i += 1
    return result


Scripted = httpx.Response | Callable[[httpx.Request], httpx.Response]


@dataclass
class FakeVenue:
    symbol: str
    candles: list[Candle]
    clock: Clock
    loose: bool = False
    requests: list[httpx.Request] = field(default_factory=list)
    script: list[Scripted] = field(default_factory=list)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.script:
            item = self.script.pop(0)
            return item if isinstance(item, httpx.Response) else item(request)
        return self.handle(request)

    def handle(self, request: httpx.Request) -> httpx.Response:
        raise NotImplementedError

    def available(self) -> list[Candle]:
        """Candles that exist at the venue's now (the forming one included)."""
        now = self.clock.now()
        return [c for c in self.candles if c.t <= now]

    def between(self, first: datetime, last: datetime) -> list[Candle]:
        if self.loose:
            return self.available()
        return [c for c in self.available() if first <= c.t <= last]


def _from_ms(value: str) -> datetime:
    return datetime.fromtimestamp(int(value) / 1000, tz=UTC)


def network_error(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused", request=request)


def status(code: int, body: Any = None, *, headers: dict[str, str] | None = None) -> httpx.Response:
    if body is None:
        return httpx.Response(code, headers=headers)
    if isinstance(body, str):
        return httpx.Response(code, text=body, headers=headers)
    return httpx.Response(code, json=body, headers=headers)


# ── Binance ──────────────────────────────────────────────────────────────────
@dataclass
class BinanceFake(FakeVenue):
    path: str = "/fapi/v1/klines"
    max_limit: int = 1500
    used_weight: int = 10

    def handle(self, request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == self.path
        p = request.url.params
        if p["symbol"] != self.symbol:
            return status(400, {"code": -1121, "msg": "Invalid symbol."})
        assert p["interval"] == "1m"
        limit = int(p.get("limit", "500"))
        if not 1 <= limit <= self.max_limit:
            return status(
                400, {"code": -1130, "msg": "Data sent for parameter 'limit' is not valid."}
            )
        rows = self.between(_from_ms(p["startTime"]), _from_ms(p["endTime"]))[:limit]
        body = [
            [c.ms, c.o, c.h, c.low, c.c, c.v, c.ms + 59_999, "123.45", 42, "1.0", "2.0", "0"]
            for c in rows
        ]
        return httpx.Response(
            200, json=body, headers={"x-mbx-used-weight-1m": str(self.used_weight)}
        )


# ── Bybit ────────────────────────────────────────────────────────────────────
@dataclass
class BybitFake(FakeVenue):
    end_exclusive: bool = False  # the docs do not say; providers must work either way

    def handle(self, request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/v5/market/kline"
        p = request.url.params
        now_ms = int(self.clock.now().timestamp() * 1000)
        if p["symbol"] != self.symbol:
            return status(
                200,
                {
                    "retCode": 10001,
                    "retMsg": "params error: symbol invalid",
                    "result": {},
                    "retExtInfo": {},
                    "time": now_ms,
                },
            )
        assert p["category"] == "linear"
        assert p["interval"] == "1"
        limit = int(p.get("limit", "200"))
        assert 1 <= limit <= 1000
        end = int(p["end"]) - (1 if self.end_exclusive else 0)
        rows = self.between(_from_ms(p["start"]), _from_ms(str(end)))
        rows = sorted(rows, key=lambda c: c.t, reverse=True)[:limit]  # newest first
        return status(
            200,
            {
                "retCode": 0,
                "retMsg": "OK",
                "result": {
                    "symbol": self.symbol,
                    "category": "linear",
                    "list": [[str(c.ms), c.o, c.h, c.low, c.c, c.v, "1234.5"] for c in rows],
                },
                "retExtInfo": {},
                "time": now_ms,
            },
        )


# ── Coinbase ─────────────────────────────────────────────────────────────────
@dataclass
class CoinbaseFake(FakeVenue):
    def handle(self, request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        prefix, product, suffix = request.url.path.rsplit("/", 2)
        assert (prefix, suffix) == ("/products", "candles")
        if product != self.symbol:
            return status(404, {"message": "NotFound"})
        p = request.url.params
        assert p["granularity"] == "60"
        first = datetime.fromisoformat(p["start"])
        last = datetime.fromisoformat(p["end"])
        if (last - first) / MINUTE + 1 > 300:
            return status(
                400,
                {
                    "message": "granularity too small for the requested time range. "
                    "Count of aggregations requested exceeds 300"
                },
            )
        rows = sorted(self.between(first, last), key=lambda c: c.t, reverse=True)
        # JSON numbers, written exactly as the venue's text (a float would round them)
        text = (
            "["
            + ",".join(f"[{int(c.t.timestamp())},{c.low},{c.h},{c.o},{c.c},{c.v}]" for c in rows)
            + "]"
        )
        return httpx.Response(200, text=text, headers={"content-type": "application/json"})


# ── Hyperliquid ──────────────────────────────────────────────────────────────
@dataclass
class HyperliquidFake(FakeVenue):
    depth: int = 5000

    def available(self) -> list[Candle]:
        return super().available()[-self.depth :]

    def handle(self, request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/info"
        body = json.loads(request.content)
        if body.get("type") != "candleSnapshot" or "startTime" not in body.get("req", {}):
            return status(
                422, "Failed to deserialize the JSON body into the target type: req: missing field"
            )
        req = body["req"]
        assert req["interval"] == "1m"
        if req["coin"] != self.symbol:
            return status(200, [])
        rows = self.between(_from_ms(str(req["startTime"])), _from_ms(str(req["endTime"])))
        return status(
            200,
            [
                {
                    "t": c.ms,
                    "T": c.ms + 59_999,
                    "s": self.symbol,
                    "i": "1m",
                    "o": c.o,
                    "c": c.c,
                    "h": c.h,
                    "l": c.low,
                    "v": c.v,
                    "n": 17,
                }
                for c in rows
            ],
        )


# ── OANDA ────────────────────────────────────────────────────────────────────
@dataclass
class OandaFake(FakeVenue):
    token: str = "practice-token-123"
    venue_clock: Clock | None = None  # the venue's own clock (for "complete"), default clock

    def handle(self, request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        if request.headers.get("authorization") != f"Bearer {self.token}":
            return status(401, {"errorMessage": "Insufficient authorization to perform request."})
        prefix, instrument, suffix = request.url.path.rsplit("/", 2)
        assert (prefix, suffix) == ("/v3/instruments", "candles")
        if instrument != self.symbol:
            return status(400, {"errorMessage": "Invalid value specified for 'instrument'"})
        p = request.url.params
        assert p["price"] == "M"
        assert p["granularity"] == "M1"
        first = datetime.fromisoformat(p["from"])
        to = datetime.fromisoformat(p["to"])
        if (to - first) / MINUTE > 5000:
            return status(400, {"errorMessage": "Maximum value for 'count' exceeded"})
        rows = self.between(first, to - MINUTE) if not self.loose else self.available()
        venue_now = (self.venue_clock or self.clock).now()
        return status(
            200,
            {
                "instrument": self.symbol,
                "granularity": "M1",
                "candles": [
                    {
                        "complete": c.t + MINUTE <= venue_now,
                        "volume": int(c.v),
                        "time": c.t.strftime("%Y-%m-%dT%H:%M:%S.000000000Z"),
                        "mid": {"o": c.o, "h": c.h, "l": c.low, "c": c.c},
                    }
                    for c in rows
                ],
            },
        )


class FakeTime:
    """A monotonic clock and ``sleep`` that record waits instead of waiting."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


__all__ = [
    "BinanceFake",
    "BybitFake",
    "Candle",
    "CoinbaseFake",
    "FakeTime",
    "FakeVenue",
    "HyperliquidFake",
    "OandaFake",
    "make_candles",
    "network_error",
    "status",
]
