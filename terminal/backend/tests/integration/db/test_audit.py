"""The audit log is append-only and hash-chained; tampering is blocked or detected."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from kterminal.core.errors import ClockError
from kterminal.core.ids import new_correlation_id, uuid7
from kterminal.db import audit
from kterminal.db.partitions import ensure_monthly_partitions

pytestmark = pytest.mark.integration

T0 = datetime(2026, 10, 6, 14, 0, tzinfo=UTC)


async def _append_three(session: AsyncSession) -> list[audit.AuditEntry]:
    decision = uuid7()
    return [
        await audit.append(
            session,
            actor="system:engine",
            action="risk.decision",
            entity_type="risk_decision",
            entity_id=decision,
            data={"approved": True, "risk_pct": Decimal("0.50"), "rules": ["max_open", "daily"]},
            correlation_id=new_correlation_id(),
            ts=T0,
        ),
        await audit.append(
            session,
            actor="user:operator",
            action="killswitch.activate",
            entity_type="kill_switch",
            entity_id="GLOBAL:*",
            data={"reason": "manual", "close_positions": False},
            ts=T0 + timedelta(seconds=1),
        ),
        await audit.append(
            session,
            actor="strategy:demo_sma_fast",
            action="order.submit",
            entity_type="order",
            entity_id=42,
            # Values jsonb normalises: large float, nested keys out of order, unicode, dates.
            data={"z": {"b": 1, "a": 2}, "big": 1e16, "note": "Δ ≥ 0", "day": date(2026, 10, 6)},
            ts=T0 + timedelta(seconds=2),
        ),
    ]


async def test_entries_are_chained_and_verify(session: AsyncSession) -> None:
    first, second, third = await _append_three(session)
    assert first.prev_hash == audit.GENESIS_HASH
    assert second.prev_hash == first.hash
    assert third.prev_hash == second.hash
    assert first.seq < second.seq < third.seq
    assert await audit.verify(session) == audit.AuditVerification(True, 3, None)


async def test_an_empty_log_verifies(session: AsyncSession) -> None:
    assert await audit.verify(session) == (True, 0, None)


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit_log SET actor = 'attacker'",
        "DELETE FROM audit_log",
        "TRUNCATE audit_log",
        "TRUNCATE audit_log_default",
    ],
)
async def test_the_database_rejects_tampering(session: AsyncSession, statement: str) -> None:
    await _append_three(session)
    with pytest.raises(DBAPIError, match="append-only"):
        async with session.begin_nested():
            await session.execute(text(statement))
    assert (await audit.verify(session)).ok


async def test_monthly_audit_partitions_are_guarded_too(session: AsyncSession) -> None:
    await ensure_monthly_partitions(session, today=T0.date(), tables=("audit_log",))
    await _append_three(session)
    partition = (
        await session.execute(text("SELECT DISTINCT tableoid::regclass::text FROM audit_log"))
    ).scalar_one()
    assert partition == "audit_log_p202610"
    for template in ("TRUNCATE {}", "DELETE FROM {}", "UPDATE {} SET data = '{{}}'"):
        statement = template.format(partition)
        with pytest.raises(DBAPIError, match="append-only"):
            async with session.begin_nested():
                await session.execute(text(statement))


async def test_verify_detects_a_modified_entry(session: AsyncSession) -> None:
    _, second, _ = await _append_three(session)
    # Simulate an attacker who can bypass the guard (the table owner disabling it).
    await session.execute(text("ALTER TABLE audit_log DISABLE TRIGGER audit_log_append_only"))
    await session.execute(
        text('UPDATE audit_log SET data = \'{"reason": "nothing to see"}\' WHERE seq = :s'),
        {"s": second.seq},
    )
    await session.execute(text("ALTER TABLE audit_log ENABLE TRIGGER audit_log_append_only"))
    assert await audit.verify(session) == (False, 2, second.seq)


async def test_verify_detects_a_deleted_entry(session: AsyncSession) -> None:
    _, second, third = await _append_three(session)
    await session.execute(text("ALTER TABLE audit_log DISABLE TRIGGER audit_log_append_only"))
    await session.execute(text("DELETE FROM audit_log WHERE seq = :s"), {"s": second.seq})
    await session.execute(text("ALTER TABLE audit_log ENABLE TRIGGER audit_log_append_only"))
    assert await audit.verify(session) == (False, 2, third.seq)


async def test_verify_detects_a_rewritten_hash(session: AsyncSession) -> None:
    """Recomputing one entry's hash still breaks the link to the next one."""
    first, second, _ = await _append_three(session)
    forged = audit.entry_hash(
        first.prev_hash,
        seq=first.seq,
        ts=first.ts,
        actor="attacker",
        action="risk.decision",
        entity_type="risk_decision",
        entity_id="x",
        data={},
        correlation_id=None,
    )
    await session.execute(text("ALTER TABLE audit_log DISABLE TRIGGER audit_log_append_only"))
    await session.execute(
        text(
            "UPDATE audit_log SET actor = 'attacker', entity_id = 'x', data = '{}', "
            "correlation_id = NULL, hash = :h WHERE seq = :s"
        ),
        {"h": forged, "s": first.seq},
    )
    await session.execute(text("ALTER TABLE audit_log ENABLE TRIGGER audit_log_append_only"))
    assert await audit.verify(session) == (False, 2, second.seq)


async def test_append_requires_aware_time_and_identity(session: AsyncSession) -> None:
    with pytest.raises(ClockError):
        await audit.append(
            session,
            actor="system",
            action="x",
            entity_type="t",
            entity_id="1",
            data={},
            ts=datetime(2026, 10, 6, 12, 0),  # noqa: DTZ001 - deliberately naive
        )
    with pytest.raises(ValueError, match="actor"):
        await audit.append(
            session, actor="", action="x", entity_type="t", entity_id="1", data={}, ts=T0
        )


def test_canonical_json_matches_the_strategy_engine() -> None:
    from kterminal.strategy_engine.versioning import canonical_json

    document = {"b": [Decimal("1.50"), 2], "a": {"when": T0, "set": {3, 1}}, "unicode": "Δ"}
    assert audit.canonical_json(document) == canonical_json(document)
    assert audit.hash_document(document) == audit.sha256_hex(canonical_json(document))
