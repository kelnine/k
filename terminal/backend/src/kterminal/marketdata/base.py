"""The market-data port: where closed 1-minute bars come from.

Every provider speaks in **canonical** instruments (``XAUUSD``, ``BTCUSD``)
and returns closed base-timeframe (1m) :class:`~kterminal.domain.market.Bar`
objects, oldest first, with ``open_time`` on the minute and the provider's
name in ``Bar.source``. Mapping a canonical instrument to the provider's own
symbol (``XAU_USD``, ``BTCUSDT``) is the provider's job, driven by the data
source map in the catalog configuration.

Rules every provider follows:

* only **closed** bars are returned — a bar whose minute has not ended (or
  that the venue still marks incomplete) is never returned;
* missing minutes are **not** filled in (TradingView does not fill them
  either); a gap is simply absent;
* prices are exact decimals as the venue reports them (no float round-trip);
* volume is whatever the venue reports (exchange volume, tick volume or 0) —
  its meaning is recorded per source in the data source map.
"""

from datetime import datetime
from typing import Protocol, runtime_checkable

from kterminal.domain.market import Bar


class MarketDataError(RuntimeError):
    """A provider could not deliver data (network, rate limit, unknown symbol, bad payload)."""


@runtime_checkable
class MarketDataProvider(Protocol):
    """A source of closed 1-minute bars for canonical instruments."""

    name: str

    def supports(self, instrument: str) -> bool:
        """True if this provider can deliver bars for the canonical instrument."""
        ...

    async def history(self, instrument: str, start: datetime, end: datetime) -> list[Bar]:
        """Closed 1m bars with ``start <= open_time < end``, oldest first.

        Pages through the venue's API as needed. ``start``/``end`` are
        timezone-aware UTC.
        """
        ...

    async def latest(self, instrument: str, since: datetime) -> list[Bar]:
        """Closed 1m bars with ``open_time >= since``, oldest first (live polling)."""
        ...

    async def aclose(self) -> None:
        """Release network resources."""
        ...


__all__ = ["MarketDataError", "MarketDataProvider"]
