"""EliteAlgo v32 (replica+) — EMA 8/21 cross with 4-of-7 confluence (doc 13, S1).

Port of ``terminal/pine/received/09_elitealgo_v32_replica.pine`` (spec:
``terminal/pine/specs/09_elitealgo_v32_replica.md``). Every closed bar:

* indicators exactly as the script calls them (L37-45): EMA 8/21/200 of the
  close, RSI 14, ATR 14, ``ta.vwap(hlc3)`` anchored on the instrument's trading
  day (doc 13 D8), DMI 14/14, and the "pulse" histogram
  ``(EMA5 − EMA60) − EMA20(EMA5 − EMA60)``;
* ``bullCnt`` counts seven Pine comparisons (L53) and ``bearCnt = 7 − bullCnt``
  (L54), so ties and na count as bearish;
* LONG on ``ta.crossover(EMA8, EMA21)`` with ``bullCnt >= 4``, close above the
  EMA200 and the cooldown passed (L64); SHORT mirrors it with ``bearCnt`` (L65);
* the 5-bar cooldown is shared by both directions and counts every script
  signal, also one the position rules then ignore (L60, L93);
* stop = signal close ∓ 1.5 × ATR(14), target 2R from the close (L95-98), fixed.

Signals are decided on closed bars (the script's ``waitClose`` default) and
fill at the next open; the README lists every deviation from the script.
"""

from collections.abc import Callable
from datetime import date
from decimal import Decimal

from pydantic import Field, JsonValue

from kterminal.domain.market import Bar
from kterminal.indicators import (
    Atr,
    Crossover,
    Crossunder,
    Dmi,
    Ema,
    Macd,
    Rsi,
    Vwap,
    gt,
    lt,
    na,
    pine_round,
)
from kterminal.strategy_engine import (
    SignalOutput,
    Strategy,
    StrategyMeta,
    StrategyParams,
    register_strategy,
)

N_CHECKS = 7  # nChecks (L52)
CHECK_NAMES = (
    "close_above_ema_trend",
    "ema_fast_above_ema_slow",
    "rsi_above_50",
    "di_plus_above_di_minus",
    "pulse_hist_above_0",
    "close_above_open",
    "close_above_vwap",
)


class EliteAlgoParams(StrategyParams):
    """The script's inputs that change signals (L6-24), Pine defaults and names."""

    fast_len: int = Field(8, ge=1, le=1_000, description="fastLen: fast EMA")
    slow_len: int = Field(21, ge=1, le=1_000, description="slowLen: slow EMA")
    trend_len: int = Field(200, ge=1, le=5_000, description="trndLen: trend EMA")
    rsi_len: int = Field(14, ge=1, le=1_000, description="rsiLen")
    adx_len: int = Field(14, ge=1, le=1_000, description="adxLen: DMI length")
    adx_smoothing: int = Field(14, ge=1, le=1_000, description="adxSm: ADX smoothing")
    atr_len: int = Field(14, ge=1, le=1_000, description="atrLen")
    pulse_fast: int = Field(5, ge=1, le=1_000, description="pF: pulse fast EMA")
    pulse_slow: int = Field(60, ge=1, le=5_000, description="pSl: pulse slow EMA")
    pulse_signal: int = Field(20, ge=1, le=1_000, description="pSig: pulse signal EMA")
    min_confluence: int = Field(4, ge=0, le=N_CHECKS, description="minConfl (0-7)")
    use_trend_filter: bool = Field(True, description="useTrendF: long > EMA, short < EMA")
    cooldown_bars: int = Field(5, ge=0, le=100_000, description="coolBars")
    sl_mult: float = Field(1.5, ge=0.1, le=100, allow_inf_nan=False, description="slMult")
    rr_ratio: float = Field(2.0, ge=0.1, le=100, allow_inf_nan=False, description="rrRatio")


