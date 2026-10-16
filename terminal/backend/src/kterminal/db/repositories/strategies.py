"""Persist strategy definitions, instances and their immutable versions.

The strategy lab (docs/12) distinguishes three things:

* a **definition** — code (a Python plug-in) or a declared external
  TradingView script, identified by its slug;
* an **instance** — a configured, independently measured lab subject (one
  definition + parameters + instruments + timeframes + its own account);
* a **version** — the immutable snapshot of everything that determines an
  instance's signals, identified per instance by its ``config_hash``.

:func:`get_or_create_version` is idempotent per ``(instance_id,
config_hash)``: running the same configuration again reuses the version, any
change creates a new one, and rows recorded under the old version keep
pointing at it — so later edits never corrupt historical comparisons.

The database itself guarantees that a version belongs to its instance's
definition and that ``current_version_id`` is one of the instance's own
versions (composite foreign keys). Repositories never commit.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from kterminal.core.enums import StrategyKind, StrategyStatus
from kterminal.core.errors import KTerminalError
from kterminal.core.ids import uuid7
from kterminal.db.audit import json_safe
from kterminal.db.models import (
    StrategyDefinitionRow,
    StrategyInstanceRow,
    StrategyPromotionRow,
    StrategyVersionRow,
    table_of,
)


class StrategyRepositoryError(KTerminalError, ValueError):
    """A strategy definition, instance or version cannot be stored as requested."""


# ── records ──────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class DefinitionRecord:
    id: str
    name: str
    kind: StrategyKind | str
    latest_version: str  # the definition's declared semantic version
    module: str | None = None
    description: str = ""
    meta: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class InstanceRecord:
    id: str
    definition_id: str
    name: str
    description: str = ""
    status: StrategyStatus | str = StrategyStatus.DRAFT  # applied on creation only
    enabled: bool = True
    tags: Sequence[str] = ()


@dataclass(frozen=True, slots=True)
class VersionRecord:
    instance_id: str
    definition_id: str
    definition_version: str
    code_hash: str | None
    params: Mapping[str, Any]
    params_hash: str
    config: Mapping[str, Any]
    config_hash: str
    framework_fingerprint: str | None = None
    kterminal_version: str | None = None


@dataclass(frozen=True, slots=True)
class StoredInstance:
    id: str
    definition_id: str
    name: str
    description: str
    status: StrategyStatus
    enabled: bool
    tags: tuple[str, ...]
    current_version_id: UUID | None
    current_config_hash: str | None
    created_at: datetime
    updated_at: datetime


# ── definitions & instances ──────────────────────────────────────────────────
async def upsert_definition(session: AsyncSession, record: DefinitionRecord) -> None:
    """Insert or update a definition (name, kind, latest version, module, description, meta)."""
    table = table_of(StrategyDefinitionRow)
    values = {
        "name": record.name,
        "kind": StrategyKind(record.kind).value,
        "latest_version": record.latest_version,
        "module": record.module,
        "description": record.description,
        "meta": json_safe(dict(record.meta)),
    }
    statement = pg_insert(table).values(id=record.id, **values)
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=["id"],
            set_={**{k: statement.excluded[k] for k in values}, "updated_at": func.now()},
            where=or_(*(table.c[k].is_distinct_from(statement.excluded[k]) for k in values)),
        )
    )


async def upsert_instance(session: AsyncSession, record: InstanceRecord) -> None:
    """Insert or update an instance.

    An instance id names one lab subject for ever: re-pointing it at another
    definition is refused (create a new instance id instead). ``status`` is only
    used when the instance is created; promotions change it afterwards
    (:func:`set_instance_status`), so re-applying the lab configuration never
    demotes a strategy.
    """
    table = table_of(StrategyInstanceRow)
    existing = (
        await session.execute(select(table.c.definition_id).where(table.c.id == record.id))
    ).scalar_one_or_none()
    if existing is not None and existing != record.definition_id:
        raise StrategyRepositoryError(
            f"instance {record.id!r} belongs to definition {existing!r}, not "
            f"{record.definition_id!r}; an instance id cannot change definition — "
            "create a new instance id for the new subject"
        )
    values = {
        "name": record.name,
        "description": record.description,
        "enabled": record.enabled,
        "tags": list(record.tags),
    }
    statement = pg_insert(table).values(
        id=record.id,
        definition_id=record.definition_id,
        status=StrategyStatus(record.status).value,
        **values,
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=["id"],
            set_={**{k: statement.excluded[k] for k in values}, "updated_at": func.now()},
            where=or_(*(table.c[k].is_distinct_from(statement.excluded[k]) for k in values)),
        )
    )


# ── versions ─────────────────────────────────────────────────────────────────
async def get_or_create_version(session: AsyncSession, record: VersionRecord) -> UUID:
    """The id of the version with ``record.config_hash`` for this instance (created if new).

    Also makes it the instance's ``current_version_id``.
    """
    if not record.config_hash or not record.params_hash:
        raise StrategyRepositoryError("a version needs a config_hash and a params_hash")
    versions = table_of(StrategyVersionRow)
    instances = table_of(StrategyInstanceRow)
    definition = (
        await session.execute(
            select(instances.c.definition_id).where(instances.c.id == record.instance_id)
        )
    ).scalar_one_or_none()
    if definition is None:
        raise StrategyRepositoryError(f"unknown strategy instance {record.instance_id!r}")
    if definition != record.definition_id:
        raise StrategyRepositoryError(
            f"version for instance {record.instance_id!r} names definition "
            f"{record.definition_id!r}, but the instance belongs to {definition!r}"
        )
    version_id: UUID | None = (
        await session.execute(
            pg_insert(versions)
            .values(
                id=uuid7(),
                instance_id=record.instance_id,
                definition_id=record.definition_id,
                definition_version=record.definition_version,
                code_hash=record.code_hash,
                params=json_safe(dict(record.params)),
                params_hash=record.params_hash,
                config=json_safe(dict(record.config)),
                config_hash=record.config_hash,
                framework_fingerprint=record.framework_fingerprint,
                kterminal_version=record.kterminal_version,
            )
            .on_conflict_do_nothing(index_elements=["instance_id", "config_hash"])
            .returning(versions.c.id)
        )
    ).scalar_one_or_none()
    if version_id is None:  # this exact configuration was recorded before
        version_id = (
            await session.execute(
                select(versions.c.id).where(
                    versions.c.instance_id == record.instance_id,
                    versions.c.config_hash == record.config_hash,
                )
            )
        ).scalar_one()
    await session.execute(
        update(instances)
        .where(
            instances.c.id == record.instance_id,
            instances.c.current_version_id.is_distinct_from(version_id),
        )
        .values(current_version_id=version_id)
    )
    return version_id


async def version_id_for(session: AsyncSession, instance_id: str, config_hash: str) -> UUID | None:
    """Map a ``strategy_version`` stamped on a signal (its config hash) to the version row."""
    versions = table_of(StrategyVersionRow)
    return (
        await session.execute(
            select(versions.c.id).where(
                versions.c.instance_id == instance_id, versions.c.config_hash == config_hash
            )
        )
    ).scalar_one_or_none()


# ── lifecycle ────────────────────────────────────────────────────────────────
async def set_instance_status(
    session: AsyncSession,
    instance_id: str,
    to_status: StrategyStatus,
    *,
    evidence: Mapping[str, Any],
    approved_by: UUID | None = None,
    note: str = "",
) -> UUID | None:
    """Change an instance's lifecycle status and record the promotion with its evidence.

    Returns the promotion id, or ``None`` when the instance already has that status.
    ``LIVE_APPROVED`` requires an approving user.
    """
    to_status = StrategyStatus(to_status)
    instances = table_of(StrategyInstanceRow)
    row = (
        await session.execute(
            select(instances.c.status, instances.c.current_version_id)
            .where(instances.c.id == instance_id)
            .with_for_update()
        )
    ).one_or_none()
    if row is None:
        raise StrategyRepositoryError(f"unknown strategy instance {instance_id!r}")
    if row.status == to_status.value:
        return None
    if to_status is StrategyStatus.LIVE_APPROVED and approved_by is None:
        raise StrategyRepositoryError("LIVE_APPROVED requires an approving user (approved_by)")
    promotion_id = uuid7()
    await session.execute(
        pg_insert(table_of(StrategyPromotionRow)).values(
            id=promotion_id,
            instance_id=instance_id,
            strategy_version_id=row.current_version_id,
            from_status=row.status,
            to_status=to_status.value,
            evidence=json_safe(dict(evidence)),
            approved_by=approved_by,
            note=note,
        )
    )
    await session.execute(
        update(instances).where(instances.c.id == instance_id).values(status=to_status.value)
    )
    return promotion_id


# ── queries ──────────────────────────────────────────────────────────────────
async def list_instances(
    session: AsyncSession,
    *,
    enabled_only: bool = False,
    definition_id: str | None = None,
) -> list[StoredInstance]:
    """Instances (ordered by id) with their current version's config hash."""
    instances = table_of(StrategyInstanceRow)
    versions = table_of(StrategyVersionRow)
    query = (
        select(instances, versions.c.config_hash.label("current_config_hash"))
        .outerjoin(versions, versions.c.id == instances.c.current_version_id)
        .order_by(instances.c.id)
    )
    if enabled_only:
        query = query.where(instances.c.enabled.is_(True))
    if definition_id is not None:
        query = query.where(instances.c.definition_id == definition_id)
    return [
        StoredInstance(
            id=row.id,
            definition_id=row.definition_id,
            name=row.name,
            description=row.description,
            status=StrategyStatus(row.status),
            enabled=row.enabled,
            tags=tuple(row.tags),
            current_version_id=row.current_version_id,
            current_config_hash=row.current_config_hash,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        for row in await session.execute(query)
    ]
