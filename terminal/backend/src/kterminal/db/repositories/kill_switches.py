"""Kill switches: persisted, audited emergency stops for new risk.

A switch has a scope — ``GLOBAL`` (everything, ``scope_id`` ``*``), ``ACCOUNT``
(one account id) or ``STRATEGY`` (one strategy instance id). While a switch is
active no new entry may pass the risk checks of the accounts it covers;
exits, stop moves and flattening remain allowed. With ``close_positions`` the
covered positions are also closed at the next bar.

Rows live in ``kill_switches`` (one per scope and id, so they survive
restarts); every change is appended to the hash-chained audit log in the same
transaction. The trading engine reads the table at every bar batch. Repositories
never commit; the caller owns the transaction.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from kterminal.core.clock import ensure_utc
from kterminal.core.errors import KTerminalError
from kterminal.db import audit
from kterminal.db.models import (
    KILL_SWITCH_SCOPES,
    AccountRow,
    KillSwitchRow,
    StrategyInstanceRow,
    table_of,
)

GLOBAL_SCOPE_ID = "*"

_switches = table_of(KillSwitchRow)


class KillSwitchError(KTerminalError, ValueError):
    """A kill switch cannot be set as requested (unknown scope or target)."""


@dataclass(frozen=True, slots=True)
class KillSwitchRecord:
    scope: str  # GLOBAL | ACCOUNT | STRATEGY
    scope_id: str  # '*' for GLOBAL, an account id, or a strategy instance id
    active: bool
    close_positions: bool
    cancel_orders: bool
    reason: str
    changed_by: str
    changed_at: datetime

    def document(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "scope_id": self.scope_id,
            "active": self.active,
            "close_positions": self.close_positions,
            "cancel_orders": self.cancel_orders,
            "reason": self.reason,
            "changed_by": self.changed_by,
            "changed_at": self.changed_at.isoformat(),
        }


async def list_kill_switches(session: AsyncSession) -> list[KillSwitchRecord]:
    """Every switch row (active or not), in a stable order."""
    rows = (
        await session.execute(select(_switches).order_by(_switches.c.scope, _switches.c.scope_id))
    ).all()
    return [
        KillSwitchRecord(
            scope=row.scope,
            scope_id=row.scope_id,
            active=row.active,
            close_positions=row.close_positions,
            cancel_orders=row.cancel_orders,
            reason=row.reason,
            changed_by=row.changed_by,
            changed_at=row.changed_at,
        )
        for row in rows
    ]


async def set_kill_switch(
    session: AsyncSession,
    *,
    scope: str,
    scope_id: str | None = None,
    active: bool,
    reason: str,
    changed_by: str,
    ts: datetime,
    close_positions: bool = False,
    cancel_orders: bool = True,
) -> KillSwitchRecord:
    """Turn a switch on or off (upsert) and append the change to the audit log."""
    scope = scope.upper()
    if scope not in KILL_SWITCH_SCOPES:
        raise KillSwitchError(f"unknown scope {scope!r} (one of {', '.join(KILL_SWITCH_SCOPES)})")
    target = await _target(session, scope, scope_id)
    if not reason.strip():
        raise KillSwitchError("a kill switch change needs a reason")
    ts = ensure_utc(ts)
    record = KillSwitchRecord(
        scope=scope,
        scope_id=target,
        active=active,
        close_positions=close_positions and active,
        cancel_orders=cancel_orders,
        reason=reason.strip(),
        changed_by=changed_by,
        changed_at=ts,
    )
    values = record.document() | {"changed_at": ts}
    stmt = insert(_switches).values(values)
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=[_switches.c.scope, _switches.c.scope_id],
            set_={k: v for k, v in values.items() if k not in ("scope", "scope_id")},
        )
    )
    await audit.append(
        session,
        actor=changed_by,
        action="killswitch.activate" if active else "killswitch.deactivate",
        entity_type="kill_switch",
        entity_id=f"{scope}:{target}",
        data=record.document(),
        ts=ts,
    )
    return record


async def _target(session: AsyncSession, scope: str, scope_id: str | None) -> str:
    if scope == "GLOBAL":
        if scope_id not in (None, "", GLOBAL_SCOPE_ID):
            raise KillSwitchError("the GLOBAL kill switch takes no --id")
        return GLOBAL_SCOPE_ID
    if not scope_id:
        raise KillSwitchError(f"the {scope} kill switch needs an id")
    if scope == "ACCOUNT":
        try:
            account_id = UUID(scope_id)
        except ValueError:
            raise KillSwitchError(f"{scope_id!r} is not an account id") from None
        exists = (
            await session.execute(select(AccountRow.id).where(AccountRow.id == account_id))
        ).scalar_one_or_none()
        if exists is None:
            raise KillSwitchError(f"unknown account {scope_id}")
        return str(account_id)
    exists_instance = (
        await session.execute(
            select(StrategyInstanceRow.id).where(StrategyInstanceRow.id == scope_id)
        )
    ).scalar_one_or_none()
    if exists_instance is None:
        raise KillSwitchError(f"unknown strategy instance {scope_id!r}")
    return scope_id


__all__ = [
    "GLOBAL_SCOPE_ID",
    "KillSwitchError",
    "KillSwitchRecord",
    "list_kill_switches",
    "set_kill_switch",
]
