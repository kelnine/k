"""Accounts with their metrics: the leaderboard and the account pages.

Two kinds of account (docs/12 §12.3):

* ``FORWARD`` — an instance's dedicated account (``accounts.strategy_instance_id``),
  traded by the forward paper runtime;
* ``RUN`` — an account created for one simulation run (``lab demo``, backtests),
  linked to its instance through ``account_allocations`` and to its run through
  its opening ``DEPOSIT`` ledger entry.

Metrics are computed for a whole set of accounts with a fixed number of
queries (no per-account round trips), so a leaderboard of ~50 forward
accounts costs the same handful of queries as one account.
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from kterminal.api.metrics import ClosedTrade, Drawdown, EquityMark, account_metrics
from kterminal.api.queries.common import version_out
from kterminal.api.queries.system import KillSwitchState, instance_runtime
from kterminal.api.schemas import AccountMetrics, AccountOut, RuntimeView, VersionOut
from kterminal.db import models as m

AccountScope = Literal["forward", "run", "all"]

SortKey = Literal[
    "average_r",
    "return_pct",
    "net_pnl",
    "max_drawdown_pct",
    "win_rate",
    "trades",
    "profit_factor",
    "expectancy",
    "equity",
    "open_positions",
    "name",
    "instance",
]
"""Leaderboard sort keys. The default, ``average_r`` (expectancy in R) with ties broken
by profit factor, is appendix A's ranking."""


@dataclass(frozen=True, slots=True)
class AccountFilter:
    scope: AccountScope = "all"
    run_id: UUID | None = None
    instance_id: str | None = None
    definition_id: str | None = None
    instrument: str | None = None
    timeframe: str | None = None
    status: str | None = None
    query: str | None = None
    account_ids: Sequence[UUID] | None = None


async def list_accounts(
    session: AsyncSession,
    filters: AccountFilter,
    *,
    runtime: RuntimeView,
    kill: KillSwitchState,
) -> list[AccountOut]:
    accounts = await _base_accounts(session, filters)
    if not accounts:
        return []
    ids = [a.id for a in accounts]

    allocations = dict(
        (
            await session.execute(
                select(
                    m.AccountAllocationRow.account_id, func.min(m.AccountAllocationRow.instance_id)
                )
                .where(m.AccountAllocationRow.account_id.in_(ids))
                .group_by(m.AccountAllocationRow.account_id)
            )
        ).all()
    )
    instance_of = {a.id: a.strategy_instance_id or allocations.get(a.id) for a in accounts}
    instances = {
        row.id: row
        for row in (
            await session.execute(
                select(
                    m.StrategyInstanceRow.id,
                    m.StrategyInstanceRow.name,
                    m.StrategyInstanceRow.definition_id,
                    m.StrategyInstanceRow.current_version_id,
                    m.StrategyDefinitionRow.name.label("definition_name"),
                )
                .join(m.StrategyDefinitionRow)
                .where(m.StrategyInstanceRow.id.in_({i for i in instance_of.values() if i}))
            )
        ).all()
    }

    # The run of a run-scoped account: its opening ledger entry's run.
    first_entries = (
        await session.execute(
            select(m.AccountLedgerRow.account_id, m.AccountLedgerRow.run_id)
            .where(m.AccountLedgerRow.account_id.in_(ids))
            .distinct(m.AccountLedgerRow.account_id)
            .order_by(m.AccountLedgerRow.account_id, m.AccountLedgerRow.seq)
        )
    ).all()
    run_of = {row.account_id: row.run_id for row in first_entries if row.run_id is not None}
    runs = {
        row.id: row
        for row in (
            await session.execute(
                select(m.RunRow.id, m.RunRow.kind, m.RunRow.name).where(
                    m.RunRow.id.in_(set(run_of.values()))
                )
            )
        ).all()
    }

    # Version: what a forward account runs now; what a run account last traded under.
    run_account_ids = [a.id for a in accounts if a.strategy_instance_id is None]
    traded_version = dict(
        (
            await session.execute(
                select(m.TradeRow.account_id, m.TradeRow.strategy_version_id)
                .where(m.TradeRow.account_id.in_(run_account_ids))
                .distinct(m.TradeRow.account_id)
                .order_by(m.TradeRow.account_id, m.TradeRow.entry_time.desc())
            )
        ).all()
        if run_account_ids
        else []
    )
    version_id_of: dict[UUID, UUID] = {}
    for account in accounts:
        instance = instances.get(instance_of[account.id] or "")
        chosen = traded_version.get(account.id) or (
            instance.current_version_id if instance else None
        )
        if chosen is not None:
            version_id_of[account.id] = chosen
    versions = {
        row.id: version_out(row)
        for row in (
            await session.execute(
                select(m.StrategyVersionRow).where(
                    m.StrategyVersionRow.id.in_(set(version_id_of.values()))
                )
            )
        ).scalars()
    }

    metrics = await account_metrics_for(
        session, [(a.id, Decimal(a.starting_balance)) for a in accounts]
    )

    out = []
    for account in accounts:
        instance_id = instance_of[account.id]
        instance = instances.get(instance_id or "")
        run = runs.get(run_of.get(account.id)) if account.id in run_of else None
        out.append(
            AccountOut(
                id=account.id,
                name=account.name,
                kind="FORWARD" if account.strategy_instance_id else "RUN",
                mode=account.mode,
                broker=account.broker,
                status=account.status,
                currency=account.currency,
                instance_id=instance_id,
                instance_name=instance.name if instance else None,
                definition_id=instance.definition_id if instance else None,
                definition_name=instance.definition_name if instance else None,
                run_id=run.id if run else None,
                run_kind=run.kind if run else None,
                run_name=run.name if run else None,
                version=versions.get(version_id_of.get(account.id)),  # type: ignore[arg-type]
                metrics=metrics[account.id],
                halted=kill.halts(account.id, instance_id),
                runtime=instance_runtime(runtime, instance_id)
                if account.strategy_instance_id
                else None,
                created_at=account.created_at,
            )
        )
    return [a for a in out if _matches(a, filters)]


