"""Abstract broker interface — all brokers must implement these methods."""
from abc import ABC, abstractmethod


class BaseBroker(ABC):
    @abstractmethod
    async def get_account_info(self) -> dict:
        """Return account details including cash/buying power."""

    @abstractmethod
    async def get_option_quote(self, option_symbol: str) -> dict | None:
        """
        Return a dict with at minimum:
          {"bid": float, "ask": float, "mid": float, "last": float}
        Returns None if the quote cannot be fetched.
        """

    @abstractmethod
    async def place_option_order(
        self,
        underlying: str,
        option_symbol: str,
        side: str,           # "buy_to_open" | "sell_to_close"
        contracts: int,
        order_type: str,     # "market" | "limit"
        limit_price: float | None,
    ) -> dict | None:
        """
        Place an options order. Returns the broker's order object on success,
        None on failure. Must raise if LIVE_TRADING safety check fails.
        """

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order. Returns True on success."""

    @staticmethod
    def build_option_symbol(
        underlying: str,
        expiry: str,          # "YYYY-MM-DD"
        option_type: str,     # "call" | "put"
        strike: float,
    ) -> str:
        """
        OCC option symbol format:
          {underlying padded to 6}{YY}{MM}{DD}{C/P}{strike*1000 zero-padded to 8}
        Example: SPY   250519C00580000
        """
        exp = expiry.replace("-", "")          # YYYYMMDD
        yy_mm_dd = exp[2:]                     # YYMMDD
        cp = "C" if option_type == "call" else "P"
        strike_int = int(round(strike * 1000))
        strike_str = str(strike_int).zfill(8)
        root = underlying.upper().ljust(6)[:6]
        return f"{root}{yy_mm_dd}{cp}{strike_str}"
