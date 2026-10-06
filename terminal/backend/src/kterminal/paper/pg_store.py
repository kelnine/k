"""PostgreSQL implementation of :class:`~kterminal.paper.store.LabStore`.

Records are written once per bar batch in **dependency order** (signals →
decisions → trades → orders → fills → trade events → ledger → equity →
errors) so every foreign key resolves inside the same transaction. Orders and
trades are emitted more than once (ACCEPTED → FILLED, OPEN → CLOSED) and are
upserted by id. Strategy definitions/instances/versions, accounts and the
catalog snapshot are written through the repositories in ``kterminal.db``.
"""

from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from kterminal import __version__
from kterminal.core.canonical import hash_data
from kterminal.core.ids import uuid7
from kterminal.db import models as m
from kterminal.db.repositories import accounts as account_repo
from kterminal.db.repositories import catalog as catalog_repo
from kterminal.db.repositories import strategies as strategy_repo
from kterminal.db.session import Database
from kterminal.domain.accounts import AccountSettings
from kterminal.paper.records import (
    DecisionRecord,
    EquityRecord,
    FaultRecord,
    FillRecord,
    LedgerRecord,
    OrderRecord,
    Record,
    SignalRecord,
    TradeEventRecord,
    TradeRecord,
)
from kterminal.paper.store import ProvisionedAccount
from kterminal.strategy_engine.instances import ResolvedInstance
from kterminal.strategy_engine.versioning import framework_fingerprint

_ORDER = (
    SignalRecord,
    DecisionRecord,
    TradeRecord,
    OrderRecord,
    FillRecord,
    TradeEventRecord,
    LedgerRecord,
    EquityRecord,
    FaultRecord,
)


