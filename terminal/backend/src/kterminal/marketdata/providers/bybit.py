"""Bybit v5 klines for linear (USDT) perpetuals: ``GET /v5/market/kline?category=linear``.

Response (every value a string; ``list`` sorted **newest first**; when the range reaches
the current minute, the first entry is the candle still forming — its close "is the last
traded price when the candle is not closed")::

    {"retCode": 0, "retMsg": "OK",
     "result": {"symbol": "SOLUSDT", "category": "linear",
                "list": [["1670608800000", "17071", "17073", "17027", "17055.5",
                          "268611", "15.74462667"], ...]},
     "retExtInfo": {}, "time": 1672025956592}

Fields: start time (ms), open, high, low, close, volume (base coin for USDT
perpetuals), turnover (quote). At most 1,000 candles per request. ``start`` is inclusive
on the candle start time; ``end`` is set to the last wanted candle's final millisecond
(start + 59 999), so a window is complete and never reaches the next candle whether the
venue reads ``end`` inclusively or exclusively.

Errors arrive as HTTP 200 with ``retCode != 0``: 10006 (API rate limit), 10000 (server
timeout) and 10016 (server error) are retried, everything else (e.g. 10001, a bad
symbol or parameter) fails at once. HTTP 403 means the IP is rate-limit banned (600
requests per 5 s per IP) **or** the request comes from a blocked country — Bybit is not
available in the US and some other jurisdictions.
"""

from datetime import datetime
from typing import Any

from kterminal.domain.market import Bar
from kterminal.marketdata.base import MarketDataError
from kterminal.marketdata.providers._http import (
    HttpProvider,
    PayloadError,
    decimal_field,
    from_ms,
    require,
    to_ms,
)

_RETRYABLE_CODES = frozenset({10000, 10006, 10016})


class BybitLinearProvider(HttpProvider):
    """Bybit linear perpetuals, e.g. ``SOLUSDT``."""

    name = "bybit_linear"
    default_base_url = "https://api.bybit.com"
    category = "linear"
    window_bars = 1000  # the endpoint's maximum ``limit``
    budget_per_minute = 300
    budget_burst = 20

    async def _fetch_window(
        self, instrument: str, symbol: str, first: datetime, last: datetime
    ) -> list[Bar]:
        params: dict[str, str | int] = {
            "category": self.category,
            "symbol": symbol,
            "interval": "1",
            "start": to_ms(first),
            "end": to_ms(last) + 59_999,  # the last wanted candle's final millisecond
            "limit": self.window_bars,
        }
        payload = await self._request_json("GET", "/v5/market/kline", params=params)
        result = require(require(payload, dict, "response").get("result"), dict, "result")
        if result.get("symbol") not in (None, symbol):
            raise PayloadError(f"result is for {result.get('symbol')!r}, not {symbol!r}")
        if result.get("category") not in (None, self.category):
            raise PayloadError(f"result is for category {result.get('category')!r}")
        rows = require(result.get("list"), list, "result.list")
        return [self._parse(instrument, row, index) for index, row in enumerate(rows)]

    def _parse(self, instrument: str, row: Any, index: int) -> Bar:
        where = f"list[{index}]"
        require(row, list, where)
        if len(row) < 6:
            raise PayloadError(f"{where}: expected at least 6 fields, got {len(row)}")
        return self._bar(
            instrument,
            from_ms(row[0], f"{where} start time"),
            decimal_field(row[1], f"{where} open"),
            decimal_field(row[2], f"{where} high"),
            decimal_field(row[3], f"{where} low"),
            decimal_field(row[4], f"{where} close"),
            decimal_field(row[5], f"{where} volume"),
        )

    def _payload_retry_reason(self, payload: Any) -> str | None:
        if not isinstance(payload, dict) or "retCode" not in payload:
            raise MarketDataError(f"{self.name}: response without retCode: {str(payload)[:200]}")
        code = payload.get("retCode")
        if code == 0:
            return None
        message = f"retCode {code}: {payload.get('retMsg', '')}"
        if code in _RETRYABLE_CODES:
            return message
        raise MarketDataError(f"{self.name} GET /v5/market/kline: {message}")

    def _status_hint(self, status: int) -> str | None:
        if status == 403:
            return (
                "Bybit answers 403 when the IP is rate-limit banned or the request comes "
                "from a blocked country (e.g. the US)"
            )
        return super()._status_hint(status)


__all__ = ["BybitLinearProvider"]
