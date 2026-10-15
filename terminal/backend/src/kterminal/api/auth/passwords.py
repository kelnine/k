"""argon2id password hashing (docs/09 §9.2).

The hash string carries its own parameters, so stronger parameters can be
adopted later: :meth:`Passwords.needs_rehash` reports old hashes and the login
endpoint re-hashes them with the password it has just verified.
"""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.low_level import Type

# A well-formed hash that no password matches is not needed: verifying against a
# throw-away hash of a random string costs the same as a real verification.
_DECOY_PASSWORD = "kterminal-decoy-password-for-unknown-users"  # noqa: S105 - not a credential


class Passwords:
    """Hash and verify passwords with argon2id (argon2-cffi's RFC 9106 defaults)."""

    def __init__(self, hasher: PasswordHasher | None = None) -> None:
        self._hasher = hasher or PasswordHasher(type=Type.ID)
        if self._hasher.type is not Type.ID:
            raise ValueError("passwords must be hashed with argon2id")
        self._decoy = self._hasher.hash(_DECOY_PASSWORD)

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, password_hash: str, password: str) -> bool:
        try:
            return self._hasher.verify(password_hash, password)
        except (VerificationError, InvalidHashError):
            return False

    def verify_decoy(self, password: str) -> None:
        """Spend the time of a verification for a username that does not exist, so the
        response time does not reveal which usernames are real."""
        self.verify(self._decoy, password)

    def needs_rehash(self, password_hash: str) -> bool:
        try:
            return self._hasher.check_needs_rehash(password_hash)
        except InvalidHashError:
            return True


def password_problems(password: str, *, min_length: int, username: str = "") -> list[str]:
    """Why ``password`` is unacceptable (empty list: acceptable)."""
    problems = []
    if len(password) < min_length:
        problems.append(f"must be at least {min_length} characters long")
    if len(password) > 1024:
        problems.append("must be at most 1024 characters long")
    if password.strip() != password:
        problems.append("must not start or end with whitespace")
    if username and username.lower() in password.lower():
        problems.append("must not contain the username")
    if len(set(password)) < 5:
        problems.append("must use at least 5 different characters")
    return problems
