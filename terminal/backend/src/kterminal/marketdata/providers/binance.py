"""Binance klines: USD-M perpetual futures (``/fapi/v1/klines``) and spot (``/api/v3/klines``).

Both answer an array of klines, oldest first::

    [[1499040000000,      // open time (ms)
      "0.01634790",       // open
      "0.80000000",       // high
      "0.01575800",       // low
      "0.01577100",       // close
      "148976.11427815",  // volume (base asset)
      1499644799999,      // close time (ms) = open time + 59 999 for 1m
      "2434.19055334", 308, "1756.87402397", "28.46694368", "0"]]

With ``startTime`` and ``endTime`` the endpoint returns the oldest klines from
``startTime`` up to ``limit`` without passing ``endTime``; the kline whose minute is
still running is included when the range reaches it (it is dropped by time here).

Limits (per IP): USD-M 2,400 request weight per minute, a 1m kline request of more
than 1,000 rows weighs 10; spot 6,000 per minute, a kline request weighs 2. Every
response carries ``X-MBX-USED-WEIGHT-1M``; past 90 % of the limit this provider pauses
until the next minute. HTTP 429 is retried after ``Retry-After``; 418 (IP banned for
ignoring 429s), 403 (WAF block) and 451 (restricted location — Binance is unavailable
in some countries, e.g. the US) fail at once.
"""

from datetime import datetime
from typing import Any

import httpx

from kterminal.domain.market import Bar
from kterminal.marketdata.providers._http import (
    HttpProvider,
    PayloadError,
    decimal_field,
    from_ms,
    int_field,
    require,
    to_ms,
)

_WEIGHT_PAUSE_FRACTION = 0.9


class _BinanceKlines(HttpProvider):
    path: str
    weight_limit_per_minute: int  # the venue's IP limit (the budget stays well below it)
    request_weight: int  # weight of one window request

    async def _fetch_window(
        self, instrument: str, symbol: str, first: datetime, last: datetime
    ) -> list[Bar]:
        params: dict[str, str | int] = {
            "symbol": symbol,
            "interval": "1m",
            "startTime": to_ms(first),
            "endTime": to_ms(last) + 59_999,  # the last wanted kline's close time
            "limit": self.window_bars,
        }
        cost = self.request_weight
        payload = await self._request_json("GET", self.path, params=params, cost=cost)
        rows = require(payload, list, "klines")
        return [self._parse(instrument, row, index) for index, row in enumerate(rows)]

    def _parse(self, instrument: str, row: Any, index: int) -> Bar:
        where = f"kline[{index}]"
        require(row, list, where)
        if len(row) < 7:
            raise PayloadError(f"{where}: expected at least 7 fields, got {len(row)}")
        open_time = from_ms(row[0], f"{where} open time")
        close_ms = int_field(row[6], f"{where} close time")
        if close_ms != to_ms(open_time) + 59_999:
            raise PayloadError(f"{where}: close time {close_ms} is not a 1-minute kline's")
        return self._bar(
            instrument,
            open_time,
            decimal_field(row[1], f"{where} open"),
            decimal_field(row[2], f"{where} high"),
            decimal_field(row[3], f"{where} low"),
            decimal_field(row[4], f"{where} close"),
            decimal_field(row[5], f"{where} volume"),
        )

    def _observe(self, response: httpx.Response) -> None:
        raw = response.headers.get("x-mbx-used-weight-1m")
        if raw is None or not raw.isdigit():
            return
        if int(raw) >= self.weight_limit_per_minute * _WEIGHT_PAUSE_FRACTION:
            now = self._clock.now()
            self._budget.pause(61 - now.second - now.microsecond / 1e6)

    def _status_hint(self, status: int) -> str | None:
        if status == 418:
            return "this IP is banned for ignoring HTTP 429s; wait for the ban (Retry-After) to end"
        if status == 403:
            return "blocked by Binance's web application firewall (rate limit or security rule)"
        return super()._status_hint(status)


class BinanceUsdmProvider(_BinanceKlines):
    """Binance USD-M (USDT-margined) perpetual futures, e.g. ``BTCUSDT``."""

    name = "binance_usdm"
    default_base_url = "https://fapi.binance.com"
    path = "/fapi/v1/klines"
    window_bars = 1500  # the endpoint's maximum ``limit``
    request_weight = 10  # limit > 1000
    weight_limit_per_minute = 2400
    budget_per_minute = 1200
    budget_burst = 100


class BinanceSpotProvider(_BinanceKlines):
    """Binance spot, e.g. ``PUMPUSDT``."""

    name = "binance_spot"
    default_base_url = "https://api.binance.com"
    path = "/api/v3/klines"
    window_bars = 1000  # the endpoint's maximum ``limit``
    request_weight = 2
    weight_limit_per_minute = 6000
    budget_per_minute = 1200
    budget_burst = 40


__all__ = ["BinanceSpotProvider", "BinanceUsdmProvider"]