async def _base_accounts(session: AsyncSession, filters: AccountFilter) -> list[Any]:
    a = m.AccountRow
    conditions: list[ColumnElement[bool]] = []
    if filters.scope == "forward":
        conditions.append(a.strategy_instance_id.is_not(None))
    elif filters.scope == "run":
        conditions.append(a.strategy_instance_id.is_(None))
    if filters.status:
        conditions.append(a.status == filters.status)
    if filters.account_ids is not None:
        conditions.append(a.id.in_(list(filters.account_ids)))
    if filters.instance_id:
        allocated = select(m.AccountAllocationRow.account_id).where(
            m.AccountAllocationRow.instance_id == filters.instance_id
        )
        conditions.append(or_(a.strategy_instance_id == filters.instance_id, a.id.in_(allocated)))
    if filters.run_id is not None:
        opened_in_run = select(m.AccountLedgerRow.account_id).where(
            m.AccountLedgerRow.run_id == filters.run_id, m.AccountLedgerRow.kind == "DEPOSIT"
        )
        traded_in_run = select(m.TradeRow.account_id).where(m.TradeRow.run_id == filters.run_id)
        conditions.append(or_(a.id.in_(opened_in_run), a.id.in_(traded_in_run)))
    rows = await session.execute(
        select(
            a.id,
            a.name,
            a.mode,
            a.broker,
            a.status,
            a.currency,
            a.starting_balance,
            a.strategy_instance_id,
            a.created_at,
        )
        .where(and_(*conditions))
        .order_by(a.name)
    )
    return list(rows.all())


def _matches(account: AccountOut, filters: AccountFilter) -> bool:
    version: VersionOut | None = account.version
    if filters.definition_id and account.definition_id != filters.definition_id:
        return False
    if filters.instrument and (version is None or filters.instrument not in version.instruments):
        return False
    if filters.timeframe and (version is None or version.timeframe != filters.timeframe):
        return False
    if filters.query:
        needle = filters.query.strip().lower()
        haystack = " ".join(
            part or ""
            for part in (
                account.name,
                account.instance_id,
                account.instance_name,
                account.definition_id,
                account.definition_name,
                " ".join(version.instruments) if version else "",
                version.timeframe if version else "",
            )
        ).lower()
        if needle not in haystack:
            return False
    return True


