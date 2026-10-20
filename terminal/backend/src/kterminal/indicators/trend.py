"""Trend: ``ta.dmi`` (DI+/DI−/ADX), ``ta.sar`` and ``ta.supertrend``.

All three follow the reference implementations in TradingView's Pine v5/v6
reference manual (``pine_dmi``, ``pine_sar``, ``pine_supertrend``) line by
line, including their behaviour on the first bars, so a port reproduces the
built-in from the same start of history.
"""

import math
from typing import NamedTuple

from kterminal.indicators._validate import check_float, check_int
from kterminal.indicators.averages import Rma
from kterminal.indicators.pine import FixNan, div, eq, gt, na, nz
from kterminal.indicators.volatility import Atr, TrueRange

__all__ = ["Dmi", "DmiValue", "Sar", "SuperTrend", "SuperTrendValue"]


class DmiValue(NamedTuple):
    plus: float  # DI+
    minus: float  # DI−
    adx: float


class Dmi:
    """Pine ``ta.dmi(diLength, adxSmoothing)`` → ``(DI+, DI−, ADX)``::

        up      = ta.change(high)
        down    = -ta.change(low)
        plusDM  = na(up)   ? na : (up > down and up > 0 ? up : 0)
        minusDM = na(down) ? na : (down > up and down > 0 ? down : 0)
        trur    = ta.rma(ta.tr, diLength)
        plus    = fixnan(100 * ta.rma(plusDM, diLength) / trur)
        minus   = fixnan(100 * ta.rma(minusDM, diLength) / trur)
        sum     = plus + minus
        adx     = 100 * ta.rma(math.abs(plus - minus) / (sum == 0 ? 1 : sum), adxSmoothing)

    The true range is ``ta.tr`` **without** na handling (na on the first
    bar), so ``trur`` differs from ``ta.atr(diLength)``: the first DI values
    are on bar index ``diLength``, the first ADX ``adxSmoothing - 1`` bars
    later. The directional-movement comparisons use Pine's 1e-10 tolerance
    (a bar whose high and low moved by the same tick amount has no
    directional movement even if the float differences disagree in the 17th
    digit). A zero ``trur`` (a perfectly flat start) gives na, which
    ``fixnan`` replaces with the previous DI.
    """

    __slots__ = (
        "_adx",
        "_fix_minus",
        "_fix_plus",
        "_minus",
        "_plus",
        "_previous_high",
        "_previous_low",
        "_true_range",
        "_true_range_rma",
        "value",
    )

    def __init__(self, di_length: int = 14, adx_smoothing: int = 14) -> None:
        check_int("di_length", di_length, 1)
        check_int("adx_smoothing", adx_smoothing, 1)
        self._true_range = TrueRange(handle_na=False)
        self._true_range_rma = Rma(di_length)
        self._plus = Rma(di_length)
        self._minus = Rma(di_length)
        self._adx = Rma(adx_smoothing)
        self._fix_plus = FixNan()
        self._fix_minus = FixNan()
        self._previous_high = math.nan
        self._previous_low = math.nan
        self.value = DmiValue(math.nan, math.nan, math.nan)

    def update(self, high: float, low: float, close: float) -> DmiValue:
        up = high - self._previous_high
        down = -(low - self._previous_low)
        self._previous_high, self._previous_low = high, low
        plus_dm = math.nan if na(up) else (up if gt(up, down) and gt(up, 0.0) else 0.0)
        minus_dm = math.nan if na(down) else (down if gt(down, up) and gt(down, 0.0) else 0.0)
        true_range = self._true_range_rma.update(self._true_range.update(high, low, close))
        plus = self._fix_plus.update(100.0 * div(self._plus.update(plus_dm), true_range))
        minus = self._fix_minus.update(100.0 * div(self._minus.update(minus_dm), true_range))
        total = plus + minus
        adx = 100.0 * self._adx.update(abs(plus - minus) / (1.0 if eq(total, 0.0) else total))
        self.value = DmiValue(plus, minus, adx)
        return self.value


