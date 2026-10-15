"""The port against an independent, array-based transcription of script 9's signal logic.

The reference below re-reads the Pine lines directly — whole-series indicators,
the VWAP rebuilt from its sums with its own trading-day anchors, crosses against
the last defined bar, tolerant comparisons, the shared cooldown and the bracket
— and the streaming strategy must emit the same signals on long synthetic runs
(default and short indicator lengths, several seeds, across trading days).
"""

import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pytest

from kterminal.domain.market import Bar
from kterminal.domain.timeframes import Timeframe
from kterminal.indicators import Atr, Dmi, Ema, Macd, Rsi, feed
from kterminal.marketdata.synthetic import synthetic_bars
from kterminal.strategies.elitealgo_ema_confluence import EliteAlgoEmaConfluence, EliteAlgoParams
from tests.fixtures.instruments import T0, XAUUSD
from tests.unit.strategies.pine_port_support import SESSIONS, run

TOLERANCE = 1e-10


def pine_gt(a: float, b: float) -> bool:
    return not (math.isnan(a) or math.isnan(b)) and a - b > TOLERANCE


def pine_lt(a: float, b: float) -> bool:
    return not (math.isnan(a) or math.isnan(b)) and a - b < -TOLERANCE


def crosses(a: list[float], b: list[float]) -> tuple[list[bool], list[bool]]:
    """ta.crossover / ta.crossunder against the last bar where both were defined."""
    over, under = [], []
    last: tuple[float, float] | None = None
    for x, y in zip(a, b, strict=True):
        if math.isnan(x) or math.isnan(y):
            over.append(False)
            under.append(False)
            continue
        over.append(last is not None and x > y and last[0] <= last[1])
        under.append(last is not None and x < y and last[0] >= last[1])
        last = (x, y)
    return over, under


def session_vwap(bars: list[Bar]) -> list[float]:
    """Σ(hlc3·v)/Σv from the first bar of each trading day (17:00 New York), na before the
    first boundary seen and on zero volume."""
    rule = SESSIONS.trading_day_rule(XAUUSD.trading_day)
    out: list[float] = []
    sums: tuple[float, float] | None = None
    previous_day = None
    for bar in bars:
        day = rule.trading_day(bar.open_time)
        hlc3 = (float(bar.high) + float(bar.low) + float(bar.close)) / 3.0
        volume = float(bar.volume)
        if previous_day is not None and day != previous_day:
            sums = (hlc3 * volume, volume)
        elif sums is not None:
            sums = (sums[0] + hlc3 * volume, sums[1] + volume)
        previous_day = day
        out.append(math.nan if sums is None or sums[1] == 0 else sums[0] / sums[1])
    return out


@dataclass(frozen=True)
class Expected:
    index: int
    action: str  # LONG / SHORT / NO_TRADE
    stop: float
    target: float


def reference(bars: list[Bar], p: EliteAlgoParams) -> list[Expected]:
    o = [float(b.open) for b in bars]
    h = [float(b.high) for b in bars]
    low = [float(b.low) for b in bars]
    c = [float(b.close) for b in bars]
    ema_f = feed(Ema(p.fast_len).update, c)
    ema_s = feed(Ema(p.slow_len).update, c)
    ema_t = feed(Ema(p.trend_len).update, c)
    rsi = feed(Rsi(p.rsi_len).update, c)
    atr = feed(Atr(p.atr_len).update, h, low, c)
    dmi = feed(Dmi(p.adx_len, p.adx_smoothing).update, h, low, c)
    hist = [m.hist for m in feed(Macd(p.pulse_fast, p.pulse_slow, p.pulse_signal).update, c)]
    vwap = session_vwap(bars)
    over, under = crosses(ema_f, ema_s)
    out: list[Expected] = []
    last_signal: int | None = None
    for i in range(len(bars)):
        bull = sum(
            (
                pine_gt(c[i], ema_t[i]),
                pine_gt(ema_f[i], ema_s[i]),
                pine_gt(rsi[i], 50.0),
                pine_gt(dmi[i].plus, dmi[i].minus),
                pine_gt(hist[i], 0.0),
                pine_gt(c[i], o[i]),
                pine_gt(c[i], vwap[i]),
            )
        )
        bear = 7 - bull
        cool = last_signal is None or i - last_signal >= p.cooldown_bars
        long_ok = not p.use_trend_filter or pine_gt(c[i], ema_t[i])
        short_ok = not p.use_trend_filter or pine_lt(c[i], ema_t[i])
        long_sig = over[i] and bull >= p.min_confluence and long_ok and cool
        short_sig = under[i] and bear >= p.min_confluence and short_ok and cool
        if not (long_sig or short_sig):
            continue
        last_signal = i
        risk = atr[i] * p.sl_mult
        sign = 1 if long_sig else -1
        stop, target = c[i] - sign * risk, c[i] + sign * risk * p.rr_ratio
        rounded_stop = XAUUSD.round_price(Decimal(repr(stop)))
        valid = rounded_stop < bars[i].close if long_sig else rounded_stop > bars[i].close
        action = ("LONG" if long_sig else "SHORT") if valid else "NO_TRADE"
        out.append(Expected(i, action, stop, target))
    return out


def gold(seed: int, count: int, volatility: float) -> list[Bar]:
    calendar = SESSIONS.calendar("metals_otc")
    return list(
        synthetic_bars(
            "XAUUSD",
            start=T0,
            count=count,
            start_price=Decimal("2650.00"),
            tick_size=Decimal("0.01"),
            timeframe=Timeframe.parse("5m"),
            seed=seed,
            volatility=volatility,
            regime_change_probability=0.02,
            is_open=calendar.is_open,
        )
    )


SHORT_LENGTHS: dict[str, Any] = {
    "fast_len": 3,
    "slow_len": 7,
    "trend_len": 30,
    "pulse_slow": 20,
    "pulse_signal": 5,
    "cooldown_bars": 3,
    "min_confluence": 3,
}


@pytest.mark.parametrize("params", [{}, SHORT_LENGTHS], ids=["script-defaults", "short-lengths"])
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_port_matches_the_reference_transcription(params: dict[str, Any], seed: int) -> None:
    bars = gold(seed, 2_500, 0.0015)
    result = run(EliteAlgoEmaConfluence, bars, params=params)
    assert result.fault is None and result.rejected == []
    expected = reference(bars, EliteAlgoParams.model_validate(params))
    index = {bar.open_time: i for i, bar in enumerate(bars)}
    got = [
        (
            index[s.bar_time],
            s.signal.value,
            s.metadata["script_stop"],
            s.metadata["script_target"],
        )
        for s in result.signals
        if s.bar_time is not None
    ]
    assert got == [(e.index, e.action, e.stop, e.target) for e in expected]
    assert len(expected) >= 10  # the comparison is not vacuous
    for signal in result.signals:
        if signal.signal.is_entry:
            meta = signal.metadata
            assert signal.stop_loss == XAUUSD.round_price(Decimal(repr(meta["script_stop"])))
            assert signal.take_profit == XAUUSD.round_price(Decimal(repr(meta["script_target"])))
