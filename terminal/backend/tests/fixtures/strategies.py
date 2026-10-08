"""Strategies used by tests. Not registered globally: tests build definitions explicitly.

Kept in an importable module so the subprocess host can import them in its child process.
"""

import decimal
import os
import time
from dataclasses import dataclass, field
from decimal import Decimal

import numpy as np
from pydantic import Field

from kterminal.core.enums import OrderType
from kterminal.domain.market import Bar
from kterminal.strategy_engine import SignalOutput, Strategy, StrategyMeta, StrategyParams
from kterminal.strategy_engine.base import NoParams


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
    mode: str = "raise"  # raise | exit | hang | sysexit | sleep
    sleep_s: float = 0.0


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
            if self.params.mode == "sysexit":
                raise SystemExit("strategy called sys.exit")
            if self.params.mode == "sleep":
                time.sleep(self.params.sleep_s)  # a slow (not crashed) strategy
                return None
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


class SabotageParams(StrategyParams):
    mode: str = "float_stop"


class Saboteur(Strategy[SabotageParams]):
    """Bends the rules in the ways a careless (or hostile) strategy might."""

    meta = StrategyMeta(id="saboteur", name="Saboteur", version="1.0.0", warmup_bars=0)
    Params = SabotageParams

    def on_bar(self, bar: Bar) -> SignalOutput:
        good = self.ctx.long(stop_loss=bar.close - 5)
        mode = self.params.mode
        if mode == "float_stop":  # model_copy skips validation: a float sneaks in
            return good.model_copy(update={"stop_loss": float(bar.close) - 5.0})
        if mode == "nan_meta":
            return good.model_copy(update={"metadata": {"atr": float("nan")}})
        if mode == "numpy_meta":
            return good.model_copy(update={"metadata": {"idx": np.int64(7)}})
        if mode == "spoof_time":
            return good.model_copy(update={"timestamp": bar.close_time.replace(year=2030)})
        if mode == "flood":
            return [good] * 1_000
        if mode == "nul_meta":  # PostgreSQL text/jsonb cannot hold NUL
            return good.model_copy(update={"metadata": {"note": "a\x00b"}})
        if mode == "tiny_risk":  # rounds to 0 at the 4 decimals risk is stored with
            return self.ctx.long(stop_loss=bar.close - 5, risk=Decimal("0.00004"))
        if mode == "huge_target":  # beyond numeric(24,10)
            return self.ctx.long(stop_loss=bar.close - 5, take_profit=Decimal("1e14"))
        if mode == "reasoned":
            if self.ctx.bars.close.size % 2:
                return self.ctx.no_trade("filtered by news window", persist=True)
            return self.ctx.long(
                stop_loss=bar.close - 5,
                entry=bar.close - 1,
                order_type=OrderType.LIMIT,
                expires_after_bars=3,
                reason="pullback entry",
            )
        if mode == "decimal":
            decimal.getcontext().prec = 4  # would break everyone's money maths if it leaked
            decimal.getcontext().rounding = decimal.ROUND_DOWN
            return good
        return None


@dataclass(frozen=True)
class _Memory:
    closes: list[Decimal] = field(default_factory=list)


class SharedViaFrozenDataclass(Strategy[NoParams]):
    meta = StrategyMeta(id="shared_dataclass", name="Shared", version="1.0.0")
    Params = NoParams
    MEMORY = _Memory()

    def on_bar(self, bar: Bar) -> SignalOutput:
        self.MEMORY.closes.append(bar.close)
        return None


class SharedViaTuple(Strategy[NoParams]):
    meta = StrategyMeta(id="shared_tuple", name="Shared", version="1.0.0")
    Params = NoParams
    SEEN = ([],)

    def on_bar(self, bar: Bar) -> SignalOutput:
        return None


class SharedViaNestedClass(Strategy[NoParams]):
    meta = StrategyMeta(id="shared_nested", name="Shared", version="1.0.0")
    Params = NoParams

    class Cache:
        hits: dict[str, int] = {}  # noqa: RUF012 - deliberately mutable (test subject)

    def on_bar(self, bar: Bar) -> SignalOutput:
        return None


class SharedViaDefaultArgument(Strategy[NoParams]):
    meta = StrategyMeta(id="shared_default", name="Shared", version="1.0.0")
    Params = NoParams

    def on_bar(self, bar: Bar, seen: list[Decimal] = []) -> SignalOutput:  # noqa: B006
        seen.append(bar.close)
        return None


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


class SetParamsModel(StrategyParams):
    sessions: frozenset[str] = frozenset(
        {"london_session", "ny_session", "asia_session", "ny_orb_15", "ny_pm", "tokyo"}
    )


class SetParams(Strategy[SetParamsModel]):
    meta = StrategyMeta(id="set_params", name="Set params", version="1.0.0")
    Params = SetParamsModel

    def on_bar(self, bar: Bar) -> SignalOutput:
        return None


class LevelsParams(StrategyParams):
    levels: list[Decimal] = Field(default_factory=lambda: [Decimal(1)])


class LevelHoarder(Strategy[LevelsParams]):
    """Mutates its (shallowly frozen) params — must only ever affect itself."""

    meta = StrategyMeta(id="level_hoarder", name="Level hoarder", version="1.0.0")
    Params = LevelsParams

    def on_bar(self, bar: Bar) -> SignalOutput:
        self.params.levels.append(bar.close)
        return None


class OrbProbe(Strategy[NoParams]):
    meta = StrategyMeta(id="orb_probe", name="ORB probe", version="1.0.0", sessions=("ny_orb_15",))
    Params = NoParams

    def on_bar(self, bar: Bar) -> SignalOutput:
        return None
