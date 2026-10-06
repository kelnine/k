"""Module 10 — Database (PostgreSQL).

Phase 1: connection pool management and advisory-lock leader election.
Phase 2: the production schema as SQLAlchemy models (``models``) with its
Alembic migration (``migrations``, driven by ``migrate``), monthly partitions
for the high-volume tables (``partitions``), the append-only, hash-chained
audit log (``audit``) and repositories (``repositories``). The schema is
documented in ``terminal/docs/04-database-schema.md``.
"""

from kterminal.db.locks import ENGINE_LEADER_LOCK, AdvisoryLock, lock_key
from kterminal.db.models import NAMING_CONVENTION, PARTITION_KEYS, TABLES, Base
from kterminal.db.partitions import PARTITIONED_TABLES, ensure_monthly_partitions
from kterminal.db.session import Database

__all__ = [
    "ENGINE_LEADER_LOCK",
    "NAMING_CONVENTION",
    "PARTITIONED_TABLES",
    "PARTITION_KEYS",
    "TABLES",
    "AdvisoryLock",
    "Base",
    "Database",
    "ensure_monthly_partitions",
    "lock_key",
]
