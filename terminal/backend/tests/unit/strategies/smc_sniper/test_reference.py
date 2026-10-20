"""The port against an independent, array-based transcription of script 5's sniper.

The reference re-reads L128-L660 directly: pivots by brute force over whole windows
(the left side ``>=``, the right side strictly ``>``), the BOS crosses against ``lsh``
/ ``lsl`` *as passed before each bar's update*, the order-block and gap lists as
plain Python lists (push after shifting at the cap, then delete on the close beyond
the far edge ± 0.05 × the current ATR), inclusive containment, the score, and the
bracket with the D3 wrong-side rule. The streaming strategy must emit the same
signals with the same unrounded levels on long synthetic runs (several seeds, the
script's defaults and short lengths, Min Score 4, either zone type switched off).
"""

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from kterminal.domain.instruments import Instrument
from kterminal.domain.market import Bar
from kterminal.domain.timeframes import Timeframe
from kterminal.indicators import Atr, Ema, Rsi, feed
from kterminal.marketdata.synthetic import synthetic_bars
from kterminal.strategies.smc_sniper import SmcSniper, SmcSniperParams
from tests.unit.strategies.pine_port_support import real_catalog, run

TOLERANCE = 1e-10
NAN = math.nan


def isna(x: float) -> bool:
    return math.isnan(x)


def p_gt(a: float, b: float) -> bool:
    return not (isna(a) or isna(b)) and a - b > TOLERANCE


def p_lt(a: float, b: float) -> bool:
    return not (isna(a) or isna(b)) and a - b < -TOLERANCE


def p_ge(a: float, b: float) -> bool:
    return not (isna(a) or isna(b)) and a - b >= -TOLERANCE


def p_le(a: float, b: float) -> bool:
    return not (isna(a) or isna(b)) and a - b <= TOLERANCE


def pivots(values: list[float], left: int, right: int, *, high: bool) -> list[float]:
    """ta.pivothigh/low: the pivot's value on its confirmation bar, na elsewhere."""
    out = [NAN] * len(values)
    for i in range(left + right, len(values)):
        j = i - right
        v = values[j]
        before, after = values[j - left : j], values[j + 1 : i + 1]
        if high:
            ok = all(v >= x for x in before) and all(v > x for x in after)
        else:
            ok = all(v <= x for x in before) and all(v < x for x in after)
        if ok:
            out[i] = v
    return out


@dataclass(frozen=True)
class Expected:
    index: int
    action: str  # LONG / SHORT / NO_TRADE
    stop: float
    target: float
    score: int


def reference(bars: list[Bar], p: SmcSniperParams, instrument: Instrument) -> list[Expected]:
    o = [float(b.open) for b in bars]
    h = [float(b.high) for b in bars]
    lo = [float(b.low) for b in bars]
    c = [float(b.close) for b in bars]
    atr = feed(Atr(p.smb_atr).update, h, lo, c)
    ema50 = feed(Ema(50).update, c)
    ema200 = feed(Ema(200).update, c)
    rsi = feed(Rsi(14).update, c)
    ob_ph, ob_pl = (
        pivots(h, p.ob_len, p.ob_len, high=True),
        pivots(lo, p.ob_len, p.ob_len, high=False),
    )
    sw_hi, sw_lo = (
        pivots(h, p.bos_len, p.bos_len, high=True),
        pivots(lo, p.bos_len, p.bos_len, high=False),
    )
    bull_obs: list[tuple[float, float]] = []  # (top, bottom)
    bear_obs: list[tuple[float, float]] = []
    bull_fvgs: list[tuple[float, float]] = []
    bear_fvgs: list[tuple[float, float]] = []

    def push(boxes: list[tuple[float, float]], box: tuple[float, float], cap: int) -> None:
        while len(boxes) >= cap:
            del boxes[0]
        boxes.append(box)

    def cull(boxes: list[tuple[float, float]], i: int, *, bull: bool) -> None:
        if bull:
            boxes[:] = [b for b in boxes if not p_lt(c[i], b[1] - atr[i] * 0.05)]
        else:
            boxes[:] = [b for b in boxes if not p_gt(c[i], b[0] + atr[i] * 0.05)]

    def inside(boxes: list[tuple[float, float]], i: int) -> bool:
        return any(p_ge(c[i], b[1]) and p_le(c[i], b[0]) for b in boxes)

    lsh = lsl = NAN
    prev_h = prev_l = NAN  # lsh / lsl as passed to the crosses on the previous bar
    upt = True
    out: list[Expected] = []
    for i in range(len(bars)):
        k = i - p.ob_len
        if p.ob_on:
            if not isna(ob_pl[i]) and p_gt(o[k], c[k]):
                push(bull_obs, (max(o[k], c[k]), min(o[k], c[k])), p.ob_max)
            if not isna(ob_ph[i]) and p_gt(c[k], o[k]):
                push(bear_obs, (max(o[k], c[k]), min(o[k], c[k])), p.ob_max)
            cull(bull_obs, i, bull=True)
            cull(bear_obs, i, bull=False)
        if p.fvg_on:
            if i >= 2 and p_lt(h[i - 2], lo[i]):
                push(bull_fvgs, (lo[i], h[i - 2]), p.fvg_max)
            if i >= 2 and p_gt(lo[i - 2], h[i]):
                push(bear_fvgs, (lo[i - 2], h[i]), p.fvg_max)
            cull(bull_fvgs, i, bull=True)
            cull(bear_fvgs, i, bull=False)
        # crosses of the levels as they stood before this bar's update
        cx_up = not isna(lsh) and not isna(prev_h) and c[i] > lsh and c[i - 1] <= prev_h
        cx_dn = not isna(lsl) and not isna(prev_l) and c[i] < lsl and c[i - 1] >= prev_l
        prev_h, prev_l = lsh, lsl
        if not isna(sw_hi[i]):
            lsh = sw_hi[i]
        if not isna(sw_lo[i]):
            lsl = sw_lo[i]
        bos_bull, bos_bear = cx_up, cx_dn
        if bos_bull:
            upt = True
        if bos_bear:
            upt = False
        roc = c[i] - c[i - 5] if i >= 5 else NAN
        bull = (
            int(p_gt(c[i], ema50[i]) and p_gt(ema50[i], ema200[i]))
            + int(upt)
            + int(inside(bull_obs, i) or inside(bull_fvgs, i))
            + int(p_gt(rsi[i], 55.0) and p_gt(roc, 0.0))
        )
        bear = (
            int(p_lt(c[i], ema50[i]) and p_lt(ema50[i], ema200[i]))
            + int(not upt)
            + int(inside(bear_obs, i) or inside(bear_fvgs, i))
            + int(p_lt(rsi[i], 45.0) and p_lt(roc, 0.0))
        )
        for is_long, fired, score in ((True, bos_bull, bull), (False, bos_bear, bear)):
            if not fired or score < p.sniper_min:
                continue
            if is_long:
                stop = (lsl if not isna(lsl) else lo[i]) - atr[i] * 0.5
                target = c[i] + 2.0 * (c[i] - stop)
            else:
                stop = (lsh if not isna(lsh) else h[i]) + atr[i] * 0.5
                target = c[i] - 2.0 * (stop - c[i])
            action = "LONG" if is_long else "SHORT"
            if isna(stop) or stop <= 0 or target <= 0:  # na ATR, or a bracket below zero
                action = "NO_TRADE"
            else:
                rounded = instrument.round_price(Decimal(repr(stop)))
                if (rounded >= bars[i].close) if is_long else (rounded <= bars[i].close):
                    action = "NO_TRADE"
            out.append(Expected(i, action, stop, target, score))
    return out


