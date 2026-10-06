"""Module 10 — Database (PostgreSQL).

Phase 1: connection pool management and advisory-lock leader election.
Phase 2 adds SQLAlchemy models and Alembic migrations for the schema in
``terminal/docs/04-database-schema.md``, repositories, the transactional
outbox and the append-only, hash-chained audit log.
"""

from kterminal.db.locks import ENGINE_LEADER_LOCK, AdvisoryLock, lock_key
from kterminal.db.session import Database

__all__ = ["ENGINE_LEADER_LOCK", "AdvisoryLock", "Database", "lock_key"]
