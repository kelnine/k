"""Hyperliquid candles: ``POST /info`` with ``{"type": "candleSnapshot", "req": {...}}``.

Request ``req``: ``coin`` (``"HYPE"``, ``"BTC"``; builder-deployed HIP-3 markets as
``"dex:COIN"``), ``interval`` ``"1m"``, ``startTime`` and ``endTime`` in ms. Response,
oldest first, prices and sizes as strings::

    [{"t": 1704286800000, "T": 1704286859999, "s": "HYPE", "i": "1m",
      "o": "2247.9", "h": "2247.9", "l": "2224.6", "c": "2226.4", "v": "591.6427", "n": 46}]

``t``/``T`` open/close time, ``v`` volume in the coin, ``n`` number of trades. The candle
still forming is included. **Only the most recent 5,000 candles of an interval are
available** — about 3.5 days of 1m bars — so this source cannot backfill long history;
requests reaching further back are cut to what exists (and a warning is logged).

Rate limit: 1,200 weight per minute per IP; ``candleSnapshot`` weighs 20 plus 1 per 60
candles returned. HTTP 429 is retried.
"""

import math
from datetime import datetime, timedelta
from typing import Any

from kterminal.domain.market import Bar
from kterminal.marketdata.providers._http import (
    MINUTE,
    HttpProvider,
    PayloadError,
    decimal_field,
    from_ms,
    int_field,
    require,
    to_ms,
)


class HyperliquidProvider(HttpProvider):
    """Hyperliquid perpetuals, e.g. ``HYPE``."""

    name = "hyperliquid"
    default_base_url = "https://api.hyperliquid.xyz"
    window_bars = 5000
    history_depth: timedelta | None = 5000 * MINUTE
    budget_per_minute = 600
    budget_burst = 150

    async def _fetch_window(
        self, instrument: str, symbol: str, first: datetime, last: datetime
    ) -> list[Bar]:
        body = {
            "type": "candleSnapshot",
            "req": {
                "coin": symbol,
                "interval": "1m",
                "startTime": to_ms(first),
                "endTime": to_ms(last) + 59_999,
            },
        }
        minutes = int((last - first) / MINUTE) + 1
        payload = await self._request_json(
            "POST", "/info", json_body=body, cost=20 + math.ceil(minutes / 60)
        )
        rows = require(payload, list, "candles")
        return [self._parse(instrument, symbol, row, index) for index, row in enumerate(rows)]

    def _parse(self, instrument: str, symbol: str, row: Any, index: int) -> Bar:
        where = f"candle[{index}]"
        require(row, dict, where)
        missing = [key for key in ("t", "T", "o", "h", "l", "c", "v") if key not in row]
        if missing:
            raise PayloadError(f"{where}: missing {', '.join(missing)}")
        if row.get("i", "1m") != "1m":
            raise PayloadError(f"{where}: interval {row.get('i')!r}, expected '1m'")
        if row.get("s", symbol) != symbol:
            raise PayloadError(f"{where}: coin {row.get('s')!r}, expected {symbol!r}")
        open_time = from_ms(row["t"], f"{where} t")
        if int_field(row["T"], f"{where} T") != to_ms(open_time) + 59_999:
            raise PayloadError(f"{where}: close time {row['T']} is not a 1-minute candle's")
        return self._bar(
            instrument,
            open_time,
            decimal_field(row["o"], f"{where} o"),
            decimal_field(row["h"], f"{where} h"),
            decimal_field(row["l"], f"{where} l"),
            decimal_field(row["c"], f"{where} c"),
            decimal_field(row["v"], f"{where} v"),
        )


__all__ = ["HyperliquidProvider"]
