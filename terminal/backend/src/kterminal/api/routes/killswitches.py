"""Kill switches: read them all (any role); activate or release one (OPERATOR and up).

Changes go through :mod:`kterminal.db.repositories.kill_switches` — the same
code as ``kterminal killswitch on/off`` — which upserts the ``kill_switches``
row and appends ``killswitch.activate`` / ``killswitch.deactivate`` to the audit
log in one transaction. The forward runtime reads the table before every
minute (docs/12 §12.7). Activating is always allowed and needs no confirmation
(a risk-reducing action); releasing a switch re-enables trading, so it needs
the operator's password again (docs/09 §9.2: re-authentication for sensitive
actions; TOTP joins it once 2FA exists).
"""

import asyncio
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select

from kterminal.api.auth.deps import get_auth, require_role
from kterminal.api.auth.service import AuthService, Principal
from kterminal.api.auth.users import Role
from kterminal.api.errors import ApiError
from kterminal.api.queries.system import (
    kill_switch_history,
    kill_switch_rows,
    kill_switches_out,
    set_kill_switch,
)
from kterminal.api.routes.common import ClockDep, DbSession
from kterminal.api.schemas import KillSwitchesOut, KillSwitchOut, KillSwitchRequest
from kterminal.db import models as m
from kterminal.db.repositories.kill_switches import GLOBAL_SCOPE_ID, KillSwitchError

router = APIRouter(prefix="/kill-switches", tags=["kill switches"])

Operator = Annotated[Principal, Depends(require_role(Role.OPERATOR))]


@router.get("", response_model=KillSwitchesOut)
async def kill_switches(session: DbSession) -> KillSwitchesOut:
    return KillSwitchesOut(
        switches=await kill_switches_out(session, await kill_switch_rows(session)),
        history=await kill_switch_history(session),
    )


@router.post("", response_model=KillSwitchOut)
async def set_switch(
    body: KillSwitchRequest,
    principal: Operator,
    auth: Annotated[AuthService, Depends(get_auth)],
    session: DbSession,
    clock: ClockDep,
) -> KillSwitchOut:
    scope_id = await _validated_scope_id(session, body.scope, body.scope_id)
    if not body.active:
        password = body.password.get_secret_value() if body.password else ""
        confirmed = bool(password) and await asyncio.to_thread(
            auth.passwords.verify, principal.user.password_hash, password
        )
        if not confirmed:
            raise ApiError(403, "REAUTH_REQUIRED", "enter your password to release a kill switch")
    try:
        record = await set_kill_switch(
            session,
            scope=body.scope,
            scope_id=scope_id,
            active=body.active,
            reason=body.reason,
            close_positions=body.close_positions,
            user_id=principal.user.id,
            now=clock.now(),
        )
    except KillSwitchError as exc:
        raise ApiError(422, "INVALID_KILL_SWITCH", str(exc)) from None
    await session.commit()
    (out,) = await kill_switches_out(session, [record])
    return out


async def _validated_scope_id(session: DbSession, scope: str, scope_id: str) -> str:
    if scope == "GLOBAL":
        return GLOBAL_SCOPE_ID
    if scope == "ACCOUNT":
        try:
            account_id = UUID(scope_id)
        except ValueError:
            raise ApiError(
                422, "INVALID_SCOPE_ID", "an account kill switch needs an account id"
            ) from None
        if await session.get(m.AccountRow, account_id) is None:
            raise ApiError(404, "NOT_FOUND", "account not found")
        return str(account_id)
    exists = (
        await session.execute(
            select(m.StrategyInstanceRow.id).where(m.StrategyInstanceRow.id == scope_id)
        )
    ).scalar_one_or_none()
    if exists is None:
        raise ApiError(404, "NOT_FOUND", "strategy instance not found")
    return scope_id
