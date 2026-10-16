"""Where the lab's record ids come from.

Simulations use random UUIDv7s (:class:`RandomIds`). A forward session must be
able to rebuild its in-memory state after a restart by replaying its input
log, and the replay must produce *the same ids* as the original run so that
the rebuilt open trades, orders and ledger can be checked against the rows in
the database. :class:`SessionIds` therefore derives ids from the bar time
being processed and a sequence number, never from the wall clock or a random
source::

    48 bits  Unix milliseconds of the batch being processed (its close time)
     4 bits  version 7
    12 bits  sequence within the batch, high part
     2 bits  RFC 9562 variant
    14 bits  sequence within the batch, low part        (26-bit sequence in total)
    48 bits  session namespace (from the session's run id)

The ids are valid UUIDv7s, they sort chronologically (by batch, then in the
order the lab created them), and the first 80 bits — which the paper account
uses in client order ids — differ for every id of one batch. Two sessions
processing the same instant differ in the namespace.
"""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from kterminal.core.clock import ensure_utc
from kterminal.core.ids import uuid7

_SEQUENCE_BITS = 26
_MAX_SEQUENCE = (1 << _SEQUENCE_BITS) - 1
_NAMESPACE_MASK = (1 << 48) - 1


class IdSource(Protocol):
    """Callable that returns a fresh id; told which batch the lab is processing."""

    def __call__(self) -> UUID: ...

    def advance(self, at: datetime) -> None:
        """The lab is now processing the batch that closed at ``at``."""
        ...


class RandomIds:
    """Random, time-ordered UUIDv7s (wall clock). Used by simulations."""

    def __call__(self) -> UUID:
        return uuid7()

    def advance(self, at: datetime) -> None:
        return None


class SessionIds:
    """Deterministic UUIDv7-shaped ids: batch time + sequence + session namespace."""

    def __init__(self, namespace: int) -> None:
        self.namespace = namespace & _NAMESPACE_MASK
        self._at_ms: int | None = None
        self._sequence = 0

    @classmethod
    def for_run(cls, run_id: UUID) -> "SessionIds":
        """Ids for the forward session recorded as ``run_id`` (namespace = its last 48 bits)."""
        return cls(run_id.int)

    @property
    def at_ms(self) -> int | None:
        return self._at_ms

    def advance(self, at: datetime) -> None:
        ms = int(ensure_utc(at).timestamp() * 1000)
        if self._at_ms is not None and ms < self._at_ms:
            raise ValueError(f"session ids cannot go back in time ({at.isoformat()})")
        if ms != self._at_ms:
            self._at_ms = ms
            self._sequence = 0

    def __call__(self) -> UUID:
        if self._at_ms is None:
            raise RuntimeError("SessionIds.advance() must be called before the first id")
        sequence = self._sequence
        if sequence > _MAX_SEQUENCE:
            raise OverflowError("more than 2**26 ids in one batch")
        self._sequence += 1
        value = (
            (self._at_ms & ((1 << 48) - 1)) << 80
            | 0x7 << 76
            | (sequence >> 14) << 64
            | 0b10 << 62
            | (sequence & 0x3FFF) << 48
            | self.namespace
        )
        return UUID(int=value)


__all__ = ["IdSource", "RandomIds", "SessionIds"]
