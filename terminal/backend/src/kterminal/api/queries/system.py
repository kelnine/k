"""Runtime status, kill switches and faults."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Final
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from kterminal.api.auth.users import usernames_by_id
from kterminal.api.schemas import (
    FaultOut,
    InstanceRuntime,
    KillSwitchEvent,
    KillSwitchOut,
    RuntimeStatus,
    RuntimeView,
)
from kterminal.db import audit
from kterminal.db import models as m

RUNTIME_STATE_KEY: Final = "paper.runtime"
"""``system_state`` key the forward paper runtime writes its status to."""

RUNTIME_STALE_AFTER: Final = timedelta(seconds=120)
"""A status older than this means the runtime is not running (or is stuck)."""

GLOBAL_SCOPE_ID: Final = "*"


# ── runtime ──────────────────────────────────────────────────────────────────
async def runtime_view(session: AsyncSession, now: datetime) -> RuntimeView:
    row = await session.get(m.SystemStateRow, RUNTIME_STATE_KEY)
    limit = RUNTIME_STALE_AFTER.total_seconds()
    if row is None:
        return RuntimeView(
            present=False,
            stale=True,
            age_seconds=None,
            stale_after_seconds=limit,
            status=None,
            error=None,
        )
    try:
        status = RuntimeStatus.model_validate(row.value)
    except ValidationError:
        status = None
    updated = (status.updated_at if status else None) or row.updated_at
    age = max(0.0, (now - updated).total_seconds())
    return RuntimeView(
        present=True,
        stale=age > limit,
        age_seconds=round(age, 1),
        stale_after_seconds=limit,
        status=status,
        error=None if status is not None else "the runtime status could not be read",
    )


def instance_runtime(view: RuntimeView, instance_id: str | None) -> InstanceRuntime | None:
    if instance_id is None or view.status is None:
        return None
    return view.status.instances.get(instance_id)


# ── kill switches ────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class KillSwitchState:
    global_active: bool = False
    accounts: frozenset[str] = field(default_factory=frozenset)
    strategies: frozenset[str] = field(default_factory=frozenset)

    def halts(self, account_id: UUID | str | None, instance_id: str | None) -> bool:
        return (
            self.global_active
            or (account_id is not None and str(account_id) in self.accounts)
            or (instance_id is not None and instance_id in self.strategies)
        )


async def kill_switch_rows(session: AsyncSession) -> list[m.KillSwitchRow]:
    rows = await session.execute(
        select(m.KillSwitchRow).order_by(m.KillSwitchRow.scope, m.KillSwitchRow.scope_id)
    )
    return list(rows.scalars())


def kill_switch_state(rows: list[m.KillSwitchRow]) -> KillSwitchState:
    active = [row for row in rows if row.active]
    return KillSwitchState(
        global_active=any(row.scope == "GLOBAL" for row in active),
        accounts=frozenset(row.scope_id for row in active if row.scope == "ACCOUNT"),
        strategies=frozenset(row.scope_id for row in active if row.scope == "STRATEGY"),
    )


async def kill_switches_out(
    session: AsyncSession, rows: list[m.KillSwitchRow]
) -> list[KillSwitchOut]:
    account_ids = []
    user_ids = set()
    for row in rows:
        if row.scope == "ACCOUNT":
            account_ids.append(_uuid(row.scope_id))
        if row.changed_by.startswith("user:") and (uid := _uuid(row.changed_by[5:])):
            user_ids.add(uid)
    names: dict[str, str] = {}
    wanted = [a for a in account_ids if a is not None]
    if wanted:
        result = await session.execute(
            select(m.AccountRow.id, m.AccountRow.name).where(m.AccountRow.id.in_(wanted))
        )
        names = {str(r.id): r.name for r in result}
    users = await usernames_by_id(session, user_ids)
    out = []
    for row in rows:
        if row.scope == "GLOBAL":
            label = "all trading"
        elif row.scope == "ACCOUNT":
            label = names.get(row.scope_id, row.scope_id)
        else:
            label = row.scope_id
        uid = _uuid(row.changed_by[5:]) if row.changed_by.startswith("user:") else None
        out.append(
            KillSwitchOut(
                scope=row.scope,  # type: ignore[arg-type]  # CHECK constraint: one of the three
                scope_id=row.scope_id,
                label=label,
                active=row.active,
                close_positions=row.close_positions,
                cancel_orders=row.cancel_orders,
                reason=row.reason,
                changed_by=row.changed_by,
                changed_by_username=users.get(uid) if uid else None,
                changed_at=row.changed_at,
            )
        )
    return out


async def kill_switch_history(session: AsyncSession, limit: int = 50) -> list[KillSwitchEvent]:
    rows = await session.execute(
        select(m.AuditLogRow)
        .where(m.AuditLogRow.entity_type == "kill_switch")
        .order_by(m.AuditLogRow.seq.desc())
        .limit(limit)
    )
    events = []
    for row in rows.scalars():
        scope, _, scope_id = row.entity_id.partition(":")
        events.append(
            KillSwitchEvent(
                seq=row.seq,
                ts=row.ts,
                actor=row.actor,
                action=row.action,
                scope=scope,
                scope_id=scope_id,
                data=dict(row.data or {}),
            )
        )
    return events


async def set_kill_switch(
    session: AsyncSession,
    *,
    scope: str,
    scope_id: str,
    active: bool,
    reason: str,
    close_positions: bool,
    user_id: UUID,
    username: str,
    now: datetime,
) -> None:
    """Write the switch the runtime reads at every batch, and its audit entry, in one
    transaction (the caller commits)."""
    values = {
        "scope": scope,
        "scope_id": scope_id,
        "active": active,
        "close_positions": close_positions and active,
        "cancel_orders": True,
        "reason": reason,
        "changed_by": f"user:{user_id}",
        "changed_at": now,
    }
    stmt = pg_insert(m.KillSwitchRow).values(**values)
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=[m.KillSwitchRow.scope, m.KillSwitchRow.scope_id],
            set_={k: v for k, v in values.items() if k not in ("scope", "scope_id")},
        )
    )
    await audit.append(
        session,
        actor=f"user:{user_id}",
        action="killswitch.activate" if active else "killswitch.release",
        entity_type="kill_switch",
        entity_id=f"{scope}:{scope_id}",
        data={
            "scope": scope,
            "scope_id": scope_id,
            "active": active,
            "reason": reason,
            "close_positions": close_positions and active,
            "username": username,
        },
        ts=now,
    )


# ── faults ───────────────────────────────────────────────────────────────────
async def faults(
    session: AsyncSession,
    *,
    limit: int,
    offset: int,
    instance_id: str | None = None,
    run_id: UUID | None = None,
) -> tuple[list[FaultOut], int]:
    conditions = []
    if instance_id:
        conditions.append(m.SystemErrorRow.strategy_instance_id == instance_id)
    if run_id:
        conditions.append(m.SystemErrorRow.run_id == run_id)
    total = (
        await session.execute(select(func.count()).select_from(m.SystemErrorRow).where(*conditions))
    ).scalar_one()
    rows = await session.execute(
        select(m.SystemErrorRow)
        .where(*conditions)
        .order_by(m.SystemErrorRow.ts.desc())
        .limit(limit)
        .offset(offset)
    )
    items = [
        FaultOut(
            id=row.id,
            ts=row.ts,
            component=row.component,
            severity=row.severity,
            message=row.message,
            strategy_instance_id=row.strategy_instance_id,
            run_id=row.run_id,
            context=dict(row.context or {}),
        )
        for row in rows.scalars()
    ]
    return items, int(total)


async def faults_since(session: AsyncSession, since: datetime) -> int:
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(m.SystemErrorRow)
                .where(m.SystemErrorRow.ts >= since)
            )
        ).scalar_one()
    )


def _uuid(text: str) -> UUID | None:
    try:
        return UUID(text)
    except ValueError:
        return None
