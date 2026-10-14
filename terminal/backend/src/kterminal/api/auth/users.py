"""Dashboard users (table ``users``) and signed-out sessions.

Roles (docs/09 §9.2): ``VIEWER`` reads, ``OPERATOR`` also operates kill
switches, ``ADMIN`` also manages users (from the CLI for now). Every change to
a user is written to the audit log in the same transaction.

Signed-out session ids are kept until their cookie would have expired anyway,
in ``system_state`` under :data:`REVOKED_SESSIONS_KEY` (``{session id: expiry}``),
so a sign-out holds for every API process and survives restarts.

Functions take an ``AsyncSession`` and never commit; the caller owns the
transaction.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

from sqlalchemy import Boolean, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from kterminal.core.errors import KTerminalError
from kterminal.db import audit
from kterminal.db.models import USER_ROLES, SystemStateRow, UserRow

REVOKED_SESSIONS_KEY: Final = "auth.revoked_sessions"
USERNAME_PATTERN: Final = re.compile(r"^[a-z][a-z0-9_.-]{2,31}$")


class Role(StrEnum):
    VIEWER = "VIEWER"
    OPERATOR = "OPERATOR"
    ADMIN = "ADMIN"

    @property
    def rank(self) -> int:
        return USER_ROLES.index(self.value)

    def allows(self, required: "Role") -> bool:
        return self.rank >= required.rank


class UserError(KTerminalError, ValueError):
    """A user cannot be created or changed as requested."""


@dataclass(frozen=True, slots=True)
class User:
    id: UUID
    username: str
    role: Role
    disabled: bool
    password_hash: str
    created_at: datetime


def normalize_username(username: str) -> str:
    return username.strip().lower()


def _user(row: UserRow) -> User:
    return User(
        id=row.id,
        username=row.username,
        role=Role(row.role),
        disabled=row.disabled,
        password_hash=row.password_hash,
        created_at=row.created_at,
    )


async def get_user(session: AsyncSession, user_id: UUID) -> User | None:
    row = await session.get(UserRow, user_id)
    return None if row is None else _user(row)


async def get_user_by_username(session: AsyncSession, username: str) -> User | None:
    row = (
        await session.execute(
            select(UserRow).where(UserRow.username == normalize_username(username))
        )
    ).scalar_one_or_none()
    return None if row is None else _user(row)


async def list_users(session: AsyncSession) -> list[User]:
    rows = (await session.execute(select(UserRow).order_by(UserRow.username))).scalars()
    return [_user(row) for row in rows]


async def usernames_by_id(session: AsyncSession, ids: set[UUID]) -> dict[UUID, str]:
    if not ids:
        return {}
    rows = await session.execute(select(UserRow.id, UserRow.username).where(UserRow.id.in_(ids)))
    return {row.id: row.username for row in rows}


async def create_user(
    session: AsyncSession,
    *,
    username: str,
    password_hash: str,
    role: Role,
    actor: str,
    now: datetime,
) -> User:
    name = normalize_username(username)
    if not USERNAME_PATTERN.fullmatch(name):
        raise UserError(
            "usernames are 3-32 characters: a letter, then letters, digits, '.', '_' or '-'"
        )
    if await get_user_by_username(session, name) is not None:
        raise UserError(f"user {name!r} already exists")
    row = UserRow(username=name, password_hash=password_hash, role=role.value)
    session.add(row)
    await session.flush()
    await session.refresh(row)
    await audit.append(
        session,
        actor=actor,
        action="user.create",
        entity_type="user",
        entity_id=row.id,
        data={"username": name, "role": role.value},
        ts=now,
    )
    return _user(row)


async def set_disabled(
    session: AsyncSession, username: str, *, disabled: bool, actor: str, now: datetime
) -> User:
    user = await get_user_by_username(session, username)
    if user is None:
        raise UserError(f"no user {normalize_username(username)!r}")
    if user.disabled != disabled:
        await session.execute(
            update(UserRow).where(UserRow.id == user.id).values(disabled=disabled)
        )
        await audit.append(
            session,
            actor=actor,
            action="user.disable" if disabled else "user.enable",
            entity_type="user",
            entity_id=user.id,
            data={"username": user.username},
            ts=now,
        )
    refreshed = await get_user(session, user.id)
    if refreshed is None:  # pragma: no cover - read back in the same transaction
        raise UserError(f"user {user.username!r} vanished")
    return refreshed


async def set_password_hash(session: AsyncSession, user_id: UUID, password_hash: str) -> None:
    await session.execute(
        update(UserRow).where(UserRow.id == user_id).values(password_hash=password_hash)
    )


# ── signed-out sessions ──────────────────────────────────────────────────────
async def revoke_session(
    session: AsyncSession, session_id: str, *, expires_at: datetime, now: datetime
) -> None:
    """Refuse ``session_id`` from now until its cookie would have expired anyway."""
    entry = {session_id: expires_at.isoformat()}
    stmt = pg_insert(SystemStateRow).values(key=REVOKED_SESSIONS_KEY, value=entry, updated_at=now)
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=[SystemStateRow.key],
            set_={
                # jsonb || jsonb merges atomically: concurrent sign-outs never lose an entry
                "value": SystemStateRow.value.op("||")(stmt.excluded.value),
                "updated_at": stmt.excluded.updated_at,
            },
        )
    )
    # Forget entries whose cookies have expired by now.
    await session.execute(
        text(
            "UPDATE system_state SET value = ("
            " SELECT coalesce(jsonb_object_agg(k, v), '{}'::jsonb)"
            " FROM jsonb_each(value) AS e(k, v) WHERE (v #>> '{}')::timestamptz > :now"
            ") WHERE key = :key"
        ),
        {"now": now, "key": REVOKED_SESSIONS_KEY},
    )


async def session_revoked(session: AsyncSession, session_id: str) -> bool:
    revoked = (
        await session.execute(
            select(
                func.coalesce(SystemStateRow.value.op("?", return_type=Boolean)(session_id), False)
            ).where(SystemStateRow.key == REVOKED_SESSIONS_KEY)
        )
    ).scalar_one_or_none()
    return bool(revoked)


async def change_password(
    session: AsyncSession, username: str, *, password_hash: str, actor: str, now: datetime
) -> User:
    """Replace the password hash; sessions opened with the old password stop working."""
    user = await get_user_by_username(session, username)
    if user is None:
        raise UserError(f"no user {normalize_username(username)!r}")
    await set_password_hash(session, user.id, password_hash)
    await audit.append(
        session,
        actor=actor,
        action="user.password",
        entity_type="user",
        entity_id=user.id,
        data={"username": user.username},
        ts=now,
    )
    return user
