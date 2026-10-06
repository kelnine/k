"""Module 13 — Logging / Audit (logging half).

Structured JSON logs with correlation IDs and secret redaction, shared by
every process. The persistent, hash-chained audit trail lives in
``kterminal.db`` (Phase 2) because it is data, not log output.
"""

from kterminal.observability.context import correlation_scope, get_correlation_id
from kterminal.observability.logging import configure_logging, get_logger
from kterminal.observability.redaction import REDACTED, redact, redact_text

__all__ = [
    "REDACTED",
    "configure_logging",
    "correlation_scope",
    "get_correlation_id",
    "get_logger",
    "redact",
    "redact_text",
]
