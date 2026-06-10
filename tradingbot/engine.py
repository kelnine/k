"""Orchestrator: for each instrument, run its strategy on the latest data,
pass entries through the risk engine and correlation filter, and execute
on the broker. One `step()` call = one evaluation of the whole book.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from .broker import PaperBroker
from .config import INSTRUMENTS, BotConfig, Instrument
from .indicators import atr
from .risk import correlation_filter_allows, plan_position
from .strategies import STRATEGY_REGISTRY, Strategy
from .strategies.base import FLAT


class Engine:
    def __init__(self, config: BotConfig | None = None,
                 instruments: dict[str, Instrument] | None = None,
                 broker: PaperBroker | None = None):
        self.config = config or BotConfig()
        self.instruments = instruments or INSTRUMENTS
        self.broker = broker or PaperBroker(
            equity=self.config.risk.starting_equity,
            journal_path=self.config.journal_path,
        )
        self.strategies: dict[str, Strategy] = {
            sym: STRATEGY_REGISTRY[inst.strategy]()
            for sym, inst in self.instruments.items()
        }
        self.log: list[str] = []

    def step(self, data: dict[str, pd.DataFrame], now: datetime) -> None:
        """`data` maps symbol -> OHLCV history ending at the current bar."""
        # 1) Hard stops first — they outrank everything the strategy thinks.
        stopped_now: set[str] = set()
        for sym in list(self.broker.positions):
            df = data.get(sym)
            if df is None or df.empty:
                continue
            bar = df.iloc[-1]
            fill = self.broker.check_stop(sym, bar["high"], bar["low"])
            if fill is not None:
                trade = self.broker.close_position(sym, fill, now, reason="hard stop hit")
                stopped_now.add(sym)
                self._log(now, f"{sym}: STOPPED OUT at {fill:.2f} (pnl {trade.pnl:+.2f})")

        # 2) Strategy exits, then entries gated by risk + correlation filter.
        for sym, inst in self.instruments.items():
            df = data.get(sym)
            if df is None or len(df) == 0:
                continue
            strategy = self.strategies[sym]
            held = self.broker.positions.get(sym)
            current_dir = held.direction if held else FLAT
            sig = strategy.signal(df, current_direction=current_dir)
            price = float(df["close"].iloc[-1])

            if held and sig.direction != held.direction:
                trade = self.broker.close_position(sym, price, now, reason=sig.reason)
                self._log(now, f"{sym}: exit at {price:.2f} (pnl {trade.pnl:+.2f}) — {sig.reason}")
                held = None
                current_dir = FLAT

            if held is None and sig.direction != FLAT:
                if sym in stopped_now:
                    # no whipsaw re-entry on the bar that just stopped us out
                    continue
                if sig.direction < 0 and not inst.allow_short:
                    continue
                open_dirs = {s: p.direction for s, p in self.broker.positions.items()}
                allowed, why = correlation_filter_allows(
                    inst, sig.direction, open_dirs, self.instruments, self.config.risk
                )
                if not allowed:
                    self._log(now, f"{sym}: entry skipped — {why}")
                    continue
                atr_value = float(atr(df, self.config.risk.atr_period).iloc[-1])
                plan = plan_position(self.broker.equity, price, atr_value,
                                     sig.direction, self.config.risk)
                if plan is None:
                    continue
                self.broker.open_position(
                    sym, sig.direction, plan.quantity, price, plan.stop_price,
                    now, reason=sig.reason,
                )
                side = "LONG" if sig.direction > 0 else "SHORT"
                self._log(
                    now,
                    f"{sym}: {side} {plan.quantity:.4f} @ {price:.2f}, "
                    f"stop {plan.stop_price:.2f} (risk {plan.risk_amount:.0f}) — {sig.reason}",
                )

    def _log(self, now: datetime, msg: str) -> None:
        line = f"[{now:%Y-%m-%d %H:%M}] {msg}"
        self.log.append(line)
        print(line)
