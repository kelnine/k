"""Trades, open positions and "explain this trade" (docs/04 §4.9)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from kterminal.api.queries.candles import stored_timeframes
from kterminal.api.queries.common import (
    TRADE_COLUMNS,
    decision_out,
    signal_out,
    trade_fields,
    trade_out,
    value_per_unit,
    version_out,
)
from kterminal.api.schemas import (
    AccountConfigOut,
    FillOut,
    LedgerEntryOut,
    OrderOut,
    PositionOut,
    TradeEventOut,
    TradeExplainOut,
    TradeOut,
)
from kterminal.db import models as m

TradeScope = Literal["forward", "run", "all"]

_RECENT_CANDLE_WINDOW = timedelta(hours=6)


@dataclass(frozen=True, slots=True)
class TradeFilter:
    scope: TradeScope = "all"
    account_id: UUID | None = None
    instance_id: str | None = None
    run_id: UUID | None = None
    instrument: str | None = None
    status: Literal["OPEN", "CLOSED"] | None = None
    direction: Literal["LONG", "SHORT"] | None = None
    since: datetime | None = None
    until: datetime | None = None


def _conditions(filters: TradeFilter) -> list[ColumnElement[bool]]:
    t = m.TradeRow
    conditions: list[ColumnElement[bool]] = []
    if filters.scope == "forward":
        conditions.append(m.AccountRow.strategy_instance_id.is_not(None))
    elif filters.scope == "run":
        conditions.append(m.AccountRow.strategy_instance_id.is_(None))
    if filters.account_id is not None:
        conditions.append(t.account_id == filters.account_id)
    if filters.instance_id:
        conditions.append(t.strategy_instance_id == filters.instance_id)
    if filters.run_id is not None:
        conditions.append(t.run_id == filters.run_id)
    if filters.instrument:
        conditions.append(t.instrument == filters.instrument)
    if filters.status:
        conditions.append(t.status == filters.status)
    if filters.direction:
        conditions.append(t.direction == filters.direction)
    if filters.since is not None:
        conditions.append(or_(t.exit_time >= filters.since, t.exit_time.is_(None)))
    if filters.until is not None:
        conditions.append(t.entry_time < filters.until)
    return conditions


async def list_trades(
    session: AsyncSession, filters: TradeFilter, *, limit: int, offset: int
) -> tuple[list[TradeOut], int]:
    conditions = _conditions(filters)
    total = (
        await session.execute(
            select(func.count())
            .select_from(m.TradeRow)
            .join(m.AccountRow, m.AccountRow.id == m.TradeRow.account_id)
            .where(*conditions)
        )
    ).scalar_one()
    rows = await session.execute(
        select(*TRADE_COLUMNS, m.AccountRow.name.label("account_name"))
        .join(m.AccountRow, m.AccountRow.id == m.TradeRow.account_id)
        .where(*conditions)
        .order_by(
            func.coalesce(m.TradeRow.exit_time, m.TradeRow.entry_time).desc(), m.TradeRow.id.desc()
        )
        .limit(limit)
        .offset(offset)
    )
    return [trade_out(row._mapping) for row in rows], int(total)


async def open_positions(
    session: AsyncSession, filters: TradeFilter, *, now: datetime
) -> list[PositionOut]:
    """Open trades marked at their instrument's latest recorded candle close."""
    conditions = [*_conditions(filters), m.TradeRow.status == "OPEN"]
    rows = (
        await session.execute(
            select(*TRADE_COLUMNS, m.AccountRow.name.label("account_name"))
            .join(m.AccountRow, m.AccountRow.id == m.TradeRow.account_id)
            .where(*conditions)
            .order_by(m.TradeRow.entry_time.desc())
        )
    ).all()
    prices = {}
    for instrument in sorted({row.instrument for row in rows}):
        prices[instrument] = await latest_price(session, instrument, now=now)
    out = []
    for row in rows:
        fields = trade_fields(row._mapping)
        mark = prices.get(row.instrument)
        unrealized = unrealized_r = None
        if mark is not None:
            vpu = value_per_unit(row.initial_risk, row.entry_price, row.initial_stop, row.qty)
            if vpu is not None:
                sign = 1 if row.direction == "LONG" else -1
                unrealized = ((mark[1] - row.entry_price) * sign * row.qty * vpu).quantize(
                    Decimal("0.01")
                )
                if row.initial_risk:
                    unrealized_r = (unrealized / row.initial_risk).quantize(Decimal("0.01"))
        out.append(
            PositionOut(
                **fields,
                last_price=mark[1] if mark else None,
                last_price_at=mark[0] if mark else None,
                unrealized_pnl=unrealized,
                unrealized_r=unrealized_r,
            )
        )
    return out


async def latest_price(
    session: AsyncSession, instrument: str, *, now: datetime
) -> tuple[datetime, Decimal] | None:
    """(close time, close) of the instrument's newest stored candle of its finest timeframe.

    Looks at recent partitions first (forward trading), then anywhere (historical runs).
    """
    c = m.CandleRow
    stored = await stored_timeframes(session, instrument)
    if not stored:
        return None
    timeframe, duration = stored[0]
    for since in (now - _RECENT_CANDLE_WINDOW, None):
        conditions = [c.instrument == instrument, c.timeframe == timeframe]
        if since is not None:
            conditions.append(c.ts >= since)
        row = (
            await session.execute(
                select(c.ts, c.close).where(*conditions).order_by(c.ts.desc()).limit(1)
            )
        ).first()
        if row is not None:
            return row.ts + duration, Decimal(row.close)
    return None


