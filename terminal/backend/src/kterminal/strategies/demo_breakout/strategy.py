"""DEMO ONLY — channel breakout with an optional higher-timeframe trend filter.

Long when the close breaks above the highest high of the previous
``channel_bars`` bars, short below the lowest low. With ``trend_filter`` on,
longs require the last *closed* 1h bar's close above its ``trend_sma``-bar
SMA (shorts below) — a minimal example of multi-timeframe context without
look-ahead. Stop at the channel midpoint, target at ``reward_risk`` × risk.
"""

from decimal import Decimal

from pydantic import Field

from kterminal.domain.market import Bar
from kterminal.strategy_engine import (
    SignalOutput,
    Strategy,
    StrategyMeta,
    StrategyParams,
    register_strategy,
)


class BreakoutParams(StrategyParams):
    channel_bars: int = Field(20, ge=3, le=1_000)
    trend_filter: bool = True
    trend_sma: int = Field(10, ge=2, le=500)
    reward_risk: Decimal = Field(Decimal("1.5"), gt=0)


@register_strategy
class DemoBreakout(Strategy[BreakoutParams]):
    meta = StrategyMeta(
        id="demo_breakout",
        name="Demo · Channel breakout (1h trend filter)",
        version="1.0.0",
        description="Demonstration strategy for the lab (not a trading idea).",
        context_timeframes=("1h",),
        warmup_bars=40,
        tags=("demo",),
    )
    Params = BreakoutParams

    def on_bar(self, bar: Bar) -> SignalOutput:
        p = self.params
        bars = self.ctx.bars
        if len(bars) < p.channel_bars + 1 or self.ctx.position is not None:
            return None
        high = float(bars.high[-p.channel_bars - 1 : -1].max())
        low = float(bars.low[-p.channel_bars - 1 : -1].min())
        close = float(bar.close)
        trend = self._trend()
        if p.trend_filter and trend is None:
            return None
        mid = Decimal(repr((high + low) / 2))
        if close > high and (not p.trend_filter or trend == 1):
            risk = bar.close - mid
            return self.ctx.long(
                stop_loss=mid,
                take_profit=bar.close + risk * p.reward_risk,
                metadata={"channel_high": high, "trend": trend},
            )
        if close < low and (not p.trend_filter or trend == -1):
            risk = mid - bar.close
            return self.ctx.short(
                stop_loss=mid,
                take_profit=bar.close - risk * p.reward_risk,
                metadata={"channel_low": low, "trend": trend},
            )
        return None

    def _trend(self) -> int | None:
        hourly = self.ctx.series("1h")
        if len(hourly) < self.params.trend_sma:
            return None
        closes = hourly.close
        return 1 if closes[-1] > closes[-self.params.trend_sma :].mean() else -1
