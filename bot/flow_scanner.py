"""
Polls the Unusual Whales API for options flow alerts.

Unusual Whales API reference:
  GET /api/option-trades/flow-alerts
  Authorization: Bearer <token>

Response shape (best-effort; adapt if the API changes):
  {
    "data": [
      {
        "id": "...",
        "ticker": "SPY",
        "date": "2025-05-19",
        "expiry": "2025-05-19",
        "strike": 580.0,
        "option_type": "call",       # also seen as "type"
        "premium": 250000,
        "size": 250,                 # contracts
        "volume": 12500,
        "open_interest": 8000,
        "dte": 0,
        "execution_estimate": "sweep",
        "side": "ask",               # ask = paid above mid (bullish)
        "bid": 0.95,
        "ask": 1.05,
        "midpoint": 1.00
      },
      ...
    ]
  }
"""
import logging
from datetime import date
from typing import Any

import aiohttp

from config import UNUSUAL_WHALES_TOKEN, UNUSUAL_WHALES_BASE_URL, FLOW_FETCH_LIMIT, WATCHLIST

logger = logging.getLogger(__name__)

_HEADERS = {
    "Authorization": f"Bearer {UNUSUAL_WHALES_TOKEN}",
    "Accept": "application/json, text/plain",
}

# Endpoints to try in order (UW sometimes changes paths between API versions)
_FLOW_ENDPOINTS = [
    "/api/option-trades/flow-alerts",
    "/api/option/flow-alerts",
    "/api/options/flow-alerts",
]


def _normalise_alert(raw: dict) -> dict | None:
    """Coerce an UW alert dict into the canonical shape the bot uses."""
    try:
        ticker = (raw.get("ticker") or raw.get("symbol") or "").upper().strip()
        if not ticker:
            return None

        opt_type = (
            raw.get("option_type") or raw.get("type") or raw.get("call_or_put") or ""
        ).lower().strip()
        if opt_type not in ("call", "put"):
            return None

        premium = float(raw.get("premium") or raw.get("total_premium") or 0)
        volume = int(raw.get("volume") or raw.get("vol") or 0)
        oi = int(raw.get("open_interest") or raw.get("oi") or 0)

        expiry = raw.get("expiry") or raw.get("expiration_date") or raw.get("exp") or ""
        dte_raw = raw.get("dte")
        if dte_raw is not None:
            dte = int(dte_raw)
        elif expiry:
            try:
                exp_date = date.fromisoformat(expiry[:10])
                dte = (exp_date - date.today()).days
            except ValueError:
                dte = 999
        else:
            dte = 999

        strike = float(raw.get("strike") or raw.get("strike_price") or 0)
        execution = (raw.get("execution_estimate") or raw.get("trade_type") or raw.get("execution") or "").lower()
        side = (raw.get("side") or "").lower()

        bid = float(raw.get("bid") or 0)
        ask = float(raw.get("ask") or 0)
        midpoint = float(raw.get("midpoint") or raw.get("mid") or ((bid + ask) / 2 if bid and ask else 0))

        alert_id = str(raw.get("id") or raw.get("alert_id") or f"{ticker}-{expiry}-{strike}-{opt_type}")

        return {
            "id": alert_id,
            "ticker": ticker,
            "option_type": opt_type,
            "strike": strike,
            "expiry": expiry[:10] if expiry else "",
            "dte": dte,
            "premium": premium,
            "volume": volume,
            "open_interest": oi,
            "execution": execution,
            "side": side,
            "bid": bid,
            "ask": ask,
            "midpoint": midpoint,
            "raw": raw,
        }
    except Exception as exc:
        logger.debug(f"Failed to normalise alert: {exc} | raw={raw}")
        return None


class FlowScanner:
    def __init__(self):
        self._working_endpoint: str | None = None

    async def get_flow(self) -> list[dict]:
        """Fetch and return normalised flow alerts from Unusual Whales."""
        if not UNUSUAL_WHALES_TOKEN:
            logger.warning("UNUSUAL_WHALES_TOKEN not set — skipping flow scan.")
            return []

        async with aiohttp.ClientSession(headers=_HEADERS) as session:
            endpoints = (
                [self._working_endpoint] if self._working_endpoint else _FLOW_ENDPOINTS
            )
            for endpoint in endpoints:
                alerts = await self._try_endpoint(session, endpoint)
                if alerts is not None:
                    self._working_endpoint = endpoint
                    return alerts

        logger.error("All Unusual Whales flow endpoints failed.")
        return []

    async def _try_endpoint(self, session: aiohttp.ClientSession, path: str) -> list[dict] | None:
        url = UNUSUAL_WHALES_BASE_URL + path
        params: dict[str, Any] = {"limit": FLOW_FETCH_LIMIT}

        # Optionally filter to watchlist tickers if the API supports it
        if WATCHLIST:
            params["tickers"] = ",".join(WATCHLIST)

        try:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 404:
                    return None
                if resp.status == 401:
                    logger.error("Unusual Whales: 401 Unauthorised. Check UNUSUAL_WHALES_TOKEN.")
                    return []
                if resp.status != 200:
                    text = await resp.text()
                    logger.warning(f"UW {path} → HTTP {resp.status}: {text[:200]}")
                    return None

                payload = await resp.json(content_type=None)

                # Handle both {"data": [...]} and bare [...]
                raw_list = payload.get("data") or payload if isinstance(payload, list) else []
                if not isinstance(raw_list, list):
                    raw_list = []

                alerts = [a for raw in raw_list if (a := _normalise_alert(raw)) is not None]
                logger.info(f"UW flow fetch: {len(alerts)} alerts from {path}")
                return alerts

        except aiohttp.ClientError as exc:
            logger.warning(f"UW request error on {path}: {exc}")
            return None
