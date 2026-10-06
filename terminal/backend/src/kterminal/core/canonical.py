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


def _default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    raise TypeError(f"not JSON serialisable: {type(value).__name__}")


def canonical_json(data: Any) -> str:
    """Deterministic JSON: sorted keys, no whitespace, Decimals as strings."""
    return json.dumps(
        data, sort_keys=True, separators=(",", ":"), default=_default, ensure_ascii=False
    )


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def hash_data(data: Any) -> str:
    return sha256_text(canonical_json(data))
