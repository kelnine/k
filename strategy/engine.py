"""Strategy engine: combines indicators + market structure into trade signals."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import pandas as pd

from strategy.indicators import Indicators, compute as compute_indicators
from strategy.structure import StructureResult, detect_structure

logger = logging.getLogger(__name__)


@dataclass
class Signal:
    symbol: str
    direction: str          # "long" | "short"
    entry_price: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    atr: float
    confidence: float       # 0.0 – 1.0
    score: int
    reasons: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.utcnow)


class StrategyEngine:
    def __init__(self, config: dict) -> None:
        self.cfg = config
        self.scfg = config.get("strategy", {})

    def analyze(self, symbol: str, df: pd.DataFrame) -> Optional[Signal]:
        """Return a Signal if a high-confidence setup is detected, else None.

        df: OHLCV DataFrame with at minimum 210 bars (EMA-200 warmup).
        """
        min_bars = max(self.scfg.get("ema_periods", [9, 21, 50, 200])[-1] + 10, 210)
        if len(df) < min_bars:
            logger.debug(f"{symbol}: not enough bars ({len(df)} < {min_bars})")
            return None

        ind = compute_indicators(df, self.scfg)
        struct = detect_structure(
            df,
            lookback=self.scfg.get("structure_lookback", 50),
            swing_window=self.scfg.get("swing_window", 5),
        )
        return self._score_and_build(symbol, df, ind, struct)

    # ── private ───────────────────────────────────────────────────────────────

    def _score_and_build(
        self,
        symbol: str,
        df: pd.DataFrame,
        ind: Indicators,
        struct: StructureResult,
    ) -> Optional[Signal]:
        close = float(df["close"].iloc[-1])
        atr = float(ind.atr.iloc[-1])
        rsi = float(ind.rsi.iloc[-1])
        adx = float(ind.adx.iloc[-1])
        vol_ratio = float(ind.volume_ratio.iloc[-1]) if not pd.isna(ind.volume_ratio.iloc[-1]) else 1.0

        e9 = float(ind.ema_9.iloc[-1])
        e21 = float(ind.ema_21.iloc[-1])
        e50 = float(ind.ema_50.iloc[-1])
        e200 = float(ind.ema_200.iloc[-1])
        di_plus = float(ind.di_plus.iloc[-1])
        di_minus = float(ind.di_minus.iloc[-1])

        rsi_ob = self.scfg.get("rsi_overbought", 70)
        rsi_os = self.scfg.get("rsi_oversold", 30)
        adx_min = self.scfg.get("adx_threshold", 25)
        vol_spike = self.scfg.get("volume_spike_multiplier", 2.0)
        min_score = self.scfg.get("min_signal_score", 4)

        long_score = 0
        short_score = 0
        reasons: list[str] = []

        # ── EMA alignment ────────────────────────────────────────────────────
        if e9 > e21 > e50 > e200:
            long_score += 2
            reasons.append("Full bullish EMA stack (9>21>50>200)")
        elif e9 < e21 < e50 < e200:
            short_score += 2
            reasons.append("Full bearish EMA stack (9<21<50<200)")
        elif e9 > e21 and close > e50:
            long_score += 1
            reasons.append("Short-term EMA bullish + above EMA50")
        elif e9 < e21 and close < e50:
            short_score += 1
            reasons.append("Short-term EMA bearish + below EMA50")

        # Price vs EMA200 bias
        if close > e200:
            long_score += 1
        else:
            short_score += 1

        # ── RSI ──────────────────────────────────────────────────────────────
        if rsi < rsi_os:
            long_score += 2
            reasons.append(f"RSI oversold ({rsi:.1f})")
        elif rsi_os < rsi < 50:
            long_score += 1
            reasons.append(f"RSI recovering ({rsi:.1f})")
        elif rsi > rsi_ob:
            short_score += 2
            reasons.append(f"RSI overbought ({rsi:.1f})")
        elif 50 < rsi < rsi_ob:
            short_score += 1
            reasons.append(f"RSI extended ({rsi:.1f})")

        # ── ADX ──────────────────────────────────────────────────────────────
        if adx > adx_min:
            if di_plus > di_minus:
                long_score += 1
                reasons.append(f"ADX bullish trend ({adx:.1f})")
            else:
                short_score += 1
                reasons.append(f"ADX bearish trend ({adx:.1f})")
        # Low ADX = ranging market → reduce both scores
        elif adx < 15:
            long_score = max(0, long_score - 1)
            short_score = max(0, short_score - 1)

        # ── Volume spike ─────────────────────────────────────────────────────
        if vol_ratio > vol_spike:
            reasons.append(f"Volume spike ({vol_ratio:.1f}× avg)")
            if long_score >= short_score:
                long_score += 1
            else:
                short_score += 1

        # ── Market structure ─────────────────────────────────────────────────
        if struct.bos_bullish:
            long_score += 2
            reasons.append("Bullish BOS (break of structure)")
        if struct.choch_bullish:
            long_score += 3
            reasons.append("Bullish CHoCH (trend change)")
        if struct.bos_bearish:
            short_score += 2
            reasons.append("Bearish BOS (break of structure)")
        if struct.choch_bearish:
            short_score += 3
            reasons.append("Bearish CHoCH (trend change)")

        # ── Liquidity sweeps → anticipatory reversal entries ─────────────────
        if struct.liquidity_sweep_low:
            long_score += 2
            reasons.append("Liquidity sweep below lows → reversal setup")
        if struct.liquidity_sweep_high:
            short_score += 2
            reasons.append("Liquidity sweep above highs → reversal setup")

        # ── Order block confluence ────────────────────────────────────────────
        for ob in struct.order_blocks:
            if ob.mitigated:
                continue
            tolerance = atr * 0.5
            if ob.direction == "bullish" and ob.low - tolerance <= close <= ob.high + tolerance:
                long_score += 2
                reasons.append(f"Bullish OB ({ob.low:.4f}–{ob.high:.4f})")
                break
            if ob.direction == "bearish" and ob.low - tolerance <= close <= ob.high + tolerance:
                short_score += 2
                reasons.append(f"Bearish OB ({ob.low:.4f}–{ob.high:.4f})")
                break

        # ── FVG confluence ────────────────────────────────────────────────────
        for fvg in struct.fvgs:
            if fvg.filled:
                continue
            if fvg.direction == "bullish" and fvg.bottom <= close <= fvg.top:
                long_score += 1
                reasons.append(f"Inside bullish FVG ({fvg.bottom:.4f}–{fvg.top:.4f})")
                break
            if fvg.direction == "bearish" and fvg.bottom <= close <= fvg.top:
                short_score += 1
                reasons.append(f"Inside bearish FVG ({fvg.bottom:.4f}–{fvg.top:.4f})")
                break

        # ── Decision ─────────────────────────────────────────────────────────
        sl_mult = self.scfg.get("sl_atr_multiplier", 1.5)
        tp1_mult = self.scfg.get("tp1_atr_multiplier", 2.0)
        tp2_mult = self.scfg.get("tp2_atr_multiplier", 3.5)

        if long_score >= min_score and long_score > short_score:
            return Signal(
                symbol=symbol,
                direction="long",
                entry_price=close,
                stop_loss=close - atr * sl_mult,
                take_profit_1=close + atr * tp1_mult,
                take_profit_2=close + atr * tp2_mult,
                atr=atr,
                confidence=min(long_score / 12.0, 1.0),
                score=long_score,
                reasons=reasons,
            )

        if short_score >= min_score and short_score > long_score:
            return Signal(
                symbol=symbol,
                direction="short",
                entry_price=close,
                stop_loss=close + atr * sl_mult,
                take_profit_1=close - atr * tp1_mult,
                take_profit_2=close - atr * tp2_mult,
                atr=atr,
                confidence=min(short_score / 12.0, 1.0),
                score=short_score,
                reasons=reasons,
            )

        logger.debug(
            f"{symbol}: no signal (long={long_score}, short={short_score}, min={min_score})"
        )
        return None