class Sar:
    """Pine ``ta.sar(start, inc, max)``: Wilder's Parabolic SAR, as TradingView's ``pine_sar``.

    * Bar 0: na.
    * Bar 1 (initialisation): if ``close > close[1]`` the trend starts long
      (SAR = ``low[1]``, extreme point = ``high``), otherwise short (SAR =
      ``high[1]``, EP = ``low``); acceleration = ``start``. The projection
      and reversal test below then run on bar 1 too.
    * Every bar: the *projected* SAR ``sar + af * (ep - sar)`` is tested
      **before** it is clamped. Long: a reversal happens when the projection
      is strictly above ``low``; the new SAR is ``max(high, ep)``, the new EP
      ``low``, af resets to ``start``. Short mirrors it (projection strictly
      below ``high``). TA-Lib and most libraries clamp first and flip on
      different bars.
    * On a bar that is not a reversal (or initialisation), a new extreme
      (``high > ep`` long, ``low < ep`` short) moves the EP and raises
      af by ``inc``, capped at ``max``.
    * Finally the SAR is clamped: long — not above ``low[1]`` and (from bar 2)
      ``low[2]``; short — not below ``high[1]``/``high[2]``.

    The path until the first reversal depends on where history starts; warm
    up well before comparing with TradingView. A bar with a na input returns
    na and is skipped. :meth:`projected` gives the unclamped projection for
    the *next* bar — the level whose touch flips TradingView's SAR, which a
    trailing-stop variant uses.
    """

    __slots__ = (
        "_acceleration",
        "_bar",
        "_extreme",
        "_high1",
        "_high2",
        "_is_long",
        "_low1",
        "_low2",
        "_previous_close",
        "_sar",
        "increment",
        "maximum",
        "start",
        "value",
    )

    def __init__(self, start: float = 0.02, increment: float = 0.02, maximum: float = 0.2) -> None:
        self.start = check_float("start", start)
        self.increment = check_float("increment", increment)
        self.maximum = check_float("maximum", maximum)
        self._bar = -1
        self._is_long = False
        self._extreme = math.nan
        self._acceleration = math.nan
        self._high1 = self._high2 = self._low1 = self._low2 = math.nan
        self._previous_close = math.nan
        self._sar = math.nan
        self.value = math.nan

    @property
    def is_long(self) -> bool | None:
        """True while the SAR is below price (uptrend); None before bar 1."""
        return self._is_long if self._bar >= 1 else None

    @property
    def acceleration(self) -> float:
        return self._acceleration

    @property
    def extreme_point(self) -> float:
        return self._extreme

    def projected(self) -> float:
        """The unclamped SAR the next bar's reversal test will use."""
        return self._sar + self._acceleration * (self._extreme - self._sar)

    def update(self, high: float, low: float, close: float) -> float:
        if na(high) or na(low) or na(close):
            self.value = math.nan
            return self.value
        self._bar += 1
        if self._bar > 0:
            self._sar = self._step(high, low, close)
        self._high2, self._high1 = self._high1, high
        self._low2, self._low1 = self._low1, low
        self._previous_close = close
        self.value = self._sar
        return self.value

    def _step(self, high: float, low: float, close: float) -> float:
        first_trend_bar = False
        sar = self._sar
        if self._bar == 1:
            if close > self._previous_close:
                self._is_long, self._extreme, sar = True, high, self._low1
            else:
                self._is_long, self._extreme, sar = False, low, self._high1
            first_trend_bar = True
            self._acceleration = self.start
        sar = sar + self._acceleration * (self._extreme - sar)
        if self._is_long:
            if sar > low:
                first_trend_bar = True
                self._is_long = False
                sar = max(high, self._extreme)
                self._extreme = low
                self._acceleration = self.start
        elif sar < high:
            first_trend_bar = True
            self._is_long = True
            sar = min(low, self._extreme)
            self._extreme = high
            self._acceleration = self.start
        if not first_trend_bar:
            if self._is_long:
                if high > self._extreme:
                    self._extreme = high
                    self._acceleration = min(self._acceleration + self.increment, self.maximum)
            elif low < self._extreme:
                self._extreme = low
                self._acceleration = min(self._acceleration + self.increment, self.maximum)
        if self._is_long:
            sar = min(sar, self._low1)
            if self._bar > 1:
                sar = min(sar, self._low2)
        else:
            sar = max(sar, self._high1)
            if self._bar > 1:
                sar = max(sar, self._high2)
        return sar


