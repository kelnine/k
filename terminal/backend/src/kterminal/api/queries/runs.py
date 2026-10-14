"""Runs: lab simulations, backtests, forward sessions and signal replays."""

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from kterminal.api.schemas import RunOut
from kterminal.db import models as m


async def list_runs(
    session: AsyncSession,
    *,
    kind: str | None = None,
    status: str | None = None,
    run_id: UUID | None = None,
    limit: int,
    offset: int,
) -> tuple[list[RunOut], int]:
    conditions: list[ColumnElement[bool]] = []
    if kind:
        conditions.append(m.RunRow.kind == kind)
    if status:
        conditions.append(m.RunRow.status == status)
    if run_id is not None:
        conditions.append(m.RunRow.id == run_id)
    total = (
        await session.execute(select(func.count()).select_from(m.RunRow).where(*conditions))
    ).scalar_one()
    runs = list(
        (
            await session.execute(
                select(m.RunRow)
                .where(*conditions)
                .order_by(m.RunRow.created_at.desc(), m.RunRow.id.desc())
                .limit(limit)
                .offset(offset)
            )
        ).scalars()
    )
    ids = [run.id for run in runs]
    counts: dict[str, dict[UUID, int]] = {}
    for name, column in (
        ("signals", m.SignalRow.run_id),
        ("trades", m.TradeRow.run_id),
    ):
        result = await session.execute(
            select(column, func.count()).where(column.in_(ids)).group_by(column)
        )
        counts[name] = {run: int(n) for run, n in result.tuples() if run is not None}
    # Accounts: run accounts opened in the run, plus forward accounts that traded in it.
    opened = select(m.AccountLedgerRow.run_id, m.AccountLedgerRow.account_id).where(
        m.AccountLedgerRow.run_id.in_(ids), m.AccountLedgerRow.kind == "DEPOSIT"
    )
    traded = select(m.TradeRow.run_id, m.TradeRow.account_id).where(m.TradeRow.run_id.in_(ids))
    both = opened.union(traded).subquery()
    grouped = await session.execute(
        select(both.c.run_id, func.count(func.distinct(both.c.account_id))).group_by(both.c.run_id)
    )
    accounts: dict[UUID, int] = {run: int(n) for run, n in grouped.tuples()}
    return [
        RunOut(
            id=run.id,
            kind=run.kind,
            name=run.name,
            status=run.status,
            created_at=run.created_at,
            started_at=run.started_at,
            finished_at=run.finished_at,
            summary=run.summary,
            error=run.error,
            instances=_instances(run.config),
            accounts=int(accounts.get(run.id, 0)),
            signals=int(counts["signals"].get(run.id, 0)),
            trades=int(counts["trades"].get(run.id, 0)),
        )
        for run in runs
    ], int(total)


def _instances(config: Mapping[str, Any] | None) -> list[str]:
    """Instance ids named in a run's configuration (lab configs list ``instances``)."""
    if not config:
        return []
    found = []
    for item in config.get("instances") or []:
        if isinstance(item, Mapping) and isinstance(item.get("id"), str):
            if item.get("enabled", True):
                found.append(item["id"])
        elif isinstance(item, str):
            found.append(item)
    return found
