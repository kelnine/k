"""Module 4 — Market Data Layer (docs/15-market-data.md).

Closed 1-minute bars for canonical instruments, from venue APIs or imported files, and
the aggregation of those bars into every higher timeframe:

* ``base`` — the ``MarketDataProvider`` port and ``MarketDataError``;
* ``sources`` — the data source map (``config/catalog/data_sources.yaml``): provider,
  provider symbol and volume kind per instrument, with alternatives;
* ``providers`` — Binance USD-M and spot, Bybit linear, Coinbase, Hyperliquid, OANDA
  (read-only REST clients) and imported CSV files;
* ``factory`` — ``build_providers(settings, sources, catalog)``;
* ``csv_import`` — generic OHLCV CSVs and TradingView chart exports;
* ``aggregator`` / ``synthetic`` — multi-timeframe aggregation and seeded demo data.

Providers are plug-ins; a broker adapter may also implement the port, but this package
never imports brokers. Nothing in it can place an order.
"""
