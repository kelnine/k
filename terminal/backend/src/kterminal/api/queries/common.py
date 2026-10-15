"""Row → response conversions shared by the read models."""

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from kterminal.api.schemas import (
    DecisionOut,
    DecisionSummary,
    SignalOut,
    TradeOut,
    VersionOut,
)
from kterminal.db import models as m

MAX_PAGE_SIZE = 500


def version_out(row: m.StrategyVersionRow) -> VersionOut:
    config: Mapping[str, Any] = row.config or {}
    instruments = config.get("instruments") or {}
    return VersionOut(
        id=row.id,
        config_hash=row.config_hash,
        definition_version=row.definition_version,
        code_hash=row.code_hash,
        params=dict(row.params or {}),
        timeframe=config.get("timeframe"),
        context_timeframes=list(config.get("context_timeframes") or []),
        instruments=sorted(instruments) if isinstance(instruments, Mapping | list) else [],
        created_at=row.created_at,
    )


TRADE_COLUMNS = tuple(
    getattr(m.TradeRow, name)
    for name in (
        "id",
        "account_id",
        "strategy_instance_id",
        "strategy_version_id",
        "run_id",
        "mode",
        "instrument",
        "venue",
        "venue_symbol",
        "timeframe",
        "direction",
        "status",
        "qty",
        "entry_requested",
        "entry_price",
        "entry_time",
        "initial_stop",
        "initial_target",
        "current_stop",
        "current_target",
        "exit_price",
        "exit_time",
        "exit_reason",
        "initial_risk",
        "gross_pnl",
        "commission",
        "swap",
        "funding",
        "spread_cost",
        "net_pnl",
        "r_multiple",
        "entry_slippage",
        "exit_slippage",
        "mae",
        "mfe",
        "session",
    )
)
"""Every column a :class:`TradeOut` needs (select them with ``accounts.name``)."""


def trade_fields(row: Mapping[Any, Any]) -> dict[str, Any]:
    """A row of :data:`TRADE_COLUMNS` + ``account_name`` (``row._mapping``) as TradeOut fields."""
    data = dict(row)
    data["instance_id"] = data.pop("strategy_instance_id")
    return data


def trade_out(row: Mapping[Any, Any]) -> TradeOut:
    return TradeOut(**trade_fields(row))


def signal_out(row: m.SignalRow) -> SignalOut:
    return SignalOut(
        id=row.id,
        instance_id=row.strategy_instance_id,
        strategy_version_id=row.strategy_version_id,
        source=row.source,
        run_id=row.run_id,
        instrument=row.instrument,
        timeframe=row.timeframe,
        bar_time=row.bar_time,
        signal_time=row.signal_time,
        received_at=row.received_at,
        action=row.action,
        order_type=row.order_type,
        entry=row.entry,
        stop_loss=row.stop_loss,
        take_profit=row.take_profit,
        risk_pct=row.risk_pct,
        confidence=row.confidence,
        reason=row.reason,
        status=row.status,
        reject_code=row.reject_code,
        reject_detail=row.reject_detail,
        metadata=dict(row.meta or {}),
    )


def decision_summary(row: m.RiskDecisionRow) -> DecisionSummary:
    return DecisionSummary(
        id=row.id,
        account_id=row.account_id,
        decided_at=row.decided_at,
        approved=row.approved,
        primary_reason=row.primary_reason,
        approved_qty=row.approved_qty,
        risk_amount=row.risk_amount,
    )


def decision_out(row: m.RiskDecisionRow) -> DecisionOut:
    return DecisionOut(
        **decision_summary(row).model_dump(),
        requested_qty=row.requested_qty,
        risk_pct=row.risk_pct,
        rule_results=list(row.rule_results or []),
        account_state=dict(row.account_state or {}),
        quote=dict(row.quote or {}),
    )


def value_per_unit(
    initial_risk: Decimal, entry_price: Decimal, initial_stop: Decimal, qty: Decimal
) -> Decimal | None:
    """Account currency per price unit per quantity unit, recovered from the trade's own
    ``initial_risk = |entry − initial stop| × qty × value per unit`` (appendix A)."""
    distance = abs(entry_price - initial_stop) * qty
    if not distance:
        return None
    return initial_risk / distance


def clamp_limit(limit: int) -> int:
    return max(1, min(limit, MAX_PAGE_SIZE))
