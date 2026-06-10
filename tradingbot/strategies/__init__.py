from .base import FLAT, LONG, SHORT, Signal, Strategy
from .mean_reversion import MeanReversion
from .momentum_breakout import MomentumBreakout
from .trend_following import TrendFollowing

STRATEGY_REGISTRY: dict[str, type[Strategy]] = {
    "mean_reversion": MeanReversion,
    "momentum_breakout": MomentumBreakout,
    "trend_following": TrendFollowing,
}

__all__ = [
    "FLAT",
    "LONG",
    "SHORT",
    "Signal",
    "Strategy",
    "MeanReversion",
    "MomentumBreakout",
    "TrendFollowing",
    "STRATEGY_REGISTRY",
]