class PostgresLabStore:
    def __init__(self, database: Database) -> None:
        self.db = database
        self._versions: dict[tuple[str, str], UUID] = {}
        self._modes: dict[UUID, str] = {}
        self._catalog_snapshot: dict[UUID, UUID | None] = {}

    # ── catalog & runs ──────────────────────────────────────────────────────
    async def apply_catalog(
        self, *, document: dict[str, Any], fingerprint: str, applied_by: str
    ) -> None:
        async with self.db.session() as session:
            await catalog_repo.apply_catalog(session, document, fingerprint, applied_by=applied_by)

    async def start_run(
        self,
        *,
        kind: str,
        name: str,
        config: dict[str, Any],
        catalog_document: dict[str, Any],
        catalog_fingerprint: str,
        started_at: datetime,
    ) -> UUID:
        async with self.db.session() as session:
            snapshot = await catalog_repo.apply_catalog(
                session, catalog_document, catalog_fingerprint, applied_by=f"lab:{name}"
            )
            row = m.RunRow(
                kind=kind,
                name=name,
                config=config,
                catalog_snapshot_id=snapshot.id,
                status="RUNNING",
                started_at=started_at,
            )
            session.add(row)
            await session.flush()
            self._catalog_snapshot[row.id] = snapshot.id
            return row.id

    async def finish_run(
        self, run_id: UUID, *, status: str, summary: dict[str, Any], finished_at: datetime
    ) -> None:
        async with self.db.session() as session:
            run = await session.get(m.RunRow, run_id)
            if run is None:
                raise KeyError(f"unknown run {run_id}")
            run.status = status
            run.summary = summary
            run.finished_at = finished_at

    # ── registration ────────────────────────────────────────────────────────
    async def register_instance(self, resolved: ResolvedInstance) -> UUID:
        key = (resolved.id, resolved.config_hash)
        if key in self._versions:
            return self._versions[key]
        definition = resolved.definition
        meta = definition.meta
        spec = resolved.spec
        async with self.db.session() as session:
            await strategy_repo.upsert_definition(
                session,
                strategy_repo.DefinitionRecord(
                    id=definition.id,
                    name=meta.name,
                    kind=definition.kind.value,
                    latest_version=meta.version,
                    module=definition.module,
                    description=meta.description,
                    meta=meta.model_dump(mode="json"),
                ),
            )
            await strategy_repo.upsert_instance(
                session,
                strategy_repo.InstanceRecord(
                    id=spec.id,
                    definition_id=definition.id,
                    name=spec.display_name,
                    description=spec.description,
                    enabled=spec.enabled,
                    tags=list(spec.tags),
                ),
            )
            version_id = await strategy_repo.get_or_create_version(
                session,
                strategy_repo.VersionRecord(
                    instance_id=spec.id,
                    definition_id=definition.id,
                    definition_version=meta.version,
                    code_hash=definition.code_hash,
                    params=resolved.params_document,
                    params_hash=hash_data(resolved.params_document),
                    config=resolved.config,
                    config_hash=resolved.config_hash,
                    framework_fingerprint=framework_fingerprint(),
                    kterminal_version=__version__,
                ),
            )
        self._versions[key] = version_id
        return version_id

    async def provision_account(
        self,
        *,
        instance_id: str,
        name: str,
        settings: AccountSettings,
        run_id: UUID | None = None,
        opened_at: datetime | None = None,
    ) -> ProvisionedAccount:
        if run_id is None:
            return await self._provision_dedicated(instance_id, name, settings, opened_at)
        return await self._provision_for_run(instance_id, name, settings, run_id, opened_at)

    async def _provision_dedicated(
        self, instance_id: str, name: str, settings: AccountSettings, opened_at: datetime | None
    ) -> ProvisionedAccount:
        """The instance's persistent forward-test account (one per instance, ever)."""
        async with self.db.session() as session:
            account_id, version_id, created = await account_repo.provision_dedicated_account(
                session,
                instance_id=instance_id,
                name=name,
                mode=settings.mode.value,
                broker="paper",
                currency=settings.currency,
                starting_balance=settings.starting_balance,
                venue_profile_id=settings.venue_profile,
                config=settings.document(),
                ts=opened_at,
            )
        self._modes[account_id] = settings.mode.value
        return ProvisionedAccount(account_id, version_id, name, created)

    async def _provision_for_run(
        self,
        instance_id: str,
        name: str,
        settings: AccountSettings,
        run_id: UUID,
        opened_at: datetime | None,
    ) -> ProvisionedAccount:
        """A fresh account for one simulation run, allocated to exactly one instance.

        Simulations never touch an instance's persistent forward-test account, so
        synthetic or historical results can never contaminate forward-test history.
        """
        account_id, version_id = uuid7(), uuid7()
        run_name = f"{name} · run {run_id.hex[-8:]}"
        document = settings.document()
        async with self.db.session() as session:
            session.add(
                m.AccountRow(
                    id=account_id,
                    name=run_name,
                    mode=settings.mode.value,
                    broker="paper-sim",
                    venue_profile_id=settings.venue_profile,
                    currency=settings.currency,
                    starting_balance=settings.starting_balance,
                    high_water_mark=settings.starting_balance,
                )
            )
            await session.flush()
            session.add(
                m.AccountConfigVersionRow(
                    id=version_id,
                    account_id=account_id,
                    version=1,
                    config=document,
                    config_hash=hash_data(document),
                )
            )
            await session.flush()
            account = await session.get(m.AccountRow, account_id)
            if account is None:  # pragma: no cover - just inserted
                raise RuntimeError("account vanished")
            account.current_config_version_id = version_id
            session.add(m.AccountAllocationRow(account_id=account_id, instance_id=instance_id))
            session.add(
                m.AccountLedgerRow(
                    id=uuid7(),
                    account_id=account_id,
                    ts=opened_at or datetime.now(UTC),
                    kind="DEPOSIT",
                    amount=settings.starting_balance,
                    balance_after=settings.starting_balance,
                    run_id=run_id,
                    note=f"starting balance of {run_name}",
                )
            )
        self._modes[account_id] = settings.mode.value
        return ProvisionedAccount(account_id, version_id, name, True)

    # ── records ─────────────────────────────────────────────────────────────
    async def write(self, records: Sequence[Record], *, run_id: UUID) -> None:
        grouped: dict[type, list[Any]] = defaultdict(list)
        for record in records:
            grouped[type(record)].append(record)
        snapshot_id = self._catalog_snapshot.get(run_id)
        async with self.db.session() as session:
            for kind in _ORDER:
                rows = grouped.get(kind)
                if rows:
                    await self._write_kind(session, kind, rows, run_id, snapshot_id)

    async def _write_kind(
        self,
        session: AsyncSession,
        kind: type,
        records: list[Any],
        run_id: UUID,
        snapshot_id: UUID | None,
    ) -> None:
        if kind is SignalRecord:
            await session.execute(
                insert(m.SignalRow), [self._signal_row(r, run_id, snapshot_id) for r in records]
            )
        elif kind is DecisionRecord:
            await session.execute(
                insert(m.RiskDecisionRow),
                [
                    {
                        "id": r.id,
                        "signal_id": r.signal_id,
                        "account_id": r.account_id,
                        "account_config_version_id": r.account_config_version_id,
                        "decided_at": r.decided_at,
                        "approved": r.approved,
                        "primary_reason": r.primary_reason,
                        "rule_results": r.rule_results,
                        "account_state": r.account_state,
                        "quote": r.quote,
                        "requested_qty": r.requested_qty,
                        "approved_qty": r.approved_qty,
                        "risk_amount": r.risk_amount,
                        "risk_pct": r.risk_pct,
                        "catalog_snapshot_id": snapshot_id,
                        "run_id": run_id,
                        "correlation_id": r.signal_id,
                    }
                    for r in records
                ],
            )
        elif kind is TradeRecord:
            for r in _latest_by_id(records):
                values = self._trade_row(r, run_id, snapshot_id)
                stmt = insert(m.TradeRow).values(values)
                await session.execute(
                    stmt.on_conflict_do_update(
                        index_elements=[m.TradeRow.id],
                        set_={k: v for k, v in values.items() if k != "id"},
                    )
                )
        elif kind is OrderRecord:
            for r in _latest_by_id(records):
                values = self._order_row(r, run_id)
                stmt = insert(m.OrderRow).values(values)
                await session.execute(
                    stmt.on_conflict_do_update(
                        index_elements=[m.OrderRow.id],
                        set_={k: v for k, v in values.items() if k != "id"},
                    )
                )
        elif kind is FillRecord:
            await session.execute(
                insert(m.FillRow),
                [
                    {
                        "id": r.id,
                        "order_id": r.order_id,
                        "account_id": r.account_id,
                        "ts": r.ts,
                        "qty": r.qty,
                        "price": r.price,
                        "commission": r.commission,
                        "liquidity": r.liquidity,
                        "spread_cost": r.spread_cost,
                        "slippage": r.slippage,
                        "run_id": run_id,
                    }
                    for r in records
                ],
            )
        elif kind is TradeEventRecord:
            await session.execute(
                insert(m.TradeEventRow),
                [
                    {
                        "id": r.id,
                        "trade_id": r.trade_id,
                        "ts": r.ts,
                        "kind": r.kind,
                        "old_value": r.old_value,
                        "new_value": r.new_value,
                        "signal_id": r.signal_id,
                        "details": r.details,
                    }
                    for r in records
                ],
            )
        elif kind is LedgerRecord:
            await session.execute(
                insert(m.AccountLedgerRow),
                [
                    {
                        "id": r.id,
                        "account_id": r.account_id,
                        "ts": r.ts,
                        "kind": r.kind,
                        "amount": r.amount,
                        "balance_after": r.balance_after,
                        "trade_id": r.trade_id,
                        "fill_id": r.fill_id,
                        "run_id": run_id,
                        "note": r.note,
                    }
                    for r in records
                ],
            )
        elif kind is EquityRecord:
            await session.execute(
                insert(m.EquitySnapshotRow),
                [
                    {
                        "account_id": r.account_id,
                        "ts": r.ts,
                        "balance": r.balance,
                        "equity": r.equity,
                        "open_pnl": r.open_pnl,
                        "open_risk": r.open_risk,
                        "daily_pnl": r.daily_pnl,
                        "drawdown": r.drawdown,
                        "high_water_mark": r.high_water_mark,
                        "run_id": run_id,
                    }
                    for r in records
                ],
            )
        elif kind is FaultRecord:
            await session.execute(
                insert(m.SystemErrorRow),
                [
                    {
                        "ts": r.recorded_at,
                        "component": "strategy.host",
                        "severity": "ERROR",
                        "message": f"{r.fault.error_type}: {r.fault.message}"[:2_000],
                        "exception": r.fault.traceback or None,
                        "context": {"stage": r.fault.stage, "instrument": r.fault.instrument},
                        "strategy_instance_id": r.instance_id,
                        "run_id": run_id,
                    }
                    for r in records
                ],
            )

    def _version_id(self, instance_id: str, config_hash: str) -> UUID:
        try:
            return self._versions[(instance_id, config_hash)]
        except KeyError:
            raise KeyError(
                f"strategy version of {instance_id} ({config_hash[:12]}) was not registered"
            ) from None

    def _signal_row(
        self, r: SignalRecord, run_id: UUID, snapshot_id: UUID | None
    ) -> dict[str, Any]:
        signal = r.signal
        row: dict[str, Any] = {
            "id": r.id,
            "strategy_instance_id": r.instance_id,
            "strategy_version_id": self._versions.get((r.instance_id, r.strategy_version)),
            "definition_id": r.definition_id,
            "source": signal.source.value if signal is not None else "INTERNAL",
            "run_id": run_id,
            "instrument": r.instrument,
            "raw_symbol": r.instrument,
            "timeframe": r.timeframe,
            "received_at": r.received_at,
            "signal_time": r.received_at,
            "status": r.status,
            "reject_code": r.reject_code,
            "reject_detail": r.reject_detail,
            "market_snapshot": r.market_snapshot,
            "raw_payload": r.raw_payload,
            "catalog_snapshot_id": snapshot_id,
            "correlation_id": r.id,
            "idempotency_key": f"{run_id}:{r.id}",
            "meta": {},
        }
        if signal is not None:
            row.update(
                action=signal.signal.value,
                order_type=signal.order_type.value,
                bar_time=signal.bar_time,
                signal_time=signal.timestamp,
                entry=signal.entry,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                risk_pct=signal.risk,
                confidence=Decimal(repr(signal.confidence))
                if signal.confidence is not None
                else None,
                meta=signal.metadata,
                idempotency_key=(
                    f"{run_id}:{r.instance_id}:{signal.symbol}:{signal.timeframe}:"
                    f"{signal.timestamp.isoformat()}:{signal.signal.value}:{r.id}"
                ),
            )
        return row

    def _trade_row(self, r: TradeRecord, run_id: UUID, snapshot_id: UUID | None) -> dict[str, Any]:
        return {
            "id": r.id,
            "account_id": r.account_id,
            "account_config_version_id": r.account_config_version_id,
            "strategy_instance_id": r.instance_id,
            "strategy_version_id": self._version_id(r.instance_id, r.strategy_version),
            "entry_signal_id": r.entry_signal_id,
            "exit_signal_id": r.exit_signal_id,
            "run_id": run_id,
            "catalog_snapshot_id": snapshot_id,
            "mode": r.mode,
            "instrument": r.instrument,
            "venue": r.venue,
            "venue_symbol": r.venue_symbol,
            "timeframe": r.timeframe,
            "direction": r.direction.value,
            "qty": r.qty,
            "entry_requested": r.entry_requested,
            "entry_price": r.entry_price,
            "entry_time": r.entry_time,
            "initial_stop": r.initial_stop,
            "initial_target": r.initial_target,
            "current_stop": r.current_stop,
            "current_target": r.current_target,
            "exit_price": r.exit_price,
            "exit_time": r.exit_time,
            "exit_reason": r.exit_reason,
            "initial_risk": r.initial_risk,
            "gross_pnl": r.gross_pnl,
            "commission": r.commission,
            "swap": r.swap,
            "funding": r.funding,
            "spread_cost": r.spread_cost,
            "net_pnl": r.net_pnl,
            "r_multiple": r.r_multiple,
            "entry_slippage": r.entry_slippage,
            "exit_slippage": r.exit_slippage,
            "mae": r.mae,
            "mfe": r.mfe,
            "session": r.session,
            "status": r.status,
            "correlation_id": r.correlation_id,
        }

    def _order_row(self, r: OrderRecord, run_id: UUID) -> dict[str, Any]:
        return {
            "id": r.id,
            "client_order_id": r.client_order_id,
            "account_id": r.account_id,
            "strategy_instance_id": r.instance_id,
            "trade_id": r.trade_id,
            "signal_id": r.signal_id,
            "risk_decision_id": r.decision_id,
            "run_id": run_id,
            "purpose": r.purpose,
            "mode": self._modes.get(r.account_id, "PAPER"),
            "venue": r.venue,
            "instrument": r.instrument,
            "venue_symbol": r.venue_symbol,
            "side": r.side.value,
            "order_type": r.order_type.value,
            "qty": r.qty,
            "requested_price": r.requested_price,
            "status": r.status,
            "filled_qty": r.filled_qty,
            "avg_fill_price": r.avg_fill_price,
            "slippage": r.slippage,
            "commission": r.commission,
            "reject_reason": r.reject_reason,
            "created_at": r.created_at,
            "submitted_at": r.created_at,
            "acknowledged_at": r.created_at,
            "completed_at": r.completed_at,
            "correlation_id": r.correlation_id,
        }

    # ── queries (metrics come from recorded rows) ───────────────────────────
    async def closed_trades(self, account_id: UUID) -> list[TradeRecord]:
        async with self.db.session() as session:
            rows = (
                (
                    await session.execute(
                        select(m.TradeRow)
                        .where(m.TradeRow.account_id == account_id, m.TradeRow.status == "CLOSED")
                        .order_by(m.TradeRow.exit_time, m.TradeRow.id)
                    )
                )
                .scalars()
                .all()
            )
        return [_trade_record(row) for row in rows]

    async def ledger_balance(self, account_id: UUID) -> Any:
        async with self.db.session() as session:
            return (
                await session.execute(
                    select(m.AccountLedgerRow.balance_after)
                    .where(m.AccountLedgerRow.account_id == account_id)
                    .order_by(m.AccountLedgerRow.seq.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()

    async def isolation_checks(self, run_id: UUID) -> list[Any]:
        from kterminal.paper.demo import IsolationCheck

        checks = []
        async with self.db.session() as session:
            owners = (
                await session.execute(
                    select(m.AccountAllocationRow.account_id, m.AccountAllocationRow.instance_id)
                    .where(
                        m.AccountAllocationRow.account_id.in_(
                            select(m.AccountLedgerRow.account_id)
                            .where(m.AccountLedgerRow.run_id == run_id)
                            .distinct()
                        )
                    )
                    .order_by(m.AccountAllocationRow.instance_id)
                )
            ).all()
            for account_id, instance in owners:
                decisions = await _count(
                    session,
                    select(func.count())
                    .select_from(m.RiskDecisionRow)
                    .where(
                        m.RiskDecisionRow.account_id == account_id,
                        m.RiskDecisionRow.run_id == run_id,
                    ),
                )
                foreign = await _count(
                    session,
                    select(func.count())
                    .select_from(m.RiskDecisionRow)
                    .join(m.SignalRow, m.SignalRow.id == m.RiskDecisionRow.signal_id)
                    .where(
                        m.RiskDecisionRow.account_id == account_id,
                        m.RiskDecisionRow.run_id == run_id,
                        m.SignalRow.strategy_instance_id != instance,
                    ),
                )
                trades = await _count(
                    session,
                    select(func.count())
                    .select_from(m.TradeRow)
                    .where(m.TradeRow.account_id == account_id, m.TradeRow.run_id == run_id),
                )
                # A trade belongs to the instance whose *signal* opened it — checked against
                # the signal row, not only the trade's own instance column.
                other_trades = await _count(
                    session,
                    select(func.count())
                    .select_from(m.TradeRow)
                    .join(m.SignalRow, m.SignalRow.id == m.TradeRow.entry_signal_id)
                    .where(
                        m.TradeRow.account_id == account_id,
                        m.TradeRow.run_id == run_id,
                        or_(
                            m.TradeRow.strategy_instance_id != instance,
                            m.SignalRow.strategy_instance_id != instance,
                        ),
                    ),
                )
                ledger_total = (
                    await session.execute(
                        select(
                            func.coalesce(func.sum(m.AccountLedgerRow.amount), 0), func.count()
                        ).where(m.AccountLedgerRow.account_id == account_id)
                    )
                ).one()
                latest = (
                    await session.execute(
                        select(m.AccountLedgerRow.balance_after)
                        .where(m.AccountLedgerRow.account_id == account_id)
                        .order_by(m.AccountLedgerRow.seq.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                checks.append(
                    IsolationCheck(
                        instance_id=str(instance),
                        account_id=str(account_id),
                        decisions=decisions,
                        decisions_on_foreign_signals=foreign,
                        trades=trades,
                        trades_of_other_instances=other_trades,
                        ledger_entries=int(ledger_total[1]),
                        # the ledger starts with the DEPOSIT of the starting balance
                        balance_matches_ledger=latest == ledger_total[0],
                    )
                )
        return checks


async def _count(session: AsyncSession, stmt: Any) -> int:
    return int((await session.execute(stmt)).scalar_one())


def _latest_by_id(records: list[Any]) -> list[Any]:
    latest: dict[UUID, Any] = {}
    for record in records:
        latest[record.id] = record
    return list(latest.values())


def _trade_record(row: m.TradeRow) -> TradeRecord:
    from kterminal.core.enums import Direction

    return TradeRecord(
        id=row.id,
        account_id=row.account_id,
        account_config_version_id=row.account_config_version_id,
        instance_id=row.strategy_instance_id,
        strategy_version=str(row.strategy_version_id),
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
        current_stop=row.current_stop or row.initial_stop,
        current_target=row.current_target,
        initial_risk=row.initial_risk,
        status=row.status,
        correlation_id=row.correlation_id,
        session=row.session,
        exit_signal_id=row.exit_signal_id,
        exit_price=row.exit_price,
        exit_time=row.exit_time,
        exit_reason=row.exit_reason,
        gross_pnl=row.gross_pnl,
        commission=row.commission,
        swap=row.swap,
        funding=row.funding,
        net_pnl=row.net_pnl,
        r_multiple=row.r_multiple,
        entry_slippage=row.entry_slippage,
        exit_slippage=row.exit_slippage,
        spread_cost=row.spread_cost,
        mae=row.mae,
        mfe=row.mfe,
    )
