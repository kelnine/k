"""Strategies used by tests. Not registered globally: tests build definitions explicitly.

Kept in an importable module so the subprocess host can import them in its child process.
"""

import os
from decimal import Decimal

from pydantic import Field

from kterminal.domain.market import Bar
from kterminal.strategy_engine import SignalOutput, Strategy, StrategyMeta, StrategyParams


class ScriptParams(StrategyParams):
    long_on: tuple[int, ...] = ()
    short_on: tuple[int, ...] = ()
    exit_long_on: tuple[int, ...] = ()
    move_sl_on: tuple[int, ...] = ()
    stop_distance: Decimal = Decimal(5)
    target_distance: Decimal = Decimal(10)


class Scripted(Strategy[ScriptParams]):
    """Emits signals on given bar numbers (1-based count of evaluated bars)."""

    meta = StrategyMeta(id="scripted", name="Scripted", version="1.0.0", warmup_bars=0)
    Params = ScriptParams

    def on_start(self) -> None:
        self.count = 0

    def on_bar(self, bar: Bar) -> SignalOutput:
        self.count += 1
        p = self.params
        close = bar.close
        if self.count in p.long_on:
            return self.ctx.long(
                stop_loss=close - p.stop_distance, take_profit=close + p.target_distance
            )
        if self.count in p.short_on:
            return self.ctx.short(
                stop_loss=close + p.stop_distance, take_profit=close - p.target_distance
            )
        if self.count in p.exit_long_on:
            return self.ctx.exit_long(reason="scripted")
        if self.count in p.move_sl_on and self.ctx.position is not None:
            return self.ctx.move_sl(self.ctx.position.entry_price)
        return None


class SmaParams(StrategyParams):
    fast: int = Field(5, ge=2)
    slow: int = Field(20, ge=3)
    stop_atr: Decimal = Decimal("1.5")


class SmaCross(Strategy[SmaParams]):
    meta = StrategyMeta(
        id="sma_cross_test",
        name="SMA cross (test)",
        version="1.0.0",
        timeframes=("5m",),
        warmup_bars=30,
    )
    Params = SmaParams

    def on_bar(self, bar: Bar) -> SignalOutput:
        close = self.ctx.bars.close
        p = self.params
        if len(close) < p.slow + 1:
            return None
        fast_now, slow_now = close[-p.fast :].mean(), close[-p.slow :].mean()
        fast_prev, slow_prev = close[-p.fast - 1 : -1].mean(), close[-p.slow - 1 : -1].mean()
        rng = float((self.ctx.bars.high[-14:] - self.ctx.bars.low[-14:]).mean())
        stop = Decimal(repr(round(rng * float(p.stop_atr), 2))) or Decimal("0.5")
        if fast_prev <= slow_prev and fast_now > slow_now:
            return self.ctx.long(stop_loss=bar.close - stop, take_profit=bar.close + 2 * stop)
        if fast_prev >= slow_prev and fast_now < slow_now:
            return self.ctx.short(stop_loss=bar.close + stop, take_profit=bar.close - 2 * stop)
        return None


class CrashParams(StrategyParams):
    crash_on: int = 3
    mode: str = "raise"  # raise | exit | hang


class Crasher(Strategy[CrashParams]):
    meta = StrategyMeta(id="crasher", name="Crasher", version="1.0.0", warmup_bars=0)
    Params = CrashParams

    def on_start(self) -> None:
        self.count = 0

    def on_bar(self, bar: Bar) -> SignalOutput:
        self.count += 1
        if self.count == self.params.crash_on:
            if self.params.mode == "exit":
                os._exit(17)  # simulates a hard crash (segfault, OOM kill)
            if self.params.mode == "hang":
                while True:  # simulates an infinite loop
                    pass
            raise ZeroDivisionError("strategy bug")
        return self.ctx.long(stop_loss=bar.close - 5) if self.count == 1 else None


class Misbehaving(Strategy[CrashParams]):
    """Returns things that are not valid signals."""

    meta = StrategyMeta(id="misbehaving", name="Misbehaving", version="1.0.0", warmup_bars=0)
    Params = CrashParams

    def on_bar(self, bar: Bar) -> SignalOutput:
        good = self.ctx.long(stop_loss=bar.close - 5)
        wrong_identity = good.model_copy(update={"strategy_id": "someone_else"})
        wrong_side = good.model_copy(update={"stop_loss": bar.close + 5})
        return [good, wrong_identity, wrong_side, "not a signal"]  # type: ignore[list-item]


class ContextProbe(Strategy[ScriptParams]):
    """Records what it can see on context timeframes (look-ahead checks)."""

    meta = StrategyMeta(
        id="context_probe",
        name="Context probe",
        version="1.0.0",
        context_timeframes=("1h",),
        warmup_bars=0,
    )
    Params = ScriptParams

    def on_start(self) -> None:
        self.seen: list[tuple[str, int, str | None]] = []

    def on_bar(self, bar: Bar) -> SignalOutput:
        hourly = self.ctx.series("1h")
        latest = hourly.latest
        self.seen.append(
            (
                bar.close_time.isoformat(),
                len(hourly),
                latest.close_time.isoformat() if latest else None,
            )
        )
        if latest is not None and latest.close_time > bar.close_time:
            raise AssertionError("look-ahead: saw an hourly bar that has not closed")
        return None
