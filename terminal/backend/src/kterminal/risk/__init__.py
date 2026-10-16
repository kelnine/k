"""Module 6 — Risk Management Engine.

A pure, deterministic rule pipeline that turns an order intent plus an
account snapshot into a ``RiskDecision`` (with the result and reason of every
rule), position sizing, prop-style daily-loss and static/trailing drawdown
models, the continuous equity monitor and the global kill switch. Only this
module constructs ``ApprovedOrder`` objects — the execution engine accepts
nothing else.

Purity (enforced by import-linter): no imports of brokers, execution, API,
webhook, notifications or strategies. See ``terminal/docs/07-risk-engine.md``.

Status: scaffold (Phase 1). Implemented in Phases 3 and 5.
"""
