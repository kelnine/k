"""
Alpaca Paper broker implementation.

Note: Alpaca options trading on paper accounts requires options approval
(Level 2 or higher). If options are unavailable on your paper account,
use BROKER=tradier in your .env.

Paper API base : https://paper-api.alpaca.markets
Data API base  : https://data.alpaca.markets
Docs           : https://docs.alpaca.markets/reference/options-trading
"""
import logging

import aiohttp

from config import ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL, ALPACA_DATA_URL, LIVE_TRADING
from bot.brokers.base import BaseBroker

logger = logging.getLogger(__name__)

_HEADERS = {
    "APCA-API-KEY-ID": ALPACA_API_KEY,
    "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
    "Accept": "application/json",
    "Content-Type": "application/json",
}


class AlpacaBroker(BaseBroker):
    def __init__(self):
        self.base = ALPACA_BASE_URL
        self.data_base = ALPACA_DATA_URL

    def _session(self) -> aiohttp.ClientSession:
        return aiohttp.ClientSession(headers=_HEADERS)

    async def get_account_info(self) -> dict:
        url = f"{self.base}/v2/account"
        async with self._session() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status != 200:
                    text = await r.text()
                    logger.error(f"Alpaca account error {r.status}: {text[:300]}")
                    return {}
                return await r.json(content_type=None)

    async def get_option_quote(self, option_symbol: str) -> dict | None:
        """Fetch latest options snapshot from Alpaca data API."""
        url = f"{self.data_base}/v1beta1/options/snapshots/{option_symbol}"
        async with self._session() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status != 200:
                    logger.warning(f"Alpaca quote {option_symbol}: HTTP {r.status}")
                    return None
                data = await r.json(content_type=None)
                snap = data.get("snapshot") or data
                latest_quote = snap.get("latestQuote") or snap.get("latest_quote") or {}
                latest_trade = snap.get("latestTrade") or snap.get("latest_trade") or {}
                bid = float(latest_quote.get("bp") or latest_quote.get("bid_price") or 0)
                ask = float(latest_quote.get("ap") or latest_quote.get("ask_price") or 0)
                last = float(latest_trade.get("p") or latest_trade.get("price") or 0)
                mid = round((bid + ask) / 2, 4) if bid and ask else last
                return {"bid": bid, "ask": ask, "mid": mid, "last": last}

    async def place_option_order(
        self,
        underlying: str,
        option_symbol: str,
        side: str,           # "buy_to_open" | "sell_to_close"
        contracts: int,
        order_type: str = "market",
        limit_price: float | None = None,
    ) -> dict | None:
        if LIVE_TRADING:
            logger.critical("LIVE_TRADING detected in place_option_order. Refusing.")
            return None

        # Alpaca uses "buy"/"sell" not "buy_to_open"/"sell_to_close"
        alpaca_side = "buy" if "buy" in side else "sell"
        body: dict = {
            "symbol": option_symbol,
            "qty": str(contracts),
            "side": alpaca_side,
            "type": order_type if order_type != "market" else "market",
            "time_in_force": "day",
        }
        if order_type == "limit" and limit_price is not None:
            body["limit_price"] = str(round(limit_price, 2))

        logger.info(
            f"Alpaca order → {side} {contracts}x {option_symbol} "
            f"({order_type}{f' @{limit_price}' if limit_price else ''})"
        )
        url = f"{self.base}/v2/orders"
        async with self._session() as s:
            async with s.post(url, json=body, timeout=aiohttp.ClientTimeout(total=15)) as r:
                text = await r.text()
                if r.status not in (200, 201):
                    logger.error(f"Alpaca order failed HTTP {r.status}: {text[:400]}")
                    return None
                data = await r.json(content_type=None)
                logger.info(f"Alpaca order placed: id={data.get('id')} status={data.get('status')}")
                return data

    async def cancel_order(self, order_id: str) -> bool:
        url = f"{self.base}/v2/orders/{order_id}"
        async with self._session() as s:
            async with s.delete(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                ok = r.status in (200, 204)
                if not ok:
                    text = await r.text()
                    logger.warning(f"Alpaca cancel {order_id}: HTTP {r.status} {text[:200]}")
                return ok
