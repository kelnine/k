"""Canonical JSON and hashing — deterministic fingerprints of configuration and data.

Used for strategy version identity, account configuration versions and the
instrument catalog fingerprint: the same content always yields the same hash,
regardless of key order or how Decimals and dates were written.
"""

import hashlib
import json
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from typing import Any


def decimal_text(value: Decimal) -> str:
    """A Decimal as plain fixed-point text without redundant zeros: ``2.00`` → ``2``,
    ``0.010`` → ``0.01``, ``1E+2`` → ``100`` (equal values give equal text)."""
    if not value.is_finite():
        return str(value)
    if value.is_zero():
        return "0"
    return format(value.normalize(), "f")


def canonical_data(value: Any) -> Any:
    """``value`` as JSON-ready data in canonical form: Decimals via :func:`decimal_text`,
    sets sorted, tuples as lists, enums by value, dates in ISO format."""
    if isinstance(value, dict):
        return {str(k): canonical_data(v) for k, v in value.items()}
    if isinstance(value, (set, frozenset)):
        return sorted((canonical_data(v) for v in value), key=canonical_json)
    if isinstance(value, (list, tuple)):
        return [canonical_data(v) for v in value]
    if isinstance(value, (Decimal, datetime, date, time, Enum)):
        return json_default(value)
    return value


def json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return decimal_text(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (set, frozenset)):
        return sorted((canonical_data(v) for v in value), key=canonical_json)
    raise TypeError(f"not JSON serialisable: {type(value).__name__}")


def canonical_json(data: Any) -> str:
    """Deterministic JSON: sorted keys, no whitespace, Decimals as strings."""
    return json.dumps(
        data, sort_keys=True, separators=(",", ":"), default=json_default, ensure_ascii=False
    )


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def hash_data(data: Any) -> str:
    return sha256_text(canonical_json(data))
