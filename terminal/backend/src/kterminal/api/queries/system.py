"""Runtime status, kill switches and faults."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Final
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import and_, func, or_, select
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
from kterminal.db import models as m
from kterminal.db.repositories import kill_switches as repository
from kterminal.db.repositories.kill_switches import KillSwitchRecord, list_kill_switches
from kterminal.paper.pg_forward import KILL_SWITCH_APPLIED, STATUS_KEY

RUNTIME_STATE_KEY: Final = STATUS_KEY
"""``system_state`` key the forward paper runtime writes its status to."""

USER_ACTOR: Final = "user:"
"""Audit actors and ``kill_switches.changed_by`` of dashboard users: ``user:<user id>``."""

RUNTIME_STALE_AFTER: Final = timedelta(seconds=120)
"""A status older than this means the runtime is not running (or is stuck)."""


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


async def kill_switch_rows(session: AsyncSession) -> list[KillSwitchRecord]:
    """Every switch the runtime reads (active or not), from the kill-switch repository."""
    return await list_kill_switches(session)


def kill_switch_state(rows: list[KillSwitchRecord]) -> KillSwitchState:
    active = [row for row in rows if row.active]
    return KillSwitchState(
        global_active=any(row.scope == "GLOBAL" for row in active),
        accounts=frozenset(row.scope_id for row in active if row.scope == "ACCOUNT"),
        strategies=frozenset(row.scope_id for row in active if row.scope == "STRATEGY"),
    )


async def kill_switches_out(
    session: AsyncSession, rows: list[KillSwitchRecord]
) -> list[KillSwitchOut]:
    account_ids = [_uuid(row.scope_id) for row in rows if row.scope == "ACCOUNT"]
    names: dict[str, str] = {}
    wanted = [a for a in account_ids if a is not None]
    if wanted:
        result = await session.execute(
            select(m.AccountRow.id, m.AccountRow.name).where(m.AccountRow.id.in_(wanted))
        )
        names = {str(r.id): r.name for r in result}
    users = await _usernames(session, [row.changed_by for row in rows])
    out = []
    for row in rows:
        if row.scope == "GLOBAL":
            label = "all trading"
        elif row.scope == "ACCOUNT":
            label = names.get(row.scope_id, row.scope_id)
        else:
            label = row.scope_id
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
                changed_by_username=users.get(row.changed_by),
                changed_at=row.changed_at,
            )
        )
    return out


async def kill_switch_history(session: AsyncSession, limit: int = 50) -> list[KillSwitchEvent]:
    """Kill-switch changes (``killswitch.activate`` / ``.deactivate``) and the moments a
    forward session applied them (``killswitch.applied``), newest first."""
    rows = list(
        (
            await session.execute(
                select(m.AuditLogRow)
                .where(
                    or_(
                        m.AuditLogRow.entity_type == "kill_switch",
                        and_(
                            m.AuditLogRow.entity_type == "run",
                            m.AuditLogRow.action == KILL_SWITCH_APPLIED,
                        ),
                    )
                )
                .order_by(m.AuditLogRow.seq.desc())
                .limit(limit)
            )
        ).scalars()
    )
    users = await _usernames(session, [row.actor for row in rows])
    events = []
    for row in rows:
        if row.entity_type == "run":
            scope, scope_id = "RUN", row.entity_id
        else:
            scope, _, scope_id = row.entity_id.partition(":")
        events.append(
            KillSwitchEvent(
                seq=row.seq,
                ts=row.ts,
                actor=row.actor,
                actor_username=users.get(row.actor),
                action=row.action,
                scope=scope,
                scope_id=scope_id,
                data=dict(row.data or {}),
            )
        )
    return events


async def _usernames(session: AsyncSession, actors: list[str]) -> dict[str, str]:
    """``{"user:<id>": username}`` for the dashboard users among ``actors``."""
    ids = {
        uid
        for actor in actors
        if actor.startswith(USER_ACTOR) and (uid := _uuid(actor.removeprefix(USER_ACTOR)))
    }
    names = await usernames_by_id(session, ids)
    return {f"{USER_ACTOR}{uid}": name for uid, name in names.items()}


async def set_kill_switch(
    session: AsyncSession,
    *,
    scope: str,
    scope_id: str,
    active: bool,
    reason: str,
    close_positions: bool,
    user_id: UUID,
    now: datetime,
) -> KillSwitchRecord:
    """Write the switch the runtime reads before every minute, and its audit entry, through
    the kill-switch repository (the caller commits)."""
    return await repository.set_kill_switch(
        session,
        scope=scope,
        scope_id=scope_id,
        active=active,
        reason=reason,
        changed_by=f"{USER_ACTOR}{user_id}",
        ts=now,
        close_positions=close_positions,
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