def bars_of(symbol: str, timeframe: str, seed: int, count: int) -> list[Bar]:
    catalog = real_catalog()
    instrument = catalog.instrument(symbol)
    return list(
        synthetic_bars(
            symbol,
            start=datetime(2026, 1, 5, tzinfo=UTC),
            count=count,
            start_price=Decimal(2_000),
            tick_size=instrument.tick_size,
            timeframe=Timeframe.parse(timeframe),
            seed=seed,
            volatility=0.002,
            regime_change_probability=0.01,
            is_open=catalog.sessions.calendar(instrument.trading_hours).is_open,
        )
    )


SHORT: dict[str, Any] = {"bos_len": 5, "ob_len": 3, "ob_max": 2, "fvg_max": 2}


@pytest.mark.parametrize("seed", [1, 2, 3])
@pytest.mark.parametrize(
    ("symbol", "timeframe", "params", "minimum"),
    [
        ("XAUUSD", "15m", {}, 10),
        ("NAS100", "5m", SHORT, 40),
        ("BTCUSD", "15m", {**SHORT, "sniper_min": 2}, 40),
        ("EURUSD", "5m", {**SHORT, "fvg_on": False}, 20),
        ("US30", "15m", {**SHORT, "ob_on": False, "smb_atr": 5}, 20),
    ],
)
def test_port_matches_the_transcription(
    seed: int, symbol: str, timeframe: str, params: dict[str, Any], minimum: int
) -> None:
    bars = bars_of(symbol, timeframe, seed, 3_000)
    instrument = real_catalog().instrument(symbol)
    expected = reference(bars, SmcSniperParams.model_validate(params), instrument)
    result = run(SmcSniper, bars, params=params, instrument=instrument, timeframe=timeframe)
    assert result.fault is None and result.rejected == []
    index = {bar.open_time: i for i, bar in enumerate(bars)}
    got = [
        Expected(
            index[s.bar_time],
            s.signal.value,
            s.metadata["script_stop"],  # type: ignore[arg-type]
            s.metadata["script_target"],  # type: ignore[arg-type]
            s.metadata["score"],  # type: ignore[arg-type]
        )
        for s in result.signals
        if s.bar_time is not None
    ]
    assert got == expected
    assert len(expected) >= minimum  # the comparison is not vacuous
    for signal in result.signals:
        if signal.signal.is_entry:
            meta = signal.metadata
            assert signal.stop_loss == instrument.round_price(Decimal(repr(meta["script_stop"])))
            assert signal.take_profit == instrument.round_price(
                Decimal(repr(meta["script_target"]))
            )


@pytest.mark.parametrize("seed", [1, 2, 3, 4])
def test_min_score_4_keeps_exactly_the_4_of_4_signals(seed: int) -> None:
    # Everything but the threshold is shared, so the Min Score 4 instance signals on
    # exactly the bars where the Min Score 3 one had all four points (doc 13 D11).
    bars = bars_of("XAUUSD", "5m", seed, 3_000)
    instrument = real_catalog().instrument("XAUUSD")
    three = run(SmcSniper, bars, params=SHORT, instrument=instrument)
    four = run(SmcSniper, bars, params={**SHORT, "sniper_min": 4}, instrument=instrument)
    full = [(s.bar_time, s.signal) for s in three.signals if s.metadata["score"] == 4]
    assert [(s.bar_time, s.signal) for s in four.signals] == full
    assert len(three.signals) > len(full)
