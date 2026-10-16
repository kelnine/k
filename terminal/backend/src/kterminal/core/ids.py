"""Identifier generation.

All primary keys are UUID version 7 (RFC 9562): a 48-bit Unix-millisecond
timestamp followed by random bits. They sort by creation time, which keeps
B-tree indexes compact and makes IDs roughly chronological in logs.
(``uuid.uuid7`` only arrives in Python 3.14, hence this implementation.)
"""

import os
import time
import uuid
from datetime import UTC, datetime

_TIMESTAMP_MASK = (1 << 48) - 1
_RAND_A_MASK = (1 << 12) - 1
_RAND_B_MASK = (1 << 62) - 1


def uuid7() -> uuid.UUID:
    """Return a new, time-ordered UUIDv7."""
    unix_ms = time.time_ns() // 1_000_000
    rand = int.from_bytes(os.urandom(10), "big")
    value = (
        (unix_ms & _TIMESTAMP_MASK) << 80
        | 0x7 << 76  # version
        | ((rand >> 62) & _RAND_A_MASK) << 64
        | 0b10 << 62  # RFC 9562 variant
        | (rand & _RAND_B_MASK)
    )
    return uuid.UUID(int=value)


def uuid7_time(value: uuid.UUID) -> datetime:
    """Creation time embedded in a UUIDv7 (millisecond precision, UTC)."""
    if value.version != 7:
        raise ValueError(f"not a UUIDv7: {value}")
    return datetime.fromtimestamp((value.int >> 80) / 1000, tz=UTC)


def new_correlation_id() -> uuid.UUID:
    """Correlation IDs follow one request/bar through every record it causes."""
    return uuid7()
