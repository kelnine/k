"""PostgreSQL persistence of forward paper sessions.

A forward session is a ``runs`` row of kind ``FORWARD``: ``config`` holds the
session plan (lab configuration, catalog fingerprint, instance versions, the
dedicated accounts and their opening balances), ``data_fingerprint`` its
progress (input segments, minutes processed, input hash), and the session's
records carry its ``run_id`` like any lab run. Each processed minute is
committed in **one transaction**: the bars (into ``candles``, the session's
input log), every record the lab produced, the progress, and an audit entry
for each kill-switch state that took effect — so a crash leaves the database
at a minute boundary, from which replay rebuilds the state exactly.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from kterminal.core.enums import Direction
from kterminal.db import audit
from kterminal.db import models as m
from kterminal.db.repositories import candles as candle_repo
from kterminal.db.repositories import catalog as catalog_repo
from kterminal.db.repositories.kill_switches import KillSwitchRecord, list_kill_switches
from kterminal.domain.market import Bar
from kterminal.paper.pg_store import PostgresLabStore
from kterminal.paper.records import Record, TradeRecord

FORWARD = "FORWARD"
STATUS_KEY = "paper.runtime"
KILL_SWITCH_APPLIED = "killswitch.applied"


@dataclass(frozen=True, slots=True)
class StoredSession:
    run_id: UUID
    name: str
    status: str
    config: dict[str, Any]
    progress: dict[str, Any]
    catalog_snapshot_id: UUID | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    summary: dict[str, Any] | None
    error: str | None


@dataclass(frozen=True, slots=True)
class OpenTrade:
    """An OPEN trade of a session with the costs it has accrued so far."""

    trade: TradeRecord  # strategy_version is the version's config hash
    entry_commission: Decimal
    swap: Decimal
    funding: Decimal
    spread_cost: Decimal


@dataclass(frozen=True, slots=True)
class AccountCheck:
    """What the database says about one account (compared with a replayed account)."""

    balance: Decimal | None  # balance_after of the newest ledger entry
    open_trades: list[tuple[UUID, str, str, Decimal, Decimal, datetime]]
    last_equity: tuple[datetime, Decimal, Decimal] | None  # newest snapshot of the run


class PostgresForwardStore(PostgresLabStore):
    """:class:`PostgresLabStore` plus what forward sessions need."""

    # ── sessions ────────────────────────────────────────────────────────────
    async def create_session(
        self,
        *,
        name: str,
        config: dict[str, Any],
        progress: dict[str, Any],
        catalog_document: dict[str, Any],
        catalog_fingerprint: str,
        started_at: datetime,
    ) -> UUID:
        async with self.db.session() as session:
            snapshot = await catalog_repo.apply_catalog(
                session, catalog_document, catalog_fingerprint, applied_by=f"paper:{name}"
            )
            row = m.RunRow(
                kind=FORWARD,
                name=name,
                config=config,
                data_fingerprint=progress,
                catalog_snapshot_id=snapshot.id,
                status="RUNNING",
                started_at=started_at,
            )
            session.add(row)
            await session.flush()
            self._catalog_snapshot[row.id] = snapshot.id
            return row.id

    def attach(self, stored: StoredSession) -> None:
        """Write later records of ``stored`` with its catalog snapshot (as start_run does)."""
        self._catalog_snapshot[stored.run_id] = stored.catalog_snapshot_id

    async def open_sessions(self) -> list[StoredSession]:
        """Forward sessions still RUNNING (normally at most one)."""
        return await self._sessions(m.RunRow.status == "RUNNING")

    async def sessions(self, limit: int = 20) -> list[StoredSession]:
        return await self._sessions(None, limit=limit)

    async def session(self, run_id: UUID) -> StoredSession:
        found = await self._sessions(m.RunRow.id == run_id)
        if not found:
            raise KeyError(f"no forward session {run_id}")
        return found[0]

    async def _sessions(self, condition: Any, *, limit: int | None = None) -> list[StoredSession]:
        stmt = select(m.RunRow).where(m.RunRow.kind == FORWARD)
        if condition is not None:
            stmt = stmt.where(condition)
        stmt = stmt.order_by(m.RunRow.created_at.desc(), m.RunRow.id.desc())
        if limit is not None:
            stmt = stmt.limit(limit)
        async with self.db.session() as session:
            rows = (await session.scalars(stmt)).all()
        return [
            StoredSession(
                run_id=row.id,
                name=row.name,
                status=row.status,
                config=dict(row.config),
                progress=dict(row.data_fingerprint or {}),
                catalog_snapshot_id=row.catalog_snapshot_id,
                created_at=row.created_at,
                started_at=row.started_at,
                finished_at=row.finished_at,
                summary=row.summary,
                error=row.error,
            )
            for row in rows
        ]

    async def finish_session(
        self,
        run_id: UUID,
        *,
        status: str,
        summary: dict[str, Any],
        finished_at: datetime,
        error: str | None = None,
    ) -> None:
        async with self.db.session() as session:
            await session.execute(
                update(m.RunRow)
                .where(m.RunRow.id == run_id)
                .values(status=status, summary=summary, finished_at=finished_at, error=error)
            )

    async def catalog_document(self, snapshot_id: UUID) -> dict[str, Any]:
        async with self.db.session() as session:
            row = await session.get(m.CatalogSnapshotRow, snapshot_id)
            if row is None:
                raise KeyError(f"unknown catalog snapshot {snapshot_id}")
            return dict(row.document)

    # ── one processed minute, atomically ────────────────────────────────────
    async def commit_minute(
        self,
        run_id: UUID,
        *,
        records: Sequence[Record],
        bars: Sequence[Bar],
        progress: dict[str, Any],
        kill_switch_changes: Sequence[tuple[datetime, dict[str, Any]]] = (),
        now: datetime,
    ) -> None:
        async with self.db.session() as session:
            if bars:
                # The bars as processed: this session's input log is authoritative for them.
                await candle_repo.insert_candles(session, bars, replace=True)
            await self.write_records(session, records, run_id=run_id)
            await self._save_progress(session, run_id, progress)
            for effective_from, state in kill_switch_changes:
                await audit.append(
                    session,
                    actor="system:paper",
                    action=KILL_SWITCH_APPLIED,
                    entity_type="run",
                    entity_id=run_id,
                    data={"effective_from": effective_from.isoformat(), "state": state},
                    ts=now,
                )

    async def save_progress(
        self, run_id: UUID, progress: dict[str, Any], records: Sequence[Record] = ()
    ) -> None:
        async with self.db.session() as session:
            await self.write_records(session, records, run_id=run_id)
            await self._save_progress(session, run_id, progress)

    @staticmethod
    async def _save_progress(session: AsyncSession, run_id: UUID, progress: dict[str, Any]) -> None:
        await session.execute(
            update(m.RunRow).where(m.RunRow.id == run_id).values(data_fingerprint=progress)
        )

    # ── candles ─────────────────────────────────────────────────────────────
    async def insert_candles(self, bars: Sequence[Bar], *, replace: bool = False) -> int:
        async with self.db.session() as session:
            return await candle_repo.insert_candles(session, bars, replace=replace)

    async def load_candles(
        self, instrument: str, *, source: str, start: datetime, end: datetime
    ) -> list[Bar]:
        async with self.db.session() as session:
            return await candle_repo.load_candles(
                session, instrument, source=source, start=start, end=end
            )

    # ── kill switches & faults (replay inputs) ──────────────────────────────
    async def kill_switch_records(self) -> list[KillSwitchRecord]:
        async with self.db.session() as session:
            return await list_kill_switches(session)

    async def kill_switch_history(self, run_id: UUID) -> list[tuple[datetime, dict[str, Any]]]:
        """Kill-switch states that took effect in this session, with their batch times."""
        async with self.db.session() as session:
            rows = (
                await session.execute(
                    select(m.AuditLogRow.data)
                    .where(
                        m.AuditLogRow.entity_type == "run",
                        m.AuditLogRow.entity_id == str(run_id),
                        m.AuditLogRow.action == KILL_SWITCH_APPLIED,
                    )
                    .order_by(m.AuditLogRow.seq)
                )
            ).all()
        return [
            (datetime.fromisoformat(data["effective_from"]), dict(data["state"]))
            for (data,) in rows
        ]

    async def host_faults(self, run_id: UUID) -> list[tuple[str, datetime, str]]:
        """Strategy-host failures of this session (instance, batch time, message): the
        faults replay cannot cause by itself (time-outs, crashed processes)."""
        async with self.db.session() as session:
            rows = (
                await session.execute(
                    select(
                        m.SystemErrorRow.strategy_instance_id,
                        m.SystemErrorRow.ts,
                        m.SystemErrorRow.message,
                    )
                    .where(
                        m.SystemErrorRow.run_id == run_id,
                        m.SystemErrorRow.component == "strategy.host",
                        m.SystemErrorRow.context["stage"].astext == "host",
                    )
                    .order_by(m.SystemErrorRow.ts)
                )
            ).all()
        return [(str(r[0]), r[1], str(r[2])) for r in rows if r[0] is not None]

    # ── state checks ────────────────────────────────────────────────────────
    async def account_check(self, account_id: UUID, run_id: UUID) -> AccountCheck:
        async with self.db.session() as session:
            balance = (
                await session.execute(
                    select(m.AccountLedgerRow.balance_after)
                    .where(m.AccountLedgerRow.account_id == account_id)
                    .order_by(m.AccountLedgerRow.seq.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            trades = (
                await session.execute(
                    select(
                        m.TradeRow.id,
                        m.TradeRow.instrument,
                        m.TradeRow.direction,
                        m.TradeRow.qty,
                        m.TradeRow.entry_price,
                        m.TradeRow.entry_time,
                    )
                    .where(m.TradeRow.account_id == account_id, m.TradeRow.status == "OPEN")
                    .order_by(m.TradeRow.id)
                )
            ).all()
            equity = (
                await session.execute(
                    select(
                        m.EquitySnapshotRow.ts,
                        m.EquitySnapshotRow.balance,
                        m.EquitySnapshotRow.equity,
                    )
                    .where(
                        m.EquitySnapshotRow.account_id == account_id,
                        m.EquitySnapshotRow.run_id == run_id,
                    )
                    .order_by(m.EquitySnapshotRow.ts.desc())
                    .limit(1)
                )
            ).first()
        return AccountCheck(
            balance=None if balance is None else Decimal(balance),
            open_trades=[(r[0], r[1], r[2], Decimal(r[3]), Decimal(r[4]), r[5]) for r in trades],
            last_equity=None
            if equity is None
            else (equity[0], Decimal(equity[1]), Decimal(equity[2])),
        )

    async def run_counts(self, run_id: UUID) -> dict[str, int]:
        """Rows each table holds for the run (the replay must produce as many)."""
        counts: dict[str, int] = {}
        async with self.db.session() as session:
            for name, model in (
                ("signals", m.SignalRow),
                ("risk_decisions", m.RiskDecisionRow),
                ("orders", m.OrderRow),
                ("fills", m.FillRow),
                ("trades", m.TradeRow),
                ("account_ledger", m.AccountLedgerRow),
            ):
                counts[name] = int(
                    (
                        await session.execute(
                            select(func.count()).select_from(model).where(model.run_id == run_id)
                        )
                    ).scalar_one()
                )
            counts["trade_events"] = int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(m.TradeEventRow)
                        .join(m.TradeRow, m.TradeRow.id == m.TradeEventRow.trade_id)
                        .where(m.TradeRow.run_id == run_id)
                    )
                ).scalar_one()
            )
        return counts

    async def ledger_entries(self, run_id: UUID) -> list[tuple[UUID, UUID, str, Decimal, Decimal]]:
        """The run's ledger entries in booking order: (id, account, kind, amount, balance)."""
        async with self.db.session() as session:
            rows = (
                await session.execute(
                    select(
                        m.AccountLedgerRow.id,
                        m.AccountLedgerRow.account_id,
                        m.AccountLedgerRow.kind,
                        m.AccountLedgerRow.amount,
                        m.AccountLedgerRow.balance_after,
                    )
                    .where(m.AccountLedgerRow.run_id == run_id)
                    .order_by(m.AccountLedgerRow.seq)
                )
            ).all()
        return [(r[0], r[1], r[2], Decimal(r[3]), Decimal(r[4])) for r in rows]

    async def trade_states(
        self, run_id: UUID
    ) -> list[tuple[UUID, str, Decimal | None, datetime | None]]:
        """The run's trades by id: (id, status, net P&L, exit time)."""
        async with self.db.session() as session:
            rows = (
                await session.execute(
                    select(
                        m.TradeRow.id, m.TradeRow.status, m.TradeRow.net_pnl, m.TradeRow.exit_time
                    )
                    .where(m.TradeRow.run_id == run_id)
                    .order_by(m.TradeRow.id)
                )
            ).all()
        return [(r[0], r[1], None if r[2] is None else Decimal(r[2]), r[3]) for r in rows]

    async def open_trade_count(self, account_id: UUID) -> int:
        async with self.db.session() as session:
            return int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(m.TradeRow)
                        .where(m.TradeRow.account_id == account_id, m.TradeRow.status == "OPEN")
                    )
                ).scalar_one()
            )

    async def high_water_mark(self, account_id: UUID) -> Decimal | None:
        """The newest equity snapshot's high-water mark of an account (any run)."""
        async with self.db.session() as session:
            value = (
                await session.execute(
                    select(m.EquitySnapshotRow.high_water_mark)
                    .where(m.EquitySnapshotRow.account_id == account_id)
                    .order_by(m.EquitySnapshotRow.ts.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        return None if value is None else Decimal(value)

    async def open_trades(self, run_id: UUID) -> list[OpenTrade]:
        """OPEN trades of a session with their stop/target as last moved and the costs
        booked so far (to close them when the session ends without a replay)."""
        result: list[OpenTrade] = []
        async with self.db.session() as session:
            rows = (
                await session.execute(
                    select(m.TradeRow, m.StrategyVersionRow.config_hash)
                    .join(
                        m.StrategyVersionRow,
                        m.StrategyVersionRow.id == m.TradeRow.strategy_version_id,
                    )
                    .where(m.TradeRow.run_id == run_id, m.TradeRow.status == "OPEN")
                    .order_by(m.TradeRow.id)
                )
            ).all()
            for row, config_hash in rows:
                self._versions[(row.strategy_instance_id, config_hash)] = row.strategy_version_id
                costs = (
                    await session.execute(
                        select(m.AccountLedgerRow.kind, func.sum(m.AccountLedgerRow.amount))
                        .where(m.AccountLedgerRow.trade_id == row.id)
                        .group_by(m.AccountLedgerRow.kind)
                    )
                ).all()
                by_kind = {kind: Decimal(total) for kind, total in costs}
                spread = (
                    await session.execute(
                        select(func.coalesce(func.sum(m.FillRow.spread_cost), 0))
                        .join(m.OrderRow, m.OrderRow.id == m.FillRow.order_id)
                        .where(m.OrderRow.trade_id == row.id)
                    )
                ).scalar_one()
                stop, target = row.current_stop or row.initial_stop, row.current_target
                for kind, new_value in (
                    await session.execute(
                        select(m.TradeEventRow.kind, m.TradeEventRow.new_value)
                        .where(m.TradeEventRow.trade_id == row.id)
                        .order_by(m.TradeEventRow.id)
                    )
                ).all():
                    if kind in ("STOP_MOVED", "BREAKEVEN") and new_value is not None:
                        stop = new_value
                    elif kind == "TARGET_MOVED":
                        target = new_value
                result.append(
                    OpenTrade(
                        trade=_open_trade_record(row, config_hash, stop, target),
                        entry_commission=-by_kind.get("COMMISSION", Decimal(0)),
                        swap=by_kind.get("SWAP", Decimal(0)),
                        funding=by_kind.get("FUNDING", Decimal(0)),
                        spread_cost=Decimal(spread),
                    )
                )
        return result

    # ── runtime status for the dashboard ────────────────────────────────────
    async def write_status(self, document: dict[str, Any], *, now: datetime) -> None:
        async with self.db.session() as session:
            stmt = insert(m.SystemStateRow).values(key=STATUS_KEY, value=document, updated_at=now)
            await session.execute(
                stmt.on_conflict_do_update(
                    index_elements=[m.SystemStateRow.key],
                    set_={"value": stmt.excluded.value, "updated_at": stmt.excluded.updated_at},
                )
            )

    async def read_status(self) -> dict[str, Any] | None:
        async with self.db.session() as session:
            row = await session.get(m.SystemStateRow, STATUS_KEY)
            return None if row is None else dict(row.value)


def _open_trade_record(
    row: m.TradeRow, config_hash: str, stop: Decimal, target: Decimal | None
) -> TradeRecord:
    return TradeRecord(
        id=row.id,
        account_id=row.account_id,
        account_config_version_id=row.account_config_version_id,
        instance_id=row.strategy_instance_id,
        strategy_version=config_hash,
        entry_signal_id=row.entry_signal_id,
        mode=row.mode,
        instrument=row.instrument,
        venue=row.venue,
        venue_symbol=row.venue_symbol,
        timeframe=row.timeframe,
        direction=Direction(row.direction),
        qty=row.qty,
        entry_requested=row.entry_requested,
        entry_price=row.entry_price,
        entry_time=row.entry_time,
        initial_stop=row.initial_stop,
        initial_target=row.initial_target,
        current_stop=stop,
        current_target=target,
        initial_risk=row.initial_risk,
        status="OPEN",
        correlation_id=row.correlation_id,
        session=row.session,
        entry_slippage=row.entry_slippage,
    )


__all__ = [
    "FORWARD",
    "KILL_SWITCH_APPLIED",
    "STATUS_KEY",
    "AccountCheck",
    "OpenTrade",
    "PostgresForwardStore",
    "StoredSession",
]
