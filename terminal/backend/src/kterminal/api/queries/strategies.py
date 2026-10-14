"""Strategy instances with their versions, dedicated accounts and runtime state."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from kterminal.api.queries.common import version_out
from kterminal.api.queries.system import instance_runtime
from kterminal.api.schemas import InstanceDetailOut, InstanceOut, RuntimeView
from kterminal.db import models as m


async def list_instances(
    session: AsyncSession, runtime: RuntimeView, *, instance_id: str | None = None
) -> list[InstanceOut]:
    i, d = m.StrategyInstanceRow, m.StrategyDefinitionRow
    query = select(i, d.name, d.kind).join(d, d.id == i.definition_id).order_by(i.id)
    if instance_id is not None:
        query = query.where(i.id == instance_id)
    rows = (await session.execute(query)).all()
    if not rows:
        return []
    ids = [row[0].id for row in rows]
    current = {row[0].current_version_id for row in rows if row[0].current_version_id}
    versions = {
        v.id: version_out(v)
        for v in (
            await session.execute(
                select(m.StrategyVersionRow).where(m.StrategyVersionRow.id.in_(current))
            )
        ).scalars()
    }
    counts = dict(
        (
            await session.execute(
                select(m.StrategyVersionRow.instance_id, func.count())
                .where(m.StrategyVersionRow.instance_id.in_(ids))
                .group_by(m.StrategyVersionRow.instance_id)
            )
        ).all()
    )
    accounts = dict(
        (
            await session.execute(
                select(m.AccountRow.strategy_instance_id, m.AccountRow.id).where(
                    m.AccountRow.strategy_instance_id.in_(ids)
                )
            )
        ).all()
    )
    return [
        InstanceOut(
            id=instance.id,
            name=instance.name,
            description=instance.description,
            definition_id=instance.definition_id,
            definition_name=definition_name,
            kind=kind,
            status=instance.status,
            enabled=instance.enabled,
            tags=list(instance.tags or []),
            version=versions.get(instance.current_version_id)
            if instance.current_version_id
            else None,
            versions=int(counts.get(instance.id, 0)),
            account_id=accounts.get(instance.id),
            runtime=instance_runtime(runtime, instance.id),
        )
        for instance, definition_name, kind in rows
    ]


async def instance_detail(
    session: AsyncSession, instance_id: str, runtime: RuntimeView
) -> InstanceDetailOut | None:
    found = await list_instances(session, runtime, instance_id=instance_id)
    if not found:
        return None
    history = (
        await session.execute(
            select(m.StrategyVersionRow)
            .where(m.StrategyVersionRow.instance_id == instance_id)
            .order_by(m.StrategyVersionRow.created_at.desc())
        )
    ).scalars()
    return InstanceDetailOut(
        **found[0].model_dump(), version_history=[version_out(v) for v in history]
    )
