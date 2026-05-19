"""
Tradier Sandbox broker implementation.

Sandbox base URL : https://sandbox.tradier.com
Docs             : https://documentation.tradier.com
Auth header      : Authorization: Bearer <TRADIER_TOKEN>

Options order endpoint:
  POST /v1/accounts/{account_id}/orders
  Content-Type: application/x-www-form-urlencoded

  class=option
  symbol=SPY
  option_symbol=SPY   250519C00580000
  side=buy_to_open | sell_to_close
  quantity=1
  type=market | limit
  duration=day
  price=<limit_price>   (only for limit orders)
"""
import logging
import urllib.parse

import aiohttp

from config import TRADIER_TOKEN, TRADIER_ACCOUNT_ID, TRADIER_BASE_URL, LIVE_TRADING
from bot.brokers.base import BaseBroker

logger = logging.getLogger(__name__)

_HEADERS = {
    "Authorization": f"Bearer {TRADIER_TOKEN}",
    "Accept": "application/json",
}


class TradierBroker(BaseBroker):
    def __init__(self):
        self.base = TRADIER_BASE_URL
        self.account_id = TRADIER_ACCOUNT_ID

    def _session(self) -> aiohttp.ClientSession:
        return aiohttp.ClientSession(headers=_HEADERS)

    async def get_account_info(self) -> dict:
        url = f"{self.base}/v1/accounts/{self.account_id}/balances"
        async with self._session() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status != 200:
                    text = await r.text()
                    logger.error(f"Tradier balances error {r.status}: {text[:300]}")
                    return {}
                data = await r.json(content_type=None)
                return data.get("balances", {})

    async def get_option_quote(self, option_symbol: str) -> dict | None:
        url = f"{self.base}/v1/markets/options/quotes"
        params = {"symbols": option_symbol, "greeks": "false"}
        async with self._session() as s:
            async with s.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status != 200:
                    logger.warning(f"Tradier quote {option_symbol}: HTTP {r.status}")
                    return None
                data = await r.json(content_type=None)
                quotes = data.get("quotes", {}).get("quote")
                if not quotes:
                    return None
                if isinstance(quotes, list):
                    q = quotes[0]
                else:
                    q = quotes
                bid = float(q.get("bid") or 0)
                ask = float(q.get("ask") or 0)
                last = float(q.get("last") or q.get("close") or 0)
                mid = round((bid + ask) / 2, 4) if bid and ask else last
                return {"bid": bid, "ask": ask, "mid": mid, "last": last}

    async def place_option_order(
        self,
        underlying: str,
        option_symbol: str,
        side: str,
        contracts: int,
        order_type: str = "market",
        limit_price: float | None = None,
    ) -> dict | None:
        if LIVE_TRADING:
            # Extra guard — config.py already forced manual confirmation at startup
            logger.critical("LIVE_TRADING detected in place_option_order. Refusing.")
            return None

        url = f"{self.base}/v1/accounts/{self.account_id}/orders"
        payload = {
            "class": "option",
            "symbol": underlying.upper(),
            "option_symbol": option_symbol,
            "side": side,
            "quantity": str(contracts),
            "type": order_type,
            "duration": "day",
        }
        if order_type == "limit" and limit_price is not None:
            payload["price"] = f"{limit_price:.2f}"

        logger.info(
            f"Tradier order → {side} {contracts}x {option_symbol} "
            f"({order_type}{f' @{limit_price}' if limit_price else ''})"
        )
        async with self._session() as s:
            async with s.post(
                url,
                data=urllib.parse.urlencode(payload),
                headers={**_HEADERS, "Content-Type": "application/x-www-form-urlencoded"},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as r:
                text = await r.text()
                if r.status not in (200, 201):
                    logger.error(f"Tradier order failed HTTP {r.status}: {text[:400]}")
                    return None
                data = await r.json(content_type=None)
                order = data.get("order", {})
                logger.info(f"Tradier order placed: id={order.get('id')} status={order.get('status')}")
                return order

    async def cancel_order(self, order_id: str) -> bool:
        url = f"{self.base}/v1/accounts/{self.account_id}/orders/{order_id}"
        async with self._session() as s:
            async with s.delete(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                ok = r.status in (200, 201)
                if not ok:
                    text = await r.text()
                    logger.warning(f"Tradier cancel {order_id}: HTTP {r.status} {text[:200]}")
                return ok