async def account_metrics_for(
    session: AsyncSession, accounts: Sequence[tuple[UUID, Decimal]]
) -> dict[UUID, AccountMetrics]:
    """Appendix A metrics of every account in ``accounts`` ((id, starting balance) pairs)."""
    ids = [account_id for account_id, _ in accounts]
    ledger = m.AccountLedgerRow
    latest_ledger = {
        row.account_id: row
        for row in (
            await session.execute(
                select(ledger.account_id, ledger.balance_after, ledger.ts)
                .where(ledger.account_id.in_(ids))
                .distinct(ledger.account_id)
                .order_by(ledger.account_id, ledger.seq.desc())
            )
        ).all()
    }
    closed: dict[UUID, list[ClosedTrade]] = defaultdict(list)
    last_exit: dict[UUID, datetime] = {}
    for row in await session.execute(
        select(
            m.TradeRow.account_id, m.TradeRow.net_pnl, m.TradeRow.r_multiple, m.TradeRow.exit_time
        )
        .where(m.TradeRow.account_id.in_(ids), m.TradeRow.status == "CLOSED")
        .order_by(m.TradeRow.exit_time)
    ):
        closed[row.account_id].append(ClosedTrade(row.net_pnl, row.r_multiple))
        last_exit[row.account_id] = row.exit_time
    open_counts: dict[UUID, int] = {}
    last_entry: dict[UUID, datetime] = {}
    opened = await session.execute(
        select(m.TradeRow.account_id, func.count(), func.max(m.TradeRow.entry_time))
        .where(m.TradeRow.account_id.in_(ids), m.TradeRow.status == "OPEN")
        .group_by(m.TradeRow.account_id)
    )
    for account_id, count, newest in opened.tuples():
        open_counts[account_id] = int(count)
        last_entry[account_id] = newest
    snapshots = m.EquitySnapshotRow
    marks = {
        row.account_id: EquityMark(row.ts, Decimal(row.equity), Decimal(row.open_pnl))
        for row in (
            await session.execute(
                select(snapshots.account_id, snapshots.ts, snapshots.equity, snapshots.open_pnl)
                .where(snapshots.account_id.in_(ids))
                .distinct(snapshots.account_id)
                .order_by(snapshots.account_id, snapshots.ts.desc())
            )
        ).all()
    }
    drawdowns = await _drawdowns(session, ids)

    out = {}
    for account_id, starting_balance in accounts:
        entry = latest_ledger.get(account_id)
        times = [t for t in (last_exit.get(account_id), last_entry.get(account_id)) if t]
        out[account_id] = account_metrics(
            starting_balance=starting_balance,
            balance=Decimal(entry.balance_after) if entry else starting_balance,
            closed=closed.get(account_id, []),
            open_positions=open_counts.get(account_id, 0),
            last_ledger_at=entry.ts if entry else None,
            mark=marks.get(account_id),
            drawdown=drawdowns.get(account_id),
            last_trade_at=max(times) if times else None,
        )
    return out


async def _drawdowns(session: AsyncSession, ids: Sequence[UUID]) -> dict[UUID, Drawdown]:
    """Maximum drawdown of each account's equity curve, the starting balance being the
    first peak — :func:`kterminal.api.metrics.drawdown_stats` in SQL."""
    snapshots = m.EquitySnapshotRow
    peak = func.greatest(
        m.AccountRow.starting_balance,
        func.max(snapshots.equity).over(
            partition_by=snapshots.account_id, order_by=snapshots.ts, rows=(None, 0)
        ),
    ).label("peak")
    curve = (
        select(snapshots.account_id, snapshots.equity, peak)
        .join(m.AccountRow, m.AccountRow.id == snapshots.account_id)
        .where(snapshots.account_id.in_(ids))
        .subquery()
    )
    rows = await session.execute(
        select(
            curve.c.account_id,
            func.max(curve.c.peak - curve.c.equity),
            func.max((curve.c.peak - curve.c.equity) / func.nullif(curve.c.peak, 0) * 100),
        ).group_by(curve.c.account_id)
    )
    return {
        row[0]: Drawdown(
            Decimal(row[1]),
            Decimal(row[2] if row[2] is not None else 0).quantize(Decimal("0.01")),
        )
        for row in rows
    }


def sort_accounts(accounts: list[AccountOut], key: str, descending: bool) -> list[AccountOut]:
    """Sort a leaderboard; accounts without a value for ``key`` always come last."""

    def value(account: AccountOut) -> Any:
        if key == "name":
            return account.name.lower()
        if key == "instance":
            return (account.instance_id or "").lower()
        return getattr(account.metrics, key)

    def tie_break(account: AccountOut) -> Decimal:
        pf = account.metrics.profit_factor
        return pf if pf is not None else Decimal("-Infinity")

    present = [a for a in accounts if value(a) is not None]
    missing = [a for a in accounts if value(a) is None]
    present.sort(key=lambda a: (value(a), tie_break(a)), reverse=descending)
    missing.sort(key=lambda a: a.name.lower())
    return present + missing
