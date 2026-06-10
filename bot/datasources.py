"""Market-data sources.

Two implementations behind one interface:

- ``BinanceDataSource``  — zero-config public REST. Works out of the box so the
  bot runs today. Gives price / 24h change / funding / open interest.
- ``LiquidDataSource``   — the Co-Invest "Liquid" analysis engine. Same fields
  PLUS the per-size positioning bias (whale vs. retail) that powers our edge,
  and the referral code. Needs LIQUID_BASE_URL / LIQUID_TOKEN.

Both return a normalized ``MarketSnapshot`` so the strategy doesn't care which
one produced it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import httpx


@dataclass
class SizeBucket:
    label: str
    min_size: float | None
    position_value: float
    long_value: float

    @property
    def long_bias(self) -> float:
        """Fraction of notional that is long (0..1)."""
        if self.position_value <= 0:
            return 0.5
        return self.long_value / self.position_value


@dataclass
class MarketSnapshot:
    symbol: str
    price: float
    change_24h_pct: float
    funding_pct: float | None = None
    open_interest_usd: float | None = None
    # Positioning by trader size, smallest -> largest. Empty if unavailable.
    buckets: list[SizeBucket] = field(default_factory=list)
    ref_code: str | None = None

    @property
    def has_positioning(self) -> bool:
        return len(self.buckets) >= 2

    def _bias_for(self, predicate) -> float | None:
        sel = [b for b in self.buckets if predicate(b)]
        tot = sum(b.position_value for b in sel)
        if tot <= 0:
            return None
        return sum(b.long_value for b in sel) / tot

    @property
    def whale_long_bias(self) -> float | None:
        """Long bias of large positions (>= $500k)."""
        return self._bias_for(lambda b: (b.min_size or 0) >= 500_000)

    @property
    def retail_long_bias(self) -> float | None:
        """Long bias of small positions (< $25k)."""
        return self._bias_for(lambda b: (b.min_size or 0) < 25_000)


class DataSource:
    def snapshot(self, symbol: str) -> MarketSnapshot | None:  # pragma: no cover
        raise NotImplementedError


class BinanceDataSource(DataSource):
    """Public Binance USDⓈ-M futures data. No API key required."""

    BASE = "https://fapi.binance.com"

    def __init__(self, client: httpx.Client | None = None):
        self._c = client or httpx.Client(timeout=10.0)

    def snapshot(self, symbol: str) -> MarketSnapshot | None:
        pair = f"{symbol.upper()}USDT"
        try:
            t = self._c.get(f"{self.BASE}/fapi/v1/ticker/24hr", params={"symbol": pair})
            if t.status_code != 200:
                return None
            t = t.json()
            price = float(t["lastPrice"])
            change = float(t["priceChangePercent"])

            funding = None
            oi_usd = None
            try:
                pr = self._c.get(f"{self.BASE}/fapi/v1/premiumIndex", params={"symbol": pair})
                if pr.status_code == 200:
                    funding = float(pr.json()["lastFundingRate"]) * 100
                oi = self._c.get(f"{self.BASE}/fapi/v1/openInterest", params={"symbol": pair})
                if oi.status_code == 200:
                    oi_usd = float(oi.json()["openInterest"]) * price
            except (httpx.HTTPError, KeyError, ValueError):
                pass

            return MarketSnapshot(
                symbol=symbol.upper(),
                price=price,
                change_24h_pct=change,
                funding_pct=funding,
                open_interest_usd=oi_usd,
            )
        except (httpx.HTTPError, KeyError, ValueError):
            return None


class LiquidDataSource(DataSource):
    """Co-Invest 'Liquid' analysis engine.

    Parses the exact shape returned by the engine's analyze_market response,
    including ``sections.size.breakdownBySize`` (positioning) and ``refCode``.
    Set base_url/token from your engine deployment.
    """

    def __init__(self, base_url: str, token: str = "", client: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._c = client or httpx.Client(timeout=15.0)

    def snapshot(self, symbol: str) -> MarketSnapshot | None:
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        try:
            r = self._c.get(
                f"{self.base_url}/analyze-market",
                params={"symbol": symbol.upper()},
                headers=headers,
            )
            if r.status_code != 200:
                return None
            return self.parse(r.json())
        except httpx.HTTPError:
            return None

    @staticmethod
    def parse(data: dict) -> MarketSnapshot | None:
        try:
            tk = data["ticker"]
            price = float(tk["markPx"])
            prev = float(tk.get("prevDayPx", price))
            change = (price - prev) / prev * 100 if prev else 0.0
            funding = _num(tk.get("funding"))
            oi = _num(tk.get("openInterest"))

            buckets: list[SizeBucket] = []
            for b in data.get("sections", {}).get("size", {}).get("breakdownBySize", []):
                buckets.append(
                    SizeBucket(
                        label=b.get("size", ""),
                        min_size=b.get("minSize"),
                        position_value=float(b.get("totalPositionValue", 0) or 0),
                        long_value=float(b.get("totalPositionValueLong", 0) or 0),
                    )
                )
            buckets.sort(key=lambda x: (x.min_size if x.min_size is not None else -1))
            return MarketSnapshot(
                symbol=data.get("symbol", "").upper(),
                price=price,
                change_24h_pct=change,
                funding_pct=funding,
                open_interest_usd=oi,
                buckets=buckets,
                ref_code=data.get("refCode"),
            )
        except (KeyError, ValueError, TypeError):
            return None


def _num(s) -> float | None:
    """Parse '0.0009%' or '$1,952,787,030' or '−3.20%' into a float."""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    cleaned = (
        str(s)
        .replace("%", "")
        .replace("$", "")
        .replace(",", "")
        .replace("−", "-")  # unicode minus -> ascii
        .strip()
    )
    try:
        return float(cleaned)
    except ValueError:
        return None


def build_data_source(cfg) -> DataSource:
    if cfg.data_source == "liquid" and cfg.liquid_base_url:
        return LiquidDataSource(cfg.liquid_base_url, cfg.liquid_token)
    return BinanceDataSource()
