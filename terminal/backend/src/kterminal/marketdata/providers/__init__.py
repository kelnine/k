"""Market-data providers: one :class:`~kterminal.marketdata.base.MarketDataProvider` per
data source (docs/15-market-data.md). Each speaks canonical instruments, maps them to its
own symbols through the data source map, and returns closed 1m bars oldest first."""

from kterminal.marketdata.providers._http import HttpProvider, ProviderOptions, RequestBudget
from kterminal.marketdata.providers.binance import BinanceSpotProvider, BinanceUsdmProvider
from kterminal.marketdata.providers.bybit import BybitLinearProvider
from kterminal.marketdata.providers.coinbase import CoinbaseProvider
from kterminal.marketdata.providers.csv_files import CsvProvider
from kterminal.marketdata.providers.hyperliquid import HyperliquidProvider
from kterminal.marketdata.providers.oanda import OANDA_HOSTS, OandaProvider

# The public (token-free) REST providers, by provider name.
HTTP_PROVIDERS: dict[str, type[HttpProvider]] = {
    provider.name: provider
    for provider in (
        BinanceUsdmProvider,
        BinanceSpotProvider,
        BybitLinearProvider,
        CoinbaseProvider,
        HyperliquidProvider,
    )
}

__all__ = [
    "HTTP_PROVIDERS",
    "OANDA_HOSTS",
    "BinanceSpotProvider",
    "BinanceUsdmProvider",
    "BybitLinearProvider",
    "CoinbaseProvider",
    "CsvProvider",
    "HttpProvider",
    "HyperliquidProvider",
    "OandaProvider",
    "ProviderOptions",
    "RequestBudget",
]
