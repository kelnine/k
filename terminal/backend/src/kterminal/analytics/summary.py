"""Trade summaries computed from **recorded** trades — never from strategy state
and never hard-coded. The full metric set of appendix A (drawdowns, Sharpe,
breakdowns, leaderboard) builds on this in Phase 4.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol


class _ClosedTrade(Protocol):
    @property
    def net_pnl(self) -> Decimal | None: ...

    @property
    def r_multiple(self) -> Decimal | None: ...


@dataclass(frozen=True, slots=True)
class TradeSummary:
    trades: int
    wins: int
    losses: int
    scratches: int
    win_rate: Decimal | None
    gross_profit: Decimal
    gross_loss: Decimal
    net_pnl: Decimal
    profit_factor: Decimal | None
    average_r: Decimal | None
    realized_r: Decimal


def summarize_trades(trades: Iterable[_ClosedTrade]) -> TradeSummary:
    pnls: list[Decimal] = []
    r_values: list[Decimal] = []
    for trade in trades:
        if trade.net_pnl is None:
            continue
        pnls.append(trade.net_pnl)
        if trade.r_multiple is not None:
            r_values.append(trade.r_multiple)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_profit = sum(wins, Decimal(0))
    gross_loss = sum(losses, Decimal(0))
    decided = len(wins) + len(losses)
    return TradeSummary(
        trades=len(pnls),
        wins=len(wins),
        losses=len(losses),
        scratches=len(pnls) - decided,
        win_rate=(Decimal(len(wins)) / decided).quantize(Decimal("0.0001")) if decided else None,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        net_pnl=gross_profit + gross_loss,
        profit_factor=(gross_profit / -gross_loss).quantize(Decimal("0.01"))
        if gross_loss < 0
        else None,
        average_r=(sum(r_values, Decimal(0)) / len(r_values)).quantize(Decimal("0.0001"))
        if r_values
        else None,
        realized_r=sum(r_values, Decimal(0)),
    )
