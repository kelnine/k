"""Coinbase Exchange candles: ``GET /products/{product_id}/candles?granularity=60``.

Response, **newest first**, numbers as JSON numbers (decoded exactly as ``Decimal``)::

    [[1591514160, 0.02507, 0.02507, 0.02507, 0.02507, 0.02816506], ...]
      time (s)    low      high     open     close    volume (base currency)

Note the field order: low before high, open after them. A request may cover at most
300 candles (``start``/``end`` in ISO 8601; larger ranges are rejected with HTTP 400).
Each request here covers 299 minutes and sets ``end`` one minute past them, so the
window is complete whether ``end`` is inclusive or exclusive (the extra bucket is
ignored). Minutes without trades have no candle, and the current minute's bucket can be
included while it is still forming. Public endpoints
allow about 10 requests per second per IP; HTTP 429 is retried. Errors are
``{"message": "..."}`` (e.g. 404 ``NotFound`` for an unknown product).
"""

from datetime import UTC, datetime
from typing import Any

from kterminal.domain.market import Bar
from kterminal.marketdata.providers._http import (
    MINUTE,
    HttpProvider,
    PayloadError,
    decimal_field,
    int_field,
    require,
)


def _iso(ts: datetime) -> str:
    return ts.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class CoinbaseProvider(HttpProvider):
    """Coinbase Exchange spot products, e.g. ``ZEC-USD``."""

    name = "coinbase"
    default_base_url = "https://api.exchange.coinbase.com"
    window_bars = 299  # + the bucket at ``end`` = the endpoint's maximum of 300
    budget_per_minute = 180
    budget_burst = 5

    async def _fetch_window(
        self, instrument: str, symbol: str, first: datetime, last: datetime
    ) -> list[Bar]:
        params: dict[str, str | int] = {
            "granularity": 60,
            "start": _iso(first),
            "end": _iso(last + MINUTE),
        }
        payload = await self._request_json("GET", f"/products/{symbol}/candles", params=params)
        rows = require(payload, list, "candles")
        return [self._parse(instrument, row, index) for index, row in enumerate(rows)]

    def _parse(self, instrument: str, row: Any, index: int) -> Bar:
        where = f"candle[{index}]"
        require(row, list, where)
        if len(row) != 6:
            raise PayloadError(f"{where}: expected 6 fields, got {len(row)}")
        seconds = int_field(row[0], f"{where} time")
        if seconds % 60:
            raise PayloadError(f"{where} time {seconds} is not on a whole minute")
        return self._bar(
            instrument,
            datetime.fromtimestamp(seconds, tz=UTC),
            open_=decimal_field(row[3], f"{where} open"),
            high=decimal_field(row[2], f"{where} high"),
            low=decimal_field(row[1], f"{where} low"),
            close=decimal_field(row[4], f"{where} close"),
            volume=decimal_field(row[5], f"{where} volume"),
        )


__all__ = ["CoinbaseProvider"]
