"""Sign-in, sign-out and the current session."""

import asyncio
import math
from dataclasses import replace
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from kterminal.api.auth.deps import CurrentPrincipal, csrf_protect, get_auth
from kterminal.api.auth.service import AuthService, Principal
from kterminal.api.auth.users import (
    get_user_by_username,
    normalize_username,
    revoke_session,
    set_password_hash,
)
from kterminal.api.deps import get_clock, get_session
from kterminal.api.errors import ApiError
from kterminal.api.schemas import LoginRequest, SessionOut, UserOut
from kterminal.core.clock import Clock
from kterminal.db import audit
from kterminal.observability.logging import get_logger

router = APIRouter(prefix="/auth", tags=["auth"])

_log = get_logger(__name__)

Auth = Annotated[AuthService, Depends(get_auth)]
Session = Annotated[AsyncSession, Depends(get_session)]
Now = Annotated[Clock, Depends(get_clock)]


def _session_out(auth: AuthService, principal: Principal) -> SessionOut:
    user = principal.user
    return SessionOut(
        user=UserOut(id=user.id, username=user.username, role=user.role),
        csrf_token=auth.signer.csrf_token(principal.claims.session_id),
        expires_at=principal.claims.expires_at,
    )


@router.post(
    "/login",
    response_model=SessionOut,
    responses={401: {"description": "Wrong username or password"}, 429: {"description": "Locked"}},
)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    auth: Auth,
    session: Session,
    clock: Now,
) -> SessionOut:
    """Check the password (argon2id) and open a session (``HttpOnly; SameSite=Strict`` cookie).

    Failed attempts are rate-limited per username and per client address; a locked
    username gets ``429`` with ``Retry-After`` whether or not it exists.
    """
    now = clock.now()
    address = request.client.host if request.client else "unknown"
    username = normalize_username(body.username)
    blocked_until = auth.limiter.blocked_until(username, address, now)
    if blocked_until is not None:
        retry = max(1, math.ceil((blocked_until - now).total_seconds()))
        raise ApiError(
            429,
            "LOGIN_LOCKED",
            "too many failed sign-ins; try again later",
            headers={"Retry-After": str(retry)},
        )
    password = body.password.get_secret_value()
    user = await get_user_by_username(session, username)
    if user is None:
        await asyncio.to_thread(auth.passwords.verify_decoy, password)
        valid = False
    else:
        valid = await asyncio.to_thread(auth.passwords.verify, user.password_hash, password)
    if user is None or not valid or user.disabled:
        locked = auth.limiter.record_failure(username, address, now)
        _log.warning("auth.login_failed", username=username[:64], client=address, locked=locked)
        if locked:
            await audit.append(
                session,
                actor="system:api",
                action="auth.lockout",
                entity_type="user",
                entity_id=str(user.id) if user else f"unknown:{username[:64]}",
                data={"username": username[:64], "client": address},
                ts=now,
            )
            await session.commit()
        raise ApiError(401, "INVALID_CREDENTIALS", "wrong username or password")

    auth.limiter.record_success(username)
    if auth.passwords.needs_rehash(user.password_hash):
        new_hash = await asyncio.to_thread(auth.passwords.hash, password)
        await set_password_hash(session, user.id, new_hash)
        user = replace(user, password_hash=new_hash)
    token, claims = auth.signer.issue(user.id, user.password_hash, now)
    await audit.append(
        session,
        actor=f"user:{user.id}",
        action="auth.login",
        entity_type="user",
        entity_id=user.id,
        data={"username": user.username, "client": address},
        ts=now,
    )
    await session.commit()
    auth.set_session_cookie(response, token, claims)
    _log.info("auth.login", username=user.username, client=address)
    return _session_out(auth, Principal(user=user, claims=claims))


@router.post(
    "/logout", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(csrf_protect)]
)
async def logout(
    principal: CurrentPrincipal,
    response: Response,
    auth: Auth,
    session: Session,
    clock: Now,
) -> None:
    """End the session everywhere (its id is refused until the cookie would have expired)."""
    now = clock.now()
    await revoke_session(
        session, principal.claims.session_id, expires_at=principal.claims.expires_at, now=now
    )
    await audit.append(
        session,
        actor=f"user:{principal.user.id}",
        action="auth.logout",
        entity_type="user",
        entity_id=principal.user.id,
        data={"username": principal.user.username},
        ts=now,
    )
    await session.commit()
    auth.clear_session_cookie(response)


@router.get("/me", response_model=SessionOut)
async def me(principal: CurrentPrincipal, auth: Auth) -> SessionOut:
    """The signed-in user and the CSRF token to send with state-changing requests."""
    return _session_out(auth, principal)
