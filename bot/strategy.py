"""Signal generation.

Turns a ``MarketSnapshot`` into a ``Signal`` with direction, entry, stop, two
targets, leverage and a confidence score.

The edge (vs. the screenshot's random-looking 37%): when the engine provides
positioning data we trade *against crowded retail and with whales*. Crowded one
sided retail tends to be liquidity for the other side. When positioning is
unavailable (e.g. Binance source) we fall back to a momentum + funding read.

This is a transparent heuristic, not a promise of profit. Tune freely.
"""
from __future__ import annotations

from dataclasses import dataclass

from .datasources import MarketSnapshot


@dataclass
class Signal:
    symbol: str
    side: str  # "LONG" | "SHORT"
    entry: float
    stop_loss: float
    tp1: float
    tp2: float
    confidence: int  # 0..100
    leverage: int
    triggers: list[str]
    strategy: str = "Positioning + Momentum (Confluence)"

    @property
    def rr(self) -> float:
        risk = abs(self.entry - self.stop_loss)
        reward = abs(self.tp2 - self.entry)
        return reward / risk if risk else 0.0


# Per-leg move sizing as a fraction of price. Crypto-perp friendly defaults.
_STOP_PCT = 0.025
_TP1_PCT = 0.035
_TP2_PCT = 0.070


def generate(snap: MarketSnapshot) -> Signal | None:
    """Return a Signal, or None if there's no edge worth posting."""
    score = 0.0  # positive => long, negative => short
    triggers: list[str] = []

    # --- 1. Positioning (the real edge) -----------------------------------
    if snap.has_positioning:
        whale = snap.whale_long_bias
        retail = snap.retail_long_bias
        if retail is not None:
            # Fade extreme retail crowding.
            crowd = retail - 0.5
            if abs(crowd) > 0.06:
                score -= crowd * 2.0  # heavy retail long -> short bias
                side = "short" if crowd > 0 else "long"
                triggers.append(f"Retail crowded {('long' if crowd>0 else 'short')} (fade)")
        if whale is not None:
            wb = whale - 0.5
            if abs(wb) > 0.03:
                score += wb * 2.5  # follow whales
                triggers.append(f"Whales net {('long' if wb>0 else 'short')}")

    # --- 2. Momentum -------------------------------------------------------
    chg = snap.change_24h_pct
    if abs(chg) >= 1.0:
        score += max(-1.0, min(1.0, chg / 6.0))
        triggers.append(f"24h momentum {chg:+.1f}%")

    # --- 3. Funding (crowded leverage pays the other side) -----------------
    if snap.funding_pct is not None and abs(snap.funding_pct) > 0.01:
        # Positive funding = longs pay shorts = crowded long -> slight short tilt.
        score -= max(-0.5, min(0.5, snap.funding_pct * 20))
        triggers.append(f"Funding {snap.funding_pct:+.3f}%")

    if abs(score) < 0.12 or not triggers:
        return None  # no conviction, no post

    side = "LONG" if score > 0 else "SHORT"
    price = snap.price

    if side == "LONG":
        stop = price * (1 - _STOP_PCT)
        tp1 = price * (1 + _TP1_PCT)
        tp2 = price * (1 + _TP2_PCT)
    else:
        stop = price * (1 + _STOP_PCT)
        tp1 = price * (1 - _TP1_PCT)
        tp2 = price * (1 - _TP2_PCT)

    # Confidence: map |score| (~0..3) to ~45..90, capped.
    confidence = int(min(90, 45 + abs(score) * 15))
    leverage = 10 if confidence >= 70 else 5

    return Signal(
        symbol=snap.symbol,
        side=side,
        entry=round(price, _round_dp(price)),
        stop_loss=round(stop, _round_dp(price)),
        tp1=round(tp1, _round_dp(price)),
        tp2=round(tp2, _round_dp(price)),
        confidence=confidence,
        leverage=leverage,
        triggers=triggers[:3],
    )


def _round_dp(price: float) -> int:
    if price >= 1000:
        return 1
    if price >= 1:
        return 2
    if price >= 0.01:
        return 4
    return 6
