"""Account metrics for the dashboard, per appendix A — always recomputed from what
was recorded (closed trades, the ledger and equity snapshots), never cached in
strategy state and never hard-coded.

Trade statistics come from :func:`kterminal.analytics.summary.summarize_trades`
(the same function the lab report uses). This module adds what needs the
account's ledger and equity curve:

* **balance** — ``balance_after`` of the latest ledger entry;
* **equity** — the balance while the account is flat; with open positions the
  latest mark-to-market snapshot (its open P&L added to the balance when the
  ledger has moved since the snapshot);
* **return %** — ``(equity − starting balance) / starting balance × 100``;
* **expectancy** — ``win rate × average winner + (1 − win rate) × average loser``
  (currency); expectancy in R is the average R;
* **max drawdown** — largest peak-to-trough decline of the equity curve, the
  starting balance counting as the first peak (see :func:`drawdown_stats`).
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from kterminal.analytics.summary import summarize_trades
from kterminal.api.schemas import AccountMetrics

LOW_SAMPLE_TRADES = 30
"""Appendix A: leaderboard rows below this many closed trades are flagged "low sample"."""

_CENT = Decimal("0.01")
_ZERO = Decimal(0)


@dataclass(frozen=True, slots=True)
class ClosedTrade:
    net_pnl: Decimal | None
    r_multiple: Decimal | None


@dataclass(frozen=True, slots=True)
class EquityMark:
    ts: datetime
    equity: Decimal
    open_pnl: Decimal


@dataclass(frozen=True, slots=True)
class Drawdown:
    amount: Decimal  # positive: the decline in account currency
    pct: Decimal  # positive: the decline as % of the peak it fell from


def drawdown_stats(starting_balance: Decimal, equity: Sequence[Decimal]) -> Drawdown | None:
    """Maximum drawdown of an equity curve (in time order) that starts at ``starting_balance``.

    The database computes the same with window functions for whole leaderboards
    (:mod:`kterminal.api.queries.accounts`); this is the reference definition.
    """
    if not equity:
        return None
    peak = starting_balance
    worst = _ZERO
    worst_pct = _ZERO
    for value in equity:
        peak = max(peak, value)
        decline = peak - value
        worst = max(worst, decline)
        if peak > 0:
            worst_pct = max(worst_pct, decline / peak * 100)
    return Drawdown(worst, worst_pct.quantize(_CENT))


def account_metrics(
    *,
    starting_balance: Decimal,
    balance: Decimal,
    closed: Iterable[ClosedTrade],
    open_positions: int,
    last_ledger_at: datetime | None,
    mark: EquityMark | None,
    drawdown: Drawdown | None,
    last_trade_at: datetime | None,
) -> AccountMetrics:
    summary = summarize_trades(closed)
    if open_positions == 0:
        equity, open_pnl = balance, _ZERO
        equity_at = last_ledger_at
        if mark is not None and (equity_at is None or mark.ts > equity_at):
            equity_at = mark.ts
    elif mark is not None:
        open_pnl = mark.open_pnl
        ledger_moved = last_ledger_at is not None and last_ledger_at > mark.ts
        equity = balance + open_pnl if ledger_moved else mark.equity
        equity_at = mark.ts
    else:  # open positions but never marked: the balance is the best we know
        equity, open_pnl, equity_at = balance, None, last_ledger_at
    avg_winner = summary.gross_profit / summary.wins if summary.wins else None
    avg_loser = summary.gross_loss / summary.losses if summary.losses else None
    expectancy = None
    if summary.win_rate is not None:
        expectancy = (
            summary.win_rate * (avg_winner or _ZERO) + (1 - summary.win_rate) * (avg_loser or _ZERO)
        ).quantize(_CENT)
    return AccountMetrics(
        starting_balance=starting_balance,
        balance=balance,
        equity=equity,
        equity_at=equity_at,
        open_pnl=open_pnl,
        net_pnl=summary.net_pnl,
        return_pct=((equity - starting_balance) / starting_balance * 100).quantize(_CENT)
        if starting_balance
        else _ZERO,
        trades=summary.trades,
        wins=summary.wins,
        losses=summary.losses,
        scratches=summary.scratches,
        win_rate=summary.win_rate,
        gross_profit=summary.gross_profit,
        gross_loss=summary.gross_loss,
        profit_factor=summary.profit_factor,
        average_r=summary.average_r,
        realized_r=summary.realized_r,
        avg_winner=None if avg_winner is None else avg_winner.quantize(_CENT),
        avg_loser=None if avg_loser is None else avg_loser.quantize(_CENT),
        expectancy=expectancy,
        max_drawdown=None if drawdown is None else drawdown.amount,
        max_drawdown_pct=None if drawdown is None else drawdown.pct,
        open_positions=open_positions,
        low_sample=summary.trades < LOW_SAMPLE_TRADES,
        last_trade_at=last_trade_at,
    )
