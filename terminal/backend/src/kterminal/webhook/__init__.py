"""Module 5 — TradingView Webhook Receiver.

Authenticates, validates, normalizes, de-duplicates, persists and enqueues
TradingView alerts, acknowledging within milliseconds. Accepting a webhook is
never the same as approving a trade — that is the risk engine's job.
See ``terminal/docs/06-tradingview-webhook.md``.

Status: scaffold (Phase 1). Implemented in Phase 6.
"""
