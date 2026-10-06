"""Module 1 — Strategy Engine (the strategy SDK and runner).

Defines the ``Strategy`` base class, ``StrategyContext``, parameter models,
the strategy registry and the ``StrategyRunner`` that feeds closed bars to a
strategy and collects its standardized ``Signal`` outputs. Also declares
*external* strategies whose signals arrive from TradingView.

Strategies propose; they never size, route or place orders.
See ``terminal/docs/05-strategy-interface.md``.

Status: scaffold (Phase 1). Implemented in Phase 2.
"""
