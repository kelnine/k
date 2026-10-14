"""The signal log: every recorded signal with what became of it.

A signal's *outcome* combines the signal's own status and the risk decision on
the account:

=============  =========================================================
``APPROVED``   the risk layer approved it on the account
``REJECTED``   the risk layer rejected it (code: the first failing rule)
``INVALID``    the framework refused the strategy's output (code: why)
``IGNORED``    recorded but not routed (a persisted ``NO_TRADE``)
``NO_DECISION``routed without a risk decision (exits and stop moves)
=============  =========================================================
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal
from uuid import UUID

from sqlalchemy import ColumnElement, and_, false, func, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from kterminal.api.queries.common import decision_summary, signal_out
from kterminal.api.schemas import SignalLogItem
from kterminal.db import models as m

Outcome = Literal["APPROVED", "REJECTED", "INVALID", "IGNORED", "NO_DECISION"]
OUTCOMES: Final = ("APPROVED", "REJECTED", "INVALID", "IGNORED", "NO_DECISION")


@dataclass(frozen=True, slots=True)
class SignalFilter:
    scope: Literal["forward", "run", "all"] = "all"
    account_id: UUID | None = None
    instance_id: str | None = None
    run_id: UUID | None = None
    instrument: str | None = None
    action: str | None = None
    outcome: Outcome | None = None
    since: datetime | None = None
    until: datetime | None = None


class UnknownAccountError(LookupError):
    pass


async def list_signals(
    session: AsyncSession, filters: SignalFilter, *, limit: int, offset: int
) -> tuple[list[SignalLogItem], int]:
    s, d = m.SignalRow, m.RiskDecisionRow
    join_on: ColumnElement[bool] = d.signal_id == s.id
    conditions: list[ColumnElement[bool]] = []
    forward_runs = select(m.RunRow.id).where(m.RunRow.kind == "FORWARD")
    if filters.account_id is not None:
        account = await session.get(m.AccountRow, filters.account_id)
        if account is None:
            raise UnknownAccountError(str(filters.account_id))
        join_on = and_(join_on, d.account_id == account.id)
        if account.strategy_instance_id is not None:  # forward account: forward signals only
            conditions.append(s.strategy_instance_id == account.strategy_instance_id)
            conditions.append(or_(s.run_id.is_(None), s.run_id.in_(forward_runs)))
        else:  # run account: its run's signals of its instance
            allocated = select(m.AccountAllocationRow.instance_id).where(
                m.AccountAllocationRow.account_id == account.id
            )
            opened = select(m.AccountLedgerRow.run_id).where(
                m.AccountLedgerRow.account_id == account.id, m.AccountLedgerRow.kind == "DEPOSIT"
            )
            conditions.append(s.strategy_instance_id.in_(allocated))
            conditions.append(s.run_id.in_(opened))
    if filters.scope == "forward":
        conditions.append(or_(s.run_id.is_(None), s.run_id.in_(forward_runs)))
    elif filters.scope == "run":
        conditions.append(and_(s.run_id.is_not(None), s.run_id.not_in(forward_runs)))
    if filters.instance_id:
        conditions.append(s.strategy_instance_id == filters.instance_id)
    if filters.run_id is not None:
        conditions.append(s.run_id == filters.run_id)
    if filters.instrument:
        conditions.append(s.instrument == filters.instrument)
    if filters.action:
        conditions.append(s.action == filters.action)
    if filters.since is not None:
        conditions.append(s.signal_time >= filters.since)
    if filters.until is not None:
        conditions.append(s.signal_time < filters.until)
    if filters.outcome is not None:
        conditions.append(_outcome_condition(filters.outcome))

    base = select(s, d).outerjoin(d, join_on).where(*conditions)
    total = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = await session.execute(
        base.order_by(s.signal_time.desc(), s.id.desc()).limit(limit).offset(offset)
    )
    items = []
    for signal, decision in rows.tuples():
        outcome, code = _outcome(signal, decision)
        items.append(
            SignalLogItem(
                **signal_out(signal).model_dump(),
                decision=decision_summary(decision) if decision is not None else None,
                outcome=outcome,
                outcome_code=code,
            )
        )
    return items, int(total)


def _outcome_condition(outcome: Outcome) -> ColumnElement[bool]:
    s, d = m.SignalRow, m.RiskDecisionRow
    if outcome == "APPROVED":
        return d.approved.is_(true())
    if outcome == "REJECTED":
        return d.approved.is_(false())
    if outcome == "INVALID":
        return s.status == "INVALID"
    if outcome == "IGNORED":
        return s.status == "IGNORED"
    return and_(d.id.is_(None), s.status.not_in(("INVALID", "IGNORED")))


def _outcome(signal: m.SignalRow, decision: m.RiskDecisionRow | None) -> tuple[Outcome, str | None]:
    if signal.status == "INVALID":
        return "INVALID", signal.reject_code
    if signal.status == "IGNORED":
        return "IGNORED", signal.reject_code
    if decision is not None:
        if decision.approved:
            return "APPROVED", None
        return "REJECTED", decision.primary_reason
    return "NO_DECISION", signal.reject_code
