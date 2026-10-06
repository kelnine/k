"""The append-only, hash-chained audit log.

Every consequential action (a risk decision, an order submission, a kill-switch
change, a LIVE enablement …) is appended to ``audit_log``. Each entry stores
the hash of the previous entry and its own hash::

    hash = sha256(prev_hash || canonical_json({seq, ts, actor, action,
                                                entity_type, entity_id, data,
                                                correlation_id}))

so modifying, deleting or re-ordering any row breaks every hash after it, and
:func:`verify` reports the first broken link. Three layers protect the log:

1. the database rejects ``UPDATE``, ``DELETE`` and ``TRUNCATE`` (trigger
   installed by the migration; the application role should also be granted
   only ``INSERT, SELECT``);
2. appends are serialised with a transaction-level advisory lock, so the chain
   stays linear even with several writers (the price: audit writers queue
   behind each other until their transactions commit);
3. the hash chain makes any tampering by someone who bypasses (1) visible.

``data`` is hashed exactly as PostgreSQL's ``jsonb`` will return it (it is
normalised by a round trip through ``jsonb`` first), so verification never
reports a false break because of key order or number formatting.

:func:`canonical_json` is also the canonical form behind every configuration
hash in the database (account configuration versions); it produces the same
text as :func:`kterminal.strategy_engine.versioning.canonical_json`.
"""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from datetime import time as dt_time
from decimal import Decimal
from enum import Enum
from typing import Any, Final, NamedTuple
from uuid import UUID

from sqlalchemy import bindparam, insert, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from kterminal.core.clock import ensure_utc
from kterminal.db.locks import lock_key
from kterminal.db.models import AuditLogRow, table_of

GENESIS_HASH: Final = "0" * 64
"""``prev_hash`` of the very first entry."""

AUDIT_LOCK: Final = "kterminal.db.audit"

_NEXT_SEQ = text("SELECT nextval(pg_get_serial_sequence('audit_log', 'seq'))")


# ── canonical JSON ───────────────────────────────────────────────────────────
def _default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date, dt_time)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(f"not JSON serialisable: {type(value).__name__}")


def canonical_json(data: Any) -> str:
    """Deterministic JSON: sorted keys, no whitespace, Decimals/UUIDs/dates as strings."""
    return json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),
        default=_default,
        ensure_ascii=False,
        allow_nan=False,
    )


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def hash_document(data: Any) -> str:
    """SHA-256 of the canonical JSON of ``data`` (configuration hashes)."""
    return sha256_hex(canonical_json(data))


def json_safe(data: Any) -> Any:
    """``data`` as plain JSON values (Decimal → str, UUID → str, datetime → ISO-8601)."""
    return json.loads(canonical_json(data))


# ── entries ──────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class AuditEntry:
    seq: int
    ts: datetime
    prev_hash: str
    hash: str


class AuditVerification(NamedTuple):
    ok: bool
    checked: int  # entries examined (all of them when ok)
    first_bad_seq: int | None  # first entry whose content or link does not verify


def entry_hash(
    prev_hash: str,
    *,
    seq: int,
    ts: datetime,
    actor: str,
    action: str,
    entity_type: str,
    entity_id: str,
    data: Any,
    correlation_id: UUID | None,
) -> str:
    row = {
        "seq": seq,
        "ts": ensure_utc(ts).isoformat(),
        "actor": actor,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "data": data,
        "correlation_id": None if correlation_id is None else str(correlation_id),
    }
    return sha256_hex(prev_hash + canonical_json(row))


async def append(
    session: AsyncSession,
    *,
    actor: str,
    action: str,
    entity_type: str,
    entity_id: str | UUID | int,
    data: Mapping[str, Any],
    correlation_id: UUID | None = None,
    ts: datetime,
) -> AuditEntry:
    """Append one entry in the caller's transaction (the caller commits).

    The advisory lock is held until that transaction ends, so keep audit writes
    at the end of short transactions.
    """
    if not actor or not action or not entity_type:
        raise ValueError("audit entries need an actor, an action and an entity_type")
    ts = ensure_utc(ts)
    await session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": lock_key(AUDIT_LOCK)})
    stored_data = await _as_jsonb(session, json_safe(dict(data)))
    prev_hash = (
        await session.execute(select(AuditLogRow.hash).order_by(AuditLogRow.seq.desc()).limit(1))
    ).scalar_one_or_none() or GENESIS_HASH
    seq = int((await session.execute(_NEXT_SEQ)).scalar_one())
    entity = str(entity_id)
    digest = entry_hash(
        prev_hash,
        seq=seq,
        ts=ts,
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=entity,
        data=stored_data,
        correlation_id=correlation_id,
    )
    await session.execute(
        insert(AuditLogRow).values(
            seq=seq,
            ts=ts,
            actor=actor,
            action=action,
            entity_type=entity_type,
            entity_id=entity,
            data=stored_data,
            correlation_id=correlation_id,
            prev_hash=prev_hash,
            hash=digest,
        )
    )
    return AuditEntry(seq=seq, ts=ts, prev_hash=prev_hash, hash=digest)


async def _as_jsonb(session: AsyncSession, data: Any) -> Any:
    """``data`` exactly as ``jsonb`` stores and returns it (e.g. ``1e16`` comes back as an int)."""
    statement = (
        text("SELECT CAST(:data AS jsonb) AS data")
        .bindparams(bindparam("data", type_=JSONB))
        .columns(data=JSONB)
    )
    return (await session.execute(statement, {"data": data})).scalar_one()


async def verify(session: AsyncSession, *, batch_size: int = 1_000) -> AuditVerification:
    """Recompute the whole chain in ``seq`` order; report the first broken link."""
    log = table_of(AuditLogRow)
    # Plain column rows (not ORM objects), so nothing is served from the identity map.
    result = await session.stream(
        select(*log.c).order_by(log.c.seq).execution_options(yield_per=batch_size)
    )
    expected_prev = GENESIS_HASH
    checked = 0
    async for row in result:
        checked += 1
        recomputed = entry_hash(
            row.prev_hash,
            seq=row.seq,
            ts=row.ts,
            actor=row.actor,
            action=row.action,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            data=row.data,
            correlation_id=row.correlation_id,
        )
        if row.prev_hash != expected_prev or row.hash != recomputed:
            await result.close()
            return AuditVerification(ok=False, checked=checked, first_bad_seq=row.seq)
        expected_prev = row.hash
    return AuditVerification(ok=True, checked=checked, first_bad_seq=None)
