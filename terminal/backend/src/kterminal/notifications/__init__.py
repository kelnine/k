"""Module 11 — Notification service (Telegram first).

Domain events → notification policy → templates → durable outbox →
rate-limited delivery by the ``worker`` process, plus scheduled daily and
weekly reports. Telegram is one ``Notifier`` plug-in; others can be added
without touching producers. See ``terminal/docs/08-telegram.md``.

Status: scaffold (Phase 1). Implemented in Phase 7.
"""
