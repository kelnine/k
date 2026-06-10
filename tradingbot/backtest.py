"""Bar-by-bar backtester reusing the live Engine, so what you test is what
runs. Bars from different timeframes are merged onto one clock; each
instrument is only re-evaluated when one of *its* bars closes.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .broker import PaperBroker
from .config import BotConfig, Instrument
from .engine import Engine


@dataclass
class BacktestResult:
    equity_curve: pd.Series
    trades: int
    wins: int
    final_equity: float
    max_drawdown: float

    @property
    def win_rate(self) -> float:
        return self.wins / self.trades if self.trades else 0.0

    def summary(self) -> str:
        return (
            f"trades={self.trades} win_rate={self.win_rate:.0%} "
            f"final_equity={self.final_equity:,.0f} max_dd={self.max_drawdown:.1%}"
        )


def run_backtest(
    data: dict[str, pd.DataFrame],
    instruments: dict[str, Instrument],
    config: BotConfig | None = None,
) -> BacktestResult:
    config = config or BotConfig()
    config.journal_path = None  # don't write the live journal from a backtest
    broker = PaperBroker(equity=config.risk.starting_equity, journal_path=None)
    engine = Engine(config=config, instruments=instruments, broker=broker)

    clock = sorted(set().union(*[df.index for df in data.values()]))
    equity_points: dict[pd.Timestamp, float] = {}

    for ts in clock:
        window = {
            sym: df.loc[:ts]
            for sym, df in data.items()
            if ts in df.index  # only instruments whose bar just closed
        }
        if not window:
            continue
        engine.step(window, ts.to_pydatetime())
        last_prices = {sym: float(df.loc[:ts, "close"].iloc[-1]) for sym, df in data.items()
                       if not df.loc[:ts].empty}
        equity_points[ts] = broker.mark_to_market(last_prices)

    curve = pd.Series(equity_points).sort_index()
    peak = curve.cummax()
    max_dd = float(((peak - curve) / peak).max()) if len(curve) else 0.0
    wins = sum(1 for t in broker.closed_trades if t.pnl > 0)
    return BacktestResult(
        equity_curve=curve,
        trades=len(broker.closed_trades),
        wins=wins,
        final_equity=broker.equity,
        max_drawdown=max_dd,
    )
