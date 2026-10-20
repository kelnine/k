"""Kill switches: one row per scope, every change audited in the same transaction."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kterminal.db import audit
from kterminal.db.models import AuditLogRow
from kterminal.db.repositories.kill_switches import (
    GLOBAL_SCOPE_ID,
    KillSwitchError,
    list_kill_switches,
    set_kill_switch,
)
from kterminal.paper.kill_switch import KillSwitchState
from tests.integration.db.helpers import T0, seed_catalog, seed_lab_subject

pytestmark = pytest.mark.integration


async def test_switches_are_upserted_per_scope_and_every_change_is_audited(
    session: AsyncSession,
) -> None:
    await seed_catalog(session)
    _, account = await seed_lab_subject(session, "sma_gold")

    on = await set_kill_switch(
        session,
        scope="global",
        active=True,
        reason=" CPI release ",
        changed_by="cli",
        ts=T0,
        close_positions=True,
    )
    assert (on.scope, on.scope_id, on.reason, on.close_positions) == (
        "GLOBAL",
        GLOBAL_SCOPE_ID,
        "CPI release",
        True,
    )
    await set_kill_switch(
        session,
        scope="ACCOUNT",
        scope_id=str(account.account_id),
        active=True,
        reason="drawdown",
        changed_by="cli",
        ts=T0,
    )
    await set_kill_switch(
        session, scope="strategy", scope_id="sma_gold", active=True, reason="review",
        changed_by="cli", ts=T0,
    )  # fmt: skip
    off = await set_kill_switch(
        session, scope="GLOBAL", active=False, reason="over", changed_by="cli", ts=T0,
        close_positions=True,
    )  # fmt: skip
    assert off.close_positions is False  # flattening only ever comes with an active switch

    switches = await list_kill_switches(session)
    assert [(s.scope, s.scope_id, s.active) for s in switches] == [
        ("ACCOUNT", str(account.account_id), True),
        ("GLOBAL", "*", False),
        ("STRATEGY", "sma_gold", True),
    ]
    state = KillSwitchState.from_records(switches)
    assert state.summary() == {
        "global": False,
        "accounts": [str(account.account_id)],
        "strategies": ["sma_gold"],
    }
    assert state.halt_reason(account.account_id, "other") == (
        f"ACCOUNT {account.account_id} kill switch active: drawdown"
    )

    rows = (
        await session.scalars(
            select(AuditLogRow)
            .where(AuditLogRow.entity_type == "kill_switch")
            .order_by(AuditLogRow.seq)
        )
    ).all()
    assert [(r.action, r.entity_id) for r in rows] == [
        ("killswitch.activate", "GLOBAL:*"),
        ("killswitch.activate", f"ACCOUNT:{account.account_id}"),
        ("killswitch.activate", "STRATEGY:sma_gold"),
        ("killswitch.deactivate", "GLOBAL:*"),
    ]
    assert rows[0].actor == "cli" and rows[0].data["reason"] == "CPI release"
    assert (await audit.verify(session)).ok


@pytest.mark.parametrize(
    ("scope", "scope_id", "reason", "error"),
    [
        ("everything", None, "x", "unknown scope 'EVERYTHING'"),
        ("GLOBAL", "acc", "x", "takes no --id"),
        ("ACCOUNT", None, "x", "needs an id"),
        ("ACCOUNT", "not-a-uuid", "x", "is not an account id"),
        ("ACCOUNT", "01900000-0000-7000-8000-000000000000", "x", "unknown account"),
        ("STRATEGY", "nobody", "x", "unknown strategy instance 'nobody'"),
        ("GLOBAL", None, "  ", "needs a reason"),
    ],
)
async def test_invalid_switches_are_refused(
    session: AsyncSession, scope: str, scope_id: str | None, reason: str, error: str
) -> None:
    with pytest.raises(KillSwitchError, match=error):
        await set_kill_switch(
            session,
            scope=scope,
            scope_id=scope_id,
            active=True,
            reason=reason,
            changed_by="cli",
            ts=T0,
        )
    assert await list_kill_switches(session) == []
