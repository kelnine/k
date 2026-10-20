"""Account metrics (appendix A) from hand-computed examples."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from kterminal.api.metrics import (
    ClosedTrade,
    Drawdown,
    EquityMark,
    account_metrics,
    drawdown_stats,
)

T0 = datetime(2026, 10, 5, tzinfo=UTC)
D = Decimal


def trades(*rows: tuple[str, str | None]) -> list[ClosedTrade]:
    return [ClosedTrade(D(pnl), None if r is None else D(r)) for pnl, r in rows]


def test_drawdown_starts_from_the_starting_balance() -> None:
    # 50,000 → 49,000 (−1,000 from the opening balance) → 52,000 → 50,700 (−1,300 = 2.5 %)
    result = drawdown_stats(D(50_000), [D(49_000), D(52_000), D(50_700), D(51_000)])
    assert result == Drawdown(D(1_300), D("2.50"))


def test_drawdown_percent_is_measured_from_its_own_peak() -> None:
    # the largest amount (2,000 from 100,000) and the largest percent (1,500 from 50,000)
    # come from different peaks, as appendix A defines them separately
    result = drawdown_stats(D(50_000), [D(48_500), D(100_000), D(98_000)])
    assert result is not None
    assert result.amount == D(2_000)
    assert result.pct == D("3.00")


def test_no_curve_no_drawdown() -> None:
    assert drawdown_stats(D(50_000), []) is None
    flat = drawdown_stats(D(50_000), [D(50_000), D(50_100)])
    assert flat == Drawdown(D(0), D("0.00"))


def test_metrics_of_a_flat_account() -> None:
    metrics = account_metrics(
        starting_balance=D(50_000),
        balance=D(50_250),
        closed=trades(("500", "2"), ("-250", "-1"), ("-250", "-1"), ("250", "1"), ("0", "0")),
        open_positions=0,
        last_ledger_at=T0,
        mark=EquityMark(T0 - timedelta(hours=1), D(49_000), D(-1_000)),
        drawdown=Drawdown(D(500), D("1.00")),
        last_trade_at=T0,
    )
    assert metrics.equity == D(50_250)  # flat: equity is the balance
    assert metrics.open_pnl == 0
    assert metrics.equity_at == T0
    assert metrics.return_pct == D("0.50")
    assert (metrics.trades, metrics.wins, metrics.losses, metrics.scratches) == (5, 2, 2, 1)
    assert metrics.win_rate == D("0.5000")  # scratches excluded
    assert metrics.net_pnl == D(250)
    assert metrics.gross_profit == D(750)
    assert metrics.gross_loss == D(-500)
    assert metrics.profit_factor == D("1.50")
    assert metrics.average_r == D("0.2000")
    assert metrics.realized_r == D(1)
    assert metrics.avg_winner == D("375.00")
    assert metrics.avg_loser == D("-250.00")
    assert metrics.expectancy == D("62.50")  # 0.5 × 375 + 0.5 × (−250)
    assert metrics.max_drawdown == D(500)
    assert metrics.low_sample


def test_open_positions_use_the_latest_mark() -> None:
    mark = EquityMark(T0, D("50100.50"), D("100.50"))
    metrics = account_metrics(
        starting_balance=D(50_000),
        balance=D(50_000),
        closed=[],
        open_positions=1,
        last_ledger_at=T0 - timedelta(hours=2),
        mark=mark,
        drawdown=None,
        last_trade_at=None,
    )
    assert metrics.equity == D("50100.50")
    assert metrics.open_pnl == D("100.50")
    assert metrics.equity_at == T0
    assert metrics.return_pct == D("0.20")
    assert metrics.win_rate is None
    assert metrics.profit_factor is None
    assert metrics.expectancy is None
    assert metrics.max_drawdown is None


def test_a_ledger_newer_than_the_mark_keeps_the_marks_open_pnl() -> None:
    # a trade closed after the last snapshot while another stays open
    metrics = account_metrics(
        starting_balance=D(50_000),
        balance=D(50_300),
        closed=trades(("300", "1.2")),
        open_positions=1,
        last_ledger_at=T0 + timedelta(minutes=5),
        mark=EquityMark(T0, D(50_050), D(50)),
        drawdown=None,
        last_trade_at=T0 + timedelta(minutes=5),
    )
    assert metrics.equity == D(50_350)
    assert metrics.open_pnl == D(50)


def test_open_positions_without_any_mark() -> None:
    metrics = account_metrics(
        starting_balance=D(50_000),
        balance=D(50_000),
        closed=[],
        open_positions=2,
        last_ledger_at=T0,
        mark=None,
        drawdown=None,
        last_trade_at=None,
    )
    assert metrics.equity == D(50_000)
    assert metrics.open_pnl is None


def test_only_winners_or_only_losers() -> None:
    winners = account_metrics(
        starting_balance=D(50_000),
        balance=D(50_400),
        closed=trades(("200", "1"), ("200", "1")),
        open_positions=0,
        last_ledger_at=T0,
        mark=None,
        drawdown=None,
        last_trade_at=T0,
    )
    assert winners.profit_factor is None  # shown as "—": no losses
    assert winners.expectancy == D("200.00")
    losers = account_metrics(
        starting_balance=D(50_000),
        balance=D(49_700),
        closed=trades(("-100", "-0.5"), ("-200", "-1")),
        open_positions=0,
        last_ledger_at=T0,
        mark=None,
        drawdown=None,
        last_trade_at=T0,
    )
    assert losers.win_rate == 0
    assert losers.expectancy == D("-150.00")
    assert losers.return_pct == D("-0.60")


def test_thirty_trades_are_no_longer_a_low_sample() -> None:
    metrics = account_metrics(
        starting_balance=D(50_000),
        balance=D(50_000),
        closed=trades(*[("10", "0.1"), ("-10", "-0.1")] * 15),
        open_positions=0,
        last_ledger_at=T0,
        mark=None,
        drawdown=None,
        last_trade_at=T0,
    )
    assert metrics.trades == 30
    assert not metrics.low_sample