class SuperTrendValue(NamedTuple):
    supertrend: float
    direction: int  # -1: up trend (line below price), 1: down trend (line above price)


class SuperTrend:
    """Pine ``ta.supertrend(factor, atrPeriod)`` → ``(supertrend, direction)``.

    TradingView's reference ``pine_supertrend``, with ``lo``/``up`` for the
    lower/upper band::

        src = hl2,  atr = ta.atr(atrPeriod)
        up = src + factor * atr,  lo = src - factor * atr
        prevLo = nz(lo[1]),  prevUp = nz(up[1])
        lo := lo > prevLo or close[1] < prevLo ? lo : prevLo
        up := up < prevUp or close[1] > prevUp ? up : prevUp
        if na(atr[1])                   direction := 1
        else if superTrend[1] == prevUp  direction := close > up ? -1 : 1
        else                            direction := close < lo ? 1 : -1
        superTrend := direction == -1 ? lo : up

    Direction **-1 is an up trend** (line = lower band, below price) and 1 a
    down trend; a BUY flip is ``direction`` going 1 → -1. The flip test
    compares ``close`` with the *current* bar's ratcheted band, and the trend
    state is the exact float equality ``superTrend[1] == upperBand[1]``.
    Warm-up quirks reproduced: ``nz(prev band)`` is 0 on the first bar, so
    bar 0 returns ``(0.0, 1)``; then the line is na until the ATR exists
    (bar ``atrPeriod - 1``, direction 1); the direction is forced to 1 while
    ``atr[1]`` is na. :attr:`atr` holds the ATR of the last bar (stops built
    on "the line ± 1 ATR" use it).
    """

    __slots__ = (
        "_atr",
        "_previous_atr",
        "_previous_close",
        "_previous_lower",
        "_previous_supertrend",
        "_previous_upper",
        "atr",
        "factor",
        "value",
    )

    def __init__(self, factor: float = 3.0, atr_period: int = 10) -> None:
        self.factor = check_float("factor", factor)
        self._atr = Atr(atr_period)
        self.atr = math.nan
        self._previous_atr = math.nan
        self._previous_close = math.nan
        self._previous_lower = math.nan
        self._previous_upper = math.nan
        self._previous_supertrend = math.nan
        self.value = SuperTrendValue(math.nan, 1)

    def update(self, high: float, low: float, close: float) -> SuperTrendValue:
        atr = self._atr.update(high, low, close)
        source = (high + low) / 2.0
        upper = source + self.factor * atr
        lower = source - self.factor * atr
        previous_lower = nz(self._previous_lower)
        previous_upper = nz(self._previous_upper)
        previous_close = self._previous_close
        if not (lower > previous_lower or previous_close < previous_lower):
            lower = previous_lower
        if not (upper < previous_upper or previous_close > previous_upper):
            upper = previous_upper
        if na(self._previous_atr):
            direction = 1
        elif self._previous_supertrend == previous_upper:
            direction = -1 if close > upper else 1
        else:
            direction = 1 if close < lower else -1
        supertrend = lower if direction == -1 else upper
        self._previous_atr = atr
        self._previous_close = close
        self._previous_lower = lower
        self._previous_upper = upper
        self._previous_supertrend = supertrend
        self.atr = atr
        self.value = SuperTrendValue(supertrend, direction)
        return self.value
