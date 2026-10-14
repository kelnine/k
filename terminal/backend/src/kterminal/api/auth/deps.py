"""FastAPI dependencies: the signed-in user, role checks and CSRF protection."""

from collections.abc import Awaitable, Callable
from typing import Annotated, cast

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from kterminal.api.auth.service import CSRF_HEADER, SESSION_COOKIE, AuthService, Principal
from kterminal.api.auth.tokens import SessionClaims
from kterminal.api.auth.users import Role, get_user, session_revoked
from kterminal.api.deps import get_clock, get_session
from kterminal.api.errors import ApiError
from kterminal.core.clock import Clock

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def get_auth(request: Request) -> AuthService:
    return cast(AuthService, request.app.state.auth)


def _unauthenticated() -> ApiError:
    return ApiError(401, "NOT_AUTHENTICATED", "sign in to continue")


async def session_claims(
    request: Request,
    auth: Annotated[AuthService, Depends(get_auth)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> SessionClaims:
    """The claims of a validly signed, unexpired session cookie, or 401 (no database needed)."""
    token = request.cookies.get(SESSION_COOKIE)
    claims = auth.signer.verify(token, clock.now()) if token else None
    if claims is None:
        raise _unauthenticated()
    return claims


async def current_principal(
    request: Request,
    claims: Annotated[SessionClaims, Depends(session_claims)],
    auth: Annotated[AuthService, Depends(get_auth)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Principal:
    """The user behind the session, or 401.

    The user is loaded on every request, so disabling a user, changing their
    password or signing out takes effect immediately.
    """
    user = await get_user(session, claims.user_id)
    if (
        user is None
        or user.disabled
        or auth.signer.password_tag(user.password_hash) != claims.password_tag
        or await session_revoked(session, claims.session_id)
    ):
        raise _unauthenticated()
    request.state.principal = user.username
    return Principal(user=user, claims=claims)


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]


async def csrf_protect(
    request: Request,
    principal: CurrentPrincipal,
    auth: Annotated[AuthService, Depends(get_auth)],
) -> None:
    """State-changing requests must echo the session's CSRF token in ``X-CSRF-Token``."""
    if request.method in SAFE_METHODS:
        return
    if not auth.signer.csrf_valid(principal.claims.session_id, request.headers.get(CSRF_HEADER)):
        raise ApiError(403, "CSRF_TOKEN_INVALID", "missing or invalid CSRF token; reload the page")


def require_role(role: Role) -> Callable[[Principal], Awaitable[Principal]]:
    async def check(principal: CurrentPrincipal) -> Principal:
        if not principal.user.role.allows(role):
            raise ApiError(403, "FORBIDDEN", f"this action needs the {role.value} role")
        return principal

    return check
