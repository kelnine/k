"""PostgreSQL advisory locks — used for leader election.

Exactly one ``engine`` process may route signals and place orders at a time;
otherwise two engines could both pass a "max one open position" check and
both submit the order. The active engine holds a *session-level* advisory
lock on a dedicated connection for as long as it runs. If the process dies or
its connection drops, PostgreSQL releases the lock and a standby engine
acquires it. Losing the connection therefore means losing leadership, and
the engine must stop trading at once (see :meth:`AdvisoryLock.verify`).
"""

import hashlib

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from kterminal.observability.logging import get_logger

_log = get_logger(__name__)

ENGINE_LEADER_LOCK = "kterminal.engine.leader"


def lock_key(name: str) -> int:
    """Stable signed 64-bit key for a lock name (PostgreSQL advisory locks take a bigint)."""
    return int.from_bytes(hashlib.sha256(name.encode()).digest()[:8], "big", signed=True)


class AdvisoryLock:
    def __init__(self, engine: AsyncEngine, name: str) -> None:
        self.name = name
        self.key = lock_key(name)
        self._engine = engine
        self._conn: AsyncConnection | None = None

    @property
    def held(self) -> bool:
        return self._conn is not None

    async def try_acquire(self) -> bool:
        """Try once, without blocking. Returns True if this process now holds the lock."""
        if self._conn is not None:
            return True
        conn = await self._engine.connect()
        try:
            # AUTOCOMMIT: holding the lock must not hold an open transaction for hours
            # ("idle in transaction" blocks vacuum and may be killed by timeouts).
            await conn.execution_options(isolation_level="AUTOCOMMIT")
            acquired = bool(
                (
                    await conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": self.key})
                ).scalar_one()
            )
        except BaseException:
            await conn.close()
            raise
        if not acquired:
            await conn.close()
            return False
        self._conn = conn
        _log.info("lock.acquired", lock=self.name)
        return True

    async def verify(self) -> bool:
        """Confirm the lock is still held by this session; False means leadership is lost."""
        if self._conn is None:
            return False
        try:
            still_held = bool(
                (
                    await self._conn.execute(
                        # A bigint advisory key is shown as classid (high 32 bits) and
                        # objid (low 32 bits) with objsubid = 1.
                        text(
                            "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype = 'advisory' "
                            "AND pid = pg_backend_pid() AND granted AND objsubid = 1 "
                            "AND ((classid::bigint << 32) | objid::bigint) = :k)"
                        ),
                        {"k": self.key},
                    )
                ).scalar_one()
            )
        except Exception as exc:
            _log.error("lock.verify_failed", lock=self.name, error=type(exc).__name__)
            await self._discard()
            return False
        if not still_held:
            _log.error("lock.lost", lock=self.name)
            await self._discard()
        return still_held

    async def release(self) -> None:
        if self._conn is None:
            return
        try:
            await self._conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": self.key})
            await self._conn.close()
            _log.info("lock.released", lock=self.name)
        except Exception as exc:
            _log.warning("lock.release_failed", lock=self.name, error=type(exc).__name__)
            await self._discard()
        finally:
            self._conn = None

    async def _discard(self) -> None:
        """Drop the connection without returning it to the pool (it may still hold the lock)."""
        conn, self._conn = self._conn, None
        if conn is not None:
            try:
                await conn.invalidate()
                await conn.close()
            except Exception:  # noqa: S110 - best effort: the connection is already broken
                pass
