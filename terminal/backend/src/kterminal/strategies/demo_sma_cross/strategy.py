"""DEMO ONLY — a deliberately simple SMA crossover used to exercise the lab.

Long when the fast SMA crosses above the slow SMA, short on the opposite
cross. Stop = ``stop_range_mult`` × the average bar range of the last
``range_bars`` bars; target = ``reward_risk`` × the stop distance. It exists
to demonstrate isolation and the signal → account pipeline, not to make money.
"""

from decimal import Decimal

from pydantic import Field, model_validator

from kterminal.domain.market import Bar
from kterminal.strategy_engine import (
    SignalOutput,
    Strategy,
    StrategyMeta,
    StrategyParams,
    register_strategy,
)


class SmaCrossParams(StrategyParams):
    fast: int = Field(9, ge=2, le=500)
    slow: int = Field(21, ge=3, le=1_000)
    range_bars: int = Field(14, ge=2, le=500)
    stop_range_mult: Decimal = Field(Decimal("1.5"), gt=0)
    reward_risk: Decimal = Field(Decimal("2"), gt=0)

    @model_validator(mode="after")
    def _fast_below_slow(self) -> "SmaCrossParams":
        if self.fast >= self.slow:
            raise ValueError("fast must be shorter than slow")
        return self


@register_strategy
class DemoSmaCross(Strategy[SmaCrossParams]):
    meta = StrategyMeta(
        id="demo_sma_cross",
        name="Demo · SMA crossover",
        version="1.0.0",
        description="Demonstration strategy for the lab (not a trading idea).",
        warmup_bars=50,
        tags=("demo",),
    )
    Params = SmaCrossParams

    def on_bar(self, bar: Bar) -> SignalOutput:
        p = self.params
        close = self.ctx.bars.close
        if len(close) < max(p.slow, p.range_bars) + 1:
            return None
        fast_now, slow_now = close[-p.fast :].mean(), close[-p.slow :].mean()
        fast_prev = close[-p.fast - 1 : -1].mean()
        slow_prev = close[-p.slow - 1 : -1].mean()
        bar_range = float(
            (self.ctx.bars.high[-p.range_bars :] - self.ctx.bars.low[-p.range_bars :]).mean()
        )
        stop = Decimal(repr(bar_range)) * p.stop_range_mult
        if stop <= 0:
            return self.ctx.no_trade("zero range")
        meta = {"fast_sma": round(float(fast_now), 5), "slow_sma": round(float(slow_now), 5)}
        if fast_prev <= slow_prev and fast_now > slow_now:
            return self.ctx.long(
                stop_loss=bar.close - stop,
                take_profit=bar.close + stop * p.reward_risk,
                confidence=0.5,
                metadata=meta,
            )
        if fast_prev >= slow_prev and fast_now < slow_now:
            return self.ctx.short(
                stop_loss=bar.close + stop,
                take_profit=bar.close - stop * p.reward_risk,
                confidence=0.5,
                metadata=meta,
            )
        return None