def bull_count(
    *,
    close: float,
    open_: float,
    ema_trend: float,
    ema_fast: float,
    ema_slow: float,
    rsi: float,
    di_plus: float,
    di_minus: float,
    pulse_hist: float,
    vwap: float,
) -> tuple[int, tuple[bool, ...]]:
    """``bullCnt`` (L53) and the seven checks in the script's order. Each is a Pine
    comparison: 1e-10 tolerance, false when either side is na."""
    checks = (
        gt(close, ema_trend),
        gt(ema_fast, ema_slow),
        gt(rsi, 50.0),
        gt(di_plus, di_minus),
        gt(pulse_hist, 0.0),
        gt(close, open_),
        gt(close, vwap),
    )
    return sum(checks), checks


def stars(count: int, min_confluence: int) -> int:
    """``math.max(1, math.min(3, cnt - minConfl + 1))`` (L69, L71)."""
    return max(1, min(3, count - min_confluence + 1))


@register_strategy
class EliteAlgoEmaConfluence(Strategy[EliteAlgoParams]):
    meta = StrategyMeta(
        id="elitealgo_ema_confluence",
        name="EliteAlgo v32 · EMA 8/21 cross, 4-of-7 confluence",
        version="1.0.0",
        description=(
            "Pine port of script 9 (EliteAlgo v32 pulse ai replica+): EMA 8/21 cross with "
            "at least 4 of 7 bullish (bearish) checks, EMA200 trend filter, shared 5-bar "
            "cooldown, stop 1.5 ATR(14), target 2R. Doc 13 S1."
        ),
        warmup_bars=1_000,  # EMA200 and the Wilder RSI/ATR/DMI converge (spec: >= 1000)
        on_opposite_signal="ignore",  # doc 13 D4 for script 9; a 'reverse' instance exists
        skip_entry_beyond_levels=True,  # doc 13 D3: signals are priced at the bar close
        tags=("pine-port", "script-9", "s1"),
    )
    Params = EliteAlgoParams

    def on_start(self) -> None:
        p = self.params
        self._ema_fast = Ema(p.fast_len)  # emaF (L37)
        self._ema_slow = Ema(p.slow_len)  # emaS (L38)
        self._ema_trend = Ema(p.trend_len)  # emaT (L39)
        self._rsi = Rsi(p.rsi_len)  # L40
        self._atr = Atr(p.atr_len)  # L41
        self._vwap = Vwap()  # ta.vwap(hlc3) (L42)
        self._dmi = Dmi(p.adx_len, p.adx_smoothing)  # L43
        self._pulse = Macd(p.pulse_fast, p.pulse_slow, p.pulse_signal)  # pulse, pHist (L44-45)
        self._cross_up = Crossover()  # ta.crossover(emaF, emaS) (L64)
        self._cross_down = Crossunder()  # ta.crossunder(emaF, emaS) (L65)
        self._last_signal_bar: int | None = None  # var int lastSigBar = na (L59)
        self._trading_day: date | None = None  # for timeframe.change("1D")

    def on_bar(self, bar: Bar) -> SignalOutput:
        p = self.params
        ctx = self.ctx
        open_, high, low, close = float(bar.open), float(bar.high), float(bar.low), float(bar.close)

        ema_fast = self._ema_fast.update(close)
        ema_slow = self._ema_slow.update(close)
        ema_trend = self._ema_trend.update(close)
        rsi = self._rsi.update(close)
        atr = self._atr.update(high, low, close)
        hlc3 = (high + low + close) / 3.0
        vwap = self._vwap.update(hlc3, float(bar.volume), self._new_day()).vwap
        dmi = self._dmi.update(high, low, close)
        pulse_hist = self._pulse.update(close).hist

        bull, checks = bull_count(
            close=close,
            open_=open_,
            ema_trend=ema_trend,
            ema_fast=ema_fast,
            ema_slow=ema_slow,
            rsi=rsi,
            di_plus=dmi.plus,
            di_minus=dmi.minus,
            pulse_hist=pulse_hist,
            vwap=vwap,
        )
        bear = N_CHECKS - bull  # ties and na count as bearish (L54)

        bar_index = ctx.bar_index
        last = self._last_signal_bar
        cool_ok = last is None or bar_index - last >= p.cooldown_bars  # L60
        trend_ok_long = not p.use_trend_filter or gt(close, ema_trend)  # L61
        trend_ok_short = not p.use_trend_filter or lt(close, ema_trend)  # L62
        # Both crosses are evaluated on every bar, as in the script (L64-65).
        cross_up = self._cross_up.update(ema_fast, ema_slow)
        cross_down = self._cross_down.update(ema_fast, ema_slow)
        long_sig = cross_up and bull >= p.min_confluence and trend_ok_long and cool_ok
        short_sig = cross_down and bear >= p.min_confluence and trend_ok_short and cool_ok
        if not (long_sig or short_sig):
            return None

        self._last_signal_bar = bar_index  # every script signal restarts the cooldown (L93)
        is_long = long_sig
        count = bull if is_long else bear
        risk = atr * p.sl_mult  # L96
        if is_long:
            stop, target = close - risk, close + risk * p.rr_ratio  # L97-98
        else:
            stop, target = close + risk, close - risk * p.rr_ratio
        metadata: dict[str, JsonValue] = {
            "pine_signal": "longSig" if is_long else "shortSig",
            "trigger": "Buy" if is_long else "Sell",
            "stars": stars(count, p.min_confluence),
            "bull_count": bull,
            "bear_count": bear,
            "checks": dict(zip(CHECK_NAMES, checks, strict=True)),
            "ema_fast": _num(ema_fast),
            "ema_slow": _num(ema_slow),
            "ema_trend": _num(ema_trend),
            "rsi": _num(rsi),
            "strength": _num(abs(rsi - 50.0) * 2.0),  # L74
            "di_plus": _num(dmi.plus),
            "di_minus": _num(dmi.minus),
            "adx": _num(dmi.adx),
            "pulse_hist": _num(pulse_hist),
            "vwap": _num(vwap),
            "atr": _num(atr),
            "script_entry": _num(close),
            "script_stop": _num(stop),
            "script_target": _num(target),
            "bar_index": bar_index,
            "bar_source": bar.source,
        }
        # conf (L73): the share of checks that agree, only 14/43/71/100 %.
        confidence = pine_round(abs(bull - bear) / N_CHECKS * 100.0) / 100.0
        entry = ctx.instrument.round_price(bar.close)
        skip = _invalid_levels(ctx.instrument.round_price, entry, stop, target, is_long)
        if skip is not None:  # doc 13 D3: a stop (or target) on the wrong side is not traded
            return ctx.no_trade(skip, persist=True, metadata=metadata)
        build = ctx.long if is_long else ctx.short
        return build(
            stop_loss=stop,
            take_profit=target,
            confidence=confidence,
            reason=f"EliteAlgo {'BUY' if is_long else 'SELL'} {metadata['stars']}★",
            metadata=metadata,
        )

    def _new_day(self) -> bool:
        """``timeframe.change("1D")`` on the instrument's trading day: true on the first
        bar of a trading day after one already seen (the VWAP's anchor)."""
        current = self.ctx.periods.current("D")
        day = current.start if current is not None else None
        changed = self._trading_day is not None and day != self._trading_day
        self._trading_day = day
        return changed


def _invalid_levels(
    round_price: Callable[[Decimal], Decimal],
    entry: Decimal,
    stop: float,
    target: float,
    is_long: bool,
) -> str | None:
    """Why the script's levels cannot be traded after rounding to the tick, or None."""
    if na(stop) or na(target):
        return "LEVELS_NA"
    if stop <= 0 or target <= 0:
        return "LEVELS_NOT_POSITIVE"
    stop_d, target_d = round_price(Decimal(repr(stop))), round_price(Decimal(repr(target)))
    if (stop_d >= entry) if is_long else (stop_d <= entry):
        return "STOP_WRONG_SIDE"
    if (target_d <= entry) if is_long else (target_d >= entry):
        return "TARGET_WRONG_SIDE"
    return None


def _num(value: float) -> float | None:
    """A float for JSON metadata: na becomes null."""
    return None if na(value) else float(value)
