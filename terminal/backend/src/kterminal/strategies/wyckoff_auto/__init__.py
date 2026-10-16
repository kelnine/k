"""S12 · Wyckoff Auto entry — port of script 6, "Wyckoff [theUltimator5]" (doc 13).

``wyckoff_engine.py`` is the script's chart-timeframe campaign engine (``f_engine``),
``state.py`` its ``WS`` campaign type, ``measures.py`` the per-bar series it reads and
``thresholds.py`` its fixed settings; ``strategy.py`` turns the Auto entry and the
campaign's structure events into signals.
"""

from kterminal.strategies.wyckoff_auto.measures import BarMeasures, Measures
from kterminal.strategies.wyckoff_auto.state import WS, PivotTriplet
from kterminal.strategies.wyckoff_auto.strategy import WyckoffAuto, WyckoffAutoParams
from kterminal.strategies.wyckoff_auto.wyckoff_engine import (
    CampaignEnd,
    EngineStep,
    EntryCheck,
    WyckoffEngine,
)

__all__ = [
    "WS",
    "BarMeasures",
    "CampaignEnd",
    "EngineStep",
    "EntryCheck",
    "Measures",
    "PivotTriplet",
    "WyckoffAuto",
    "WyckoffAutoParams",
    "WyckoffEngine",
]