async def explain_trade(session: AsyncSession, trade_id: UUID) -> TradeExplainOut | None:
    row = (
        await session.execute(
            select(*TRADE_COLUMNS, m.AccountRow.name.label("account_name"))
            .join(m.AccountRow, m.AccountRow.id == m.TradeRow.account_id)
            .where(m.TradeRow.id == trade_id)
        )
    ).first()
    if row is None:
        return None
    trade = await session.get(m.TradeRow, trade_id)
    if trade is None:  # pragma: no cover - just read
        return None
    version = await session.get(m.StrategyVersionRow, trade.strategy_version_id)
    definition = (
        await session.get(m.StrategyDefinitionRow, version.definition_id) if version else None
    )
    account_config = await session.get(m.AccountConfigVersionRow, trade.account_config_version_id)
    if version is None or definition is None or account_config is None:  # FKs guarantee these
        raise LookupError(f"trade {trade_id} references missing rows")
    snapshot = (
        await session.get(m.CatalogSnapshotRow, trade.catalog_snapshot_id)
        if trade.catalog_snapshot_id
        else None
    )
    entry_signal = await session.get(m.SignalRow, trade.entry_signal_id)
    if entry_signal is None:  # pragma: no cover - a foreign key guarantees it
        raise LookupError(f"trade {trade_id} references a missing entry signal")
    exit_signal = (
        await session.get(m.SignalRow, trade.exit_signal_id) if trade.exit_signal_id else None
    )
    decision = (
        await session.execute(
            select(m.RiskDecisionRow).where(
                m.RiskDecisionRow.signal_id == trade.entry_signal_id,
                m.RiskDecisionRow.account_id == trade.account_id,
            )
        )
    ).scalar_one_or_none()
    orders = list(
        (
            await session.execute(
                select(m.OrderRow)
                .where(
                    or_(
                        m.OrderRow.trade_id == trade_id,
                        (m.OrderRow.signal_id == trade.entry_signal_id)
                        & (m.OrderRow.account_id == trade.account_id),
                    )
                )
                .order_by(m.OrderRow.created_at, m.OrderRow.id)
            )
        ).scalars()
    )
    fills: Sequence[m.FillRow] = []
    if orders:
        fills = list(
            (
                await session.execute(
                    select(m.FillRow)
                    .where(m.FillRow.order_id.in_([o.id for o in orders]))
                    .order_by(m.FillRow.ts, m.FillRow.id)
                )
            ).scalars()
        )
    events = (
        await session.execute(
            select(m.TradeEventRow)
            .where(m.TradeEventRow.trade_id == trade_id)
            .order_by(m.TradeEventRow.ts, m.TradeEventRow.id)
        )
    ).scalars()
    ledger = (
        await session.execute(
            select(m.AccountLedgerRow)
            .where(m.AccountLedgerRow.trade_id == trade_id)
            .order_by(m.AccountLedgerRow.seq)
        )
    ).scalars()
    return TradeExplainOut(
        trade=trade_out(row._mapping),
        definition_id=definition.id,
        definition_name=definition.name,
        version=version_out(version),
        account_config=AccountConfigOut(
            id=account_config.id, version=account_config.version, config=account_config.config
        ),
        catalog_fingerprint=snapshot.fingerprint if snapshot else None,
        entry_signal=signal_out(entry_signal),
        entry_market_snapshot=dict(entry_signal.market_snapshot or {}),
        exit_signal=signal_out(exit_signal) if exit_signal else None,
        decision=decision_out(decision) if decision else None,
        orders=[_order_out(o) for o in orders],
        fills=[
            FillOut(
                id=f.id,
                order_id=f.order_id,
                ts=f.ts,
                qty=f.qty,
                price=f.price,
                commission=f.commission,
                liquidity=f.liquidity,
                spread_cost=f.spread_cost,
                slippage=f.slippage,
            )
            for f in fills
        ],
        events=[
            TradeEventOut(
                id=e.id,
                ts=e.ts,
                kind=e.kind,
                old_value=e.old_value,
                new_value=e.new_value,
                signal_id=e.signal_id,
                details=dict(e.details or {}),
            )
            for e in events
        ],
        ledger=[
            LedgerEntryOut(
                ts=entry.ts,
                kind=entry.kind,
                amount=entry.amount,
                balance_after=entry.balance_after,
                note=entry.note,
            )
            for entry in ledger
        ],
    )


def _order_out(o: m.OrderRow) -> OrderOut:
    return OrderOut(
        id=o.id,
        purpose=o.purpose,
        side=o.side,
        order_type=o.order_type,
        qty=o.qty,
        requested_price=o.requested_price,
        status=o.status,
        filled_qty=o.filled_qty,
        avg_fill_price=o.avg_fill_price,
        slippage=o.slippage,
        commission=o.commission,
        reject_reason=o.reject_reason,
        created_at=o.created_at,
        submitted_at=o.submitted_at,
        completed_at=o.completed_at,
    )
