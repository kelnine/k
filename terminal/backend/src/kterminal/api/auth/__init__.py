"""Dashboard authentication: argon2id passwords, signed ``HttpOnly; SameSite=Strict``
session cookies, CSRF tokens, sign-in rate limiting/lockout and role checks
(docs/09 §9.2). TOTP second factors are not implemented yet.
"""

from kterminal.api.auth.service import CSRF_HEADER, SESSION_COOKIE, AuthService, Principal
from kterminal.api.auth.settings import AuthSettings, load_auth_settings
from kterminal.api.auth.users import Role, User

__all__ = [
    "CSRF_HEADER",
    "SESSION_COOKIE",
    "AuthService",
    "AuthSettings",
    "Principal",
    "Role",
    "User",
    "load_auth_settings",
]
