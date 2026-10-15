"""Signed session cookies and CSRF tokens.

A session is a signed, self-contained token in an ``HttpOnly; SameSite=Strict``
cookie::

    v1.<base64url(JSON claims)>.<base64url(HMAC-SHA256)>

The claims hold the user id, a random session id, the issue and expiry times
and a tag derived from the user's password hash. On every request the API
checks the signature and expiry, then loads the user: a disabled user, a
changed password (different tag) or a signed-out session (revoked id) ends the
session immediately.

The CSRF token is ``HMAC(csrf key, session id)``. The dashboard receives it in
the JSON body of sign-in and ``/auth/me`` and sends it back in the
``X-CSRF-Token`` header of every state-changing request; a cross-site page can
neither read it nor compute it.

Separate keys for sessions, CSRF tokens and password tags are derived from
the one configured secret.
"""

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from kterminal.core.clock import ensure_utc

TOKEN_VERSION = "v1"  # noqa: S105 - the token format tag, not a secret


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _derive(secret: bytes, purpose: str) -> bytes:
    return hmac.new(secret, f"kterminal.auth.{purpose}".encode(), hashlib.sha256).digest()


@dataclass(frozen=True, slots=True)
class SessionClaims:
    user_id: UUID
    session_id: str
    issued_at: datetime
    expires_at: datetime
    password_tag: str


class SessionSigner:
    def __init__(self, secret: str, ttl: timedelta) -> None:
        if len(secret) < 32:
            raise ValueError("the session secret must be at least 32 characters")
        raw = secret.encode()
        self._session_key = _derive(raw, "session")
        self._csrf_key = _derive(raw, "csrf")
        self._password_key = _derive(raw, "password-tag")
        self.ttl = ttl

    def password_tag(self, password_hash: str) -> str:
        """Binds a session to the password it was opened with."""
        digest = hmac.new(self._password_key, password_hash.encode(), hashlib.sha256).digest()
        return _b64encode(digest[:12])

    def issue(self, user_id: UUID, password_hash: str, now: datetime) -> tuple[str, SessionClaims]:
        now = ensure_utc(now).replace(microsecond=0)
        claims = SessionClaims(
            user_id=user_id,
            session_id=secrets.token_urlsafe(18),
            issued_at=now,
            expires_at=now + self.ttl,
            password_tag=self.password_tag(password_hash),
        )
        document = {
            "u": str(claims.user_id),
            "s": claims.session_id,
            "i": int(claims.issued_at.timestamp()),
            "e": int(claims.expires_at.timestamp()),
            "p": claims.password_tag,
        }
        payload = _b64encode(json.dumps(document, separators=(",", ":")).encode())
        return f"{TOKEN_VERSION}.{payload}.{self._sign(payload)}", claims

    def verify(self, token: str, now: datetime) -> SessionClaims | None:
        """The claims of a valid, unexpired token; ``None`` for anything else."""
        if len(token) > 1024:
            return None
        parts = token.split(".")
        if len(parts) != 3 or parts[0] != TOKEN_VERSION:
            return None
        _, payload, signature = parts
        if not hmac.compare_digest(signature, self._sign(payload)):
            return None
        try:
            document = json.loads(_b64decode(payload))
            claims = SessionClaims(
                user_id=UUID(document["u"]),
                session_id=str(document["s"]),
                issued_at=datetime.fromtimestamp(int(document["i"]), UTC),
                expires_at=datetime.fromtimestamp(int(document["e"]), UTC),
                password_tag=str(document["p"]),
            )
        except (ValueError, KeyError, TypeError):
            return None
        if ensure_utc(now) >= claims.expires_at:
            return None
        return claims

    def csrf_token(self, session_id: str) -> str:
        return _b64encode(hmac.new(self._csrf_key, session_id.encode(), hashlib.sha256).digest())

    def csrf_valid(self, session_id: str, token: str | None) -> bool:
        if not token or len(token) > 128:
            return False
        return hmac.compare_digest(token, self.csrf_token(session_id))

    def _sign(self, payload: str) -> str:
        message = f"{TOKEN_VERSION}.{payload}".encode()
        return _b64encode(hmac.new(self._session_key, message, hashlib.sha256).digest())
