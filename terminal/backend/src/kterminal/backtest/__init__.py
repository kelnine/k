"""Module 2 — Backtesting Engine.

Replays historical bars on a simulated clock through the *same* strategy
runner, risk engine and execution engine used live, with a simulated broker
and an explicit fill model (spread, slippage, commission, intrabar SL/TP
ordering). Also replays recorded external signals ("signal replay").

Status: scaffold (Phase 1). Implemented in Phase 3.
"""
