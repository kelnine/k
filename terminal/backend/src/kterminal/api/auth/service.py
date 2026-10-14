"""The API's authentication service: one per process, kept on ``app.state.auth``."""

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from fastapi import Response

from kterminal.api.auth.limiter import LoginLimiter
from kterminal.api.auth.passwords import Passwords
from kterminal.api.auth.settings import AuthSettings
from kterminal.api.auth.tokens import SessionClaims, SessionSigner
from kterminal.api.auth.users import User
from kterminal.observability.logging import get_logger

SESSION_COOKIE = "kt_session"
CSRF_HEADER = "X-CSRF-Token"

_log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Principal:
    """The signed-in user of a request."""

    user: User
    claims: SessionClaims


class AuthService:
    def __init__(self, settings: AuthSettings, passwords: Passwords | None = None) -> None:
        self.settings = settings
        if settings.session_secret is None:
            secret = secrets.token_urlsafe(48)
            _log.warning(
                "auth.ephemeral_session_secret",
                detail="KT_AUTH__SESSION_SECRET is not set: sessions end when the API restarts",
            )
        else:
            secret = settings.session_secret.get_secret_value().strip()
        self.signer = SessionSigner(secret, timedelta(minutes=settings.session_ttl_minutes))
        self.passwords = passwords or Passwords()
        self.limiter = LoginLimiter(
            max_failures=settings.max_failed_logins,
            max_failures_per_ip=settings.max_failed_logins_per_ip,
            window=timedelta(minutes=settings.lockout_minutes),
        )

    def set_session_cookie(self, response: Response, token: str, expires_at: datetime) -> None:
        response.set_cookie(
            SESSION_COOKIE,
            token,
            expires=expires_at,
            path="/",
            secure=self.settings.cookie_secure,
            httponly=True,
            samesite="strict",
        )

    def clear_session_cookie(self, response: Response) -> None:
        response.delete_cookie(
            SESSION_COOKIE,
            path="/",
            secure=self.settings.cookie_secure,
            httponly=True,
            samesite="strict",
        )
