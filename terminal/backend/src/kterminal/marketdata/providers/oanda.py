"""OANDA v20 candles: ``GET /v3/instruments/{instrument}/candles?granularity=M1&price=M``.

Needs an API token (``Authorization: Bearer …``; ``KT_MARKETDATA__OANDA_TOKEN`` or
``KT_MARKETDATA__OANDA_TOKEN_FILE``). Tokens belong to one environment: practice
(``api-fxpractice.oanda.com``, the default) or live (``api-fxtrade.oanda.com``). Only
candles are ever requested — the live host is used to *read prices* with a live-account
token, never to trade.

Response (``price=M``: mid prices; times RFC 3339 with nanoseconds)::

    {"instrument": "XAU_USD", "granularity": "M1",
     "candles": [{"complete": true, "volume": 52,
                  "time": "2016-10-17T15:16:00.000000000Z",
                  "mid": {"o": "1.09886", "h": "1.09889", "l": "1.09880", "c": "1.09883"}}]}

``volume`` is the number of price updates in the minute (**tick volume**), not traded
size. ``complete: false`` marks the candle still forming; it is dropped. Minutes without
a price (weekends, daily breaks) have no candle. ``count`` may not exceed 5,000, so a
request covers at most 4,999 minutes from ``from`` to ``to``. OANDA allows about 120
requests per second per token; HTTP 429 is retried. Errors are
``{"errorMessage": "...", "errorCode": "..."}`` (401: bad token or wrong environment).
"""

import asyncio
import re
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import httpx
from pydantic import SecretStr

from kterminal.config.settings import OandaEnvironment
from kterminal.core.clock import Clock
from kterminal.domain.market import Bar
from kterminal.marketdata.providers._http import (
    MINUTE,
    HttpProvider,
    Monotonic,
    PayloadError,
    ProviderOptions,
    Sleep,
    decimal_field,
    require,
)

OANDA_HOSTS = {
    OandaEnvironment.PRACTICE: "https://api-fxpractice.oanda.com",
    OandaEnvironment.LIVE: "https://api-fxtrade.oanda.com",
}

_RFC3339 = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?Z$")


def _iso(ts: datetime) -> str:
    return ts.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000000000Z")


def _parse_time(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or (match := _RFC3339.fullmatch(value)) is None:
        raise PayloadError(f"{field}: expected an RFC 3339 UTC time, got {value!r}")
    if match[2] and int(match[2]):
        raise PayloadError(f"{field} {value} is not on a whole minute")
    ts = datetime.fromisoformat(match[1]).replace(tzinfo=UTC)
    if ts.second:
        raise PayloadError(f"{field} {value} is not on a whole minute")
    return ts


class OandaProvider(HttpProvider):
    """OANDA v20 instruments, e.g. ``XAU_USD``; mid prices, tick volume."""

    name = "oanda"
    default_base_url = OANDA_HOSTS[OandaEnvironment.PRACTICE]
    window_bars = 4999  # ``to`` may be read inclusively: 4,999 minutes stay ≤ 5,000 candles
    budget_per_minute = 600
    budget_burst = 20

    def __init__(
        self,
        symbols: Mapping[str, str],
        *,
        token: SecretStr,
        environment: OandaEnvironment = OandaEnvironment.PRACTICE,
        options: ProviderOptions | None = None,
        clock: Clock | None = None,
        base_url: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Sleep = asyncio.sleep,
        monotonic: Monotonic = time.monotonic,
    ) -> None:
        if not token.get_secret_value().strip():
            raise ValueError("OANDA needs an API token")
        self._token = token
        self.environment = environment
        super().__init__(
            symbols,
            options=options,
            clock=clock,
            base_url=base_url or OANDA_HOSTS[environment],
            transport=transport,
            sleep=sleep,
            monotonic=monotonic,
        )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token.get_secret_value().strip()}",
            "Accept-Datetime-Format": "RFC3339",
        }

    async def _fetch_window(
        self, instrument: str, symbol: str, first: datetime, last: datetime
    ) -> list[Bar]:
        params: dict[str, str | int] = {
            "price": "M",
            "granularity": "M1",
            "from": _iso(first),
            "to": _iso(last + MINUTE),
        }
        payload = await self._request_json(
            "GET", f"/v3/instruments/{symbol}/candles", params=params
        )
        body = require(payload, dict, "response")
        if body.get("instrument") not in (None, symbol):
            raise PayloadError(f"response is for {body.get('instrument')!r}, not {symbol!r}")
        if body.get("granularity") not in (None, "M1"):
            raise PayloadError(f"granularity {body.get('granularity')!r}, expected 'M1'")
        bars = []
        for index, row in enumerate(require(body.get("candles"), list, "candles")):
            where = f"candles[{index}]"
            require(row, dict, where)
            if require(row.get("complete"), bool, f"{where}.complete") is not True:
                continue  # still forming
            mid = require(row.get("mid"), dict, f"{where}.mid")
            bars.append(
                self._bar(
                    instrument,
                    _parse_time(row.get("time"), f"{where}.time"),
                    decimal_field(mid.get("o"), f"{where}.mid.o"),
                    decimal_field(mid.get("h"), f"{where}.mid.h"),
                    decimal_field(mid.get("l"), f"{where}.mid.l"),
                    decimal_field(mid.get("c"), f"{where}.mid.c"),
                    decimal_field(row.get("volume"), f"{where}.volume"),
                )
            )
        return bars

    def _status_hint(self, status: int) -> str | None:
        if status == 401:
            return (
                f"the OANDA token was rejected by the {self.environment.value} host "
                "(practice tokens only work with KT_MARKETDATA__OANDA_ENVIRONMENT=practice, "
                "live-account tokens with =live)"
            )
        return super()._status_hint(status)


__all__ = ["OANDA_HOSTS", "OandaProvider"]
