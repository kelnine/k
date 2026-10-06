"""Module 4 — Market Data Layer.

Historical import (CSV/Parquet), live quote and bar feeds, bar aggregation,
staleness detection, canonical symbol mapping (``OANDA:XAUUSD`` → ``XAUUSD``)
and data fingerprints that make every backtest reproducible.

Port: ``MarketDataProvider`` (``base.py``). Providers are plug-ins; a broker
adapter may also implement this port, but this package never imports brokers.

Status: scaffold (Phase 1). Implemented in Phases 3 and 5.
"""
