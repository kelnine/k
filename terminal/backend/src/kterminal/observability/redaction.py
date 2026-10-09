"""Secret redaction for logs and stored payloads.

Applied as the last structlog processor before rendering, so nothing that
looks like a credential reaches stdout — including values inside nested
dicts, exception text and stdlib log records from third-party libraries.
It is a safety net, not the primary control: secrets are ``SecretStr`` and
should never be logged deliberately.
"""

import re
from collections.abc import Mapping
from typing import Any

from pydantic import SecretBytes, SecretStr
from structlog.typing import EventDict

REDACTED = "[REDACTED]"

# Keys whose values are always masked, wherever they appear.
SENSITIVE_KEY = re.compile(
    r"(secret|passw|token|api[_-]?key|authorization|cookie|credential|private[_-]?key|dsn)",
    re.IGNORECASE,
)

# Patterns masked inside any string value.
_VALUE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # scheme://user:password@host  →  scheme://user:[REDACTED]@host
    (
        re.compile(r"(?P<prefix>\b[a-z][a-z0-9+.\-]*://[^:/@\s]+:)[^@/\s]+@", re.IGNORECASE),
        rf"\g<prefix>{REDACTED}@",
    ),
    # Telegram bot tokens: 123456789:AA…
    (re.compile(r"(?<!\d)\d{6,12}:[A-Za-z0-9_-]{30,}"), REDACTED),
    # Authorization: Bearer <token>
    (
        re.compile(r"(?P<prefix>\bbearer\s+)[A-Za-z0-9._~+/\-]+=*", re.IGNORECASE),
        rf"\g<prefix>{REDACTED}",
    ),
    # "secret": "…" / secret=… inside free text (e.g. a raw webhook body in an error message)
    (
        re.compile(
            r"(?P<prefix>[\"']?(?:secret|password|token|api[_-]?key)[\"']?\s*[:=]\s*[\"']?)"
            r"[^\"'\s,}&]+",
            re.IGNORECASE,
        ),
        rf"\g<prefix>{REDACTED}",
    ),
)

_MAX_DEPTH = 12


def redact_text(text: str) -> str:
    for pattern, replacement in _VALUE_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def redact(value: Any, _depth: int = 0) -> Any:
    """Return a copy of ``value`` with secrets masked (dicts, lists, tuples, strings)."""
    if _depth > _MAX_DEPTH:
        return "[TRUNCATED]"
    if isinstance(value, (SecretStr, SecretBytes)):
        return REDACTED
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        return {
            key: (
                REDACTED
                if isinstance(key, str) and SENSITIVE_KEY.search(key) and val not in (None, "")
                else redact(val, _depth + 1)
            )
            for key, val in value.items()
        }
    if isinstance(value, tuple):
        return tuple(redact(item, _depth + 1) for item in value)
    if isinstance(value, (list, set, frozenset)):
        return [redact(item, _depth + 1) for item in value]
    return value


def redaction_processor(_logger: Any, _method: str, event_dict: EventDict) -> EventDict:
    """structlog processor: mask secrets in every field of the event."""
    result: EventDict = redact(event_dict)
    return result
