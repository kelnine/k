"""Model C against an independent transcription of script 2 on long synthetic runs.

``transcribe`` below re-implements, in plain procedural code and without the port's
classes, the lines Model C executes: higher-timeframe bars bucketed by wall clock from
the 1m bars; ``f_pdBias`` on every 1h bar (L228-298) read through ``lookahead_on`` and
``[1]`` (a 1m bar sees the state after the last 1h bar that ended by its open, L617);
``f_htfFvg`` on the 5m bars with ``cFresh`` (L301-304, L618, L623); the 1m gaps, CISD run
opens and IFVG list (L163-168, L740-773); the zones (L358-401) and the trigger scan
(L801-830) with the New York window by local wall-clock minute. The port must signal the
same trades on the same bars with the same unrounded entry, stop and target.

The data are 1m random walks on the metals calendar (closed at weekends) across the
2026-11-01 New York clock change.
"""

import math
from bisect import bisect_right
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from kterminal.domain.market import Bar
from kterminal.domain.timeframes import H1, M5
from kterminal.marketdata.synthetic import synthetic_bars
from kterminal.strategies.ict_model_c import IctModelC
from tests.fixtures.instruments import XAUUSD
from tests.unit.strategies.ict_model_c.scenario import run_1m, with_htf
from tests.unit.strategies.pine_port_support import real_catalog

EPS = 1e-10
NAN = math.nan
NY = ZoneInfo("America/New_York")
START = datetime(2026, 10, 19, 0, 0, tzinfo=UTC)
TICK = 0.01


def gt(a: float, b: float) -> bool:
    return not (math.isnan(a) or math.isnan(b)) and a - b > EPS


def ge(a: float, b: float) -> bool:
    return not (math.isnan(a) or math.isnan(b)) and a - b >= -EPS


def lt(a: float, b: float) -> bool:
    return gt(b, a)


def le(a: float, b: float) -> bool:
    return ge(b, a)


def pivot(values: list[float], i: int, length: int, highs: bool) -> float:
    """``ta.pivothigh/pivotlow(values, length, length)`` on bar ``i``."""
    if i < 2 * length:
        return NAN
    p = i - length
    v = values[p]
    left, right = values[p - length : p], values[p + 1 : i + 1]
    if highs and all(v >= x for x in left) and all(v > x for x in right):
        return v
    if not highs and all(v <= x for x in left) and all(v < x for x in right):
        return v
    return NAN


def buckets(bars: list[Bar], minutes: int) -> list[tuple[datetime, float, float, float]]:
    """Higher-timeframe bars by wall clock: ``(end, high, low, close)``, oldest first."""
    out: list[list[Any]] = []
    span = timedelta(minutes=minutes)
    for bar in bars:
        start = bar.open_time - timedelta(
            minutes=(bar.open_time.hour * 60 + bar.open_time.minute) % minutes
        )
        h, low, c = float(bar.high), float(bar.low), float(bar.close)
        if out and out[-1][0] == start + span:
            out[-1][1] = max(out[-1][1], h)
            out[-1][2] = min(out[-1][2], low)
            out[-1][3] = c
        else:
            out.append([start + span, h, low, c])
    return [(e, h, low, c) for e, h, low, c in out]


def pd_bias_states(h1: list[tuple[datetime, float, float, float]], liq_len: int) -> list[Any]:
    """``(bias, bsl, ssl)`` after each 1h bar (f_pdBias, L228-298)."""
    b_t: list[float] = []
    b_b: list[float] = []
    s_t: list[float] = []
    s_b: list[float] = []
    liq_h: list[float] = []
    liq_l: list[float] = []
    bias = 0
    highs = [b[1] for b in h1]
    lows = [b[2] for b in h1]
    states = []
    for k, (_, high, low, close) in enumerate(h1):
        bull_ev = bear_ev = 0
        for i in range(len(b_t) - 1, -1, -1):
            t, b = b_t[i], b_b[i]
            if lt(close, b):
                bear_ev += 1
                del b_t[i], b_b[i]
            elif le(low, t) and ge(close, (t + b) / 2):
                bull_ev += 1
        for i in range(len(s_t) - 1, -1, -1):
            t, b = s_t[i], s_b[i]
            if gt(close, t):
                bull_ev += 1
                del s_t[i], s_b[i]
            elif ge(high, b) and le(close, (t + b) / 2):
                bear_ev += 1
        if bull_ev > 0 and bear_ev == 0:
            bias = 1
        elif bear_ev > 0 and bull_ev == 0:
            bias = -1
        if k >= 2 and gt(low, highs[k - 2]):
            b_t.append(low)
            b_b.append(highs[k - 2])
            if len(b_t) > 10:
                del b_t[0], b_b[0]
        if k >= 2 and lt(high, lows[k - 2]):
            s_t.append(lows[k - 2])
            s_b.append(high)
            if len(s_t) > 10:
                del s_t[0], s_b[0]
        ph = pivot(highs, k, liq_len, True)
        pl = pivot(lows, k, liq_len, False)
        if not math.isnan(ph):
            liq_h.append(ph)
            if len(liq_h) > 50:
                del liq_h[0]
        if not math.isnan(pl):
            liq_l.append(pl)
            if len(liq_l) > 50:
                del liq_l[0]
        liq_h = [x for x in liq_h if not gt(high, x)]
        liq_l = [x for x in liq_l if not lt(low, x)]
        states.append((bias, min(liq_h) if liq_h else NAN, max(liq_l) if liq_l else NAN))
    return states


def in_window(t: datetime, start: int, end: int) -> bool:
    local = t.astimezone(NY)
    m = local.hour * 60 + local.minute
    return start <= m < end


def transcribe(bars: list[Bar], p: dict[str, Any]) -> list[tuple[Any, ...]]:
    """``(open time, dir, entry, sl, tp)`` of every Model C trade the script opens."""
    look = p.get("c_look", 30)
    trig = p.get("c_trig", "IFVG or CISD")
    tgt = p.get("c_tgt", "Draw on liquidity")
    rr = p.get("c_rr", 2.0)
    min_rr = p.get("min_rr", 1.0)
    min_gap = p.get("min_fvg_ticks", 0) * TICK
    sl_buf = p.get("sl_buf_ticks", 0) * TICK
    h1 = buckets(bars, 60)
    states = pd_bias_states(h1, p.get("c_liq_len", 3))
    h1_ends = [b[0] for b in h1]
    m5 = buckets(bars, 5)
    m5_ends = [b[0] for b in m5]
    o = [float(b.open) for b in bars]
    h = [float(b.high) for b in bars]
    lo = [float(b.low) for b in bars]
    c = [float(b.close) for b in bars]
    zones: list[dict[str, Any]] = []
    bg: list[list[Any]] = []  # bearish 1m gaps: [top, middle bar]
    ug: list[list[Any]] = []  # bullish 1m gaps: [bottom, middle bar]
    bear_run = bull_run = NAN
    taken = 0
    prev_in = False
    prev_ct: datetime | None = None
    trades = []
    for i, bar in enumerate(bars):
        t = bar.open_time
        kh = bisect_right(h1_ends, t) - 1
        bias, bsl, ssl = states[kh] if kh >= 0 else (0, NAN, NAN)
        k5 = bisect_right(m5_ends, t) - 1
        ct = m5[k5 - 2][0] if k5 >= 2 else None
        fresh = ct is not None and ct != prev_ct
        prev_ct = ct
        # runs (L740-743)
        if lt(c[i], o[i]) and not (i > 0 and lt(c[i - 1], o[i - 1])):
            bear_run = o[i]
        if gt(c[i], o[i]) and not (i > 0 and gt(c[i - 1], o[i - 1])):
            bull_run = o[i]
        # IFVG (L745-773)
        inv_bull, inv_bull_bar, inv_bear, inv_bear_bar = False, 0, False, 0
        for j in range(len(bg) - 1, -1, -1):
            if i - bg[j][1] > look:
                del bg[j]
            elif gt(c[i], bg[j][0]):
                inv_bull, inv_bull_bar = True, max(inv_bull_bar, bg[j][1])
                del bg[j]
        for j in range(len(ug) - 1, -1, -1):
            if i - ug[j][1] > look:
                del ug[j]
            elif lt(c[i], ug[j][0]):
                inv_bear, inv_bear_bar = True, max(inv_bear_bar, ug[j][1])
                del ug[j]
        if i >= 2 and lt(h[i], lo[i - 2]) and ge(lo[i - 2] - h[i], min_gap):
            bg.append([lo[i - 2], i - 1])
        if i >= 2 and gt(lo[i], h[i - 2]) and ge(lo[i] - h[i - 2], min_gap):
            ug.append([h[i - 2], i - 1])
        # zones (L801-806)
        if fresh:
            _, h_1, l_1, _ = m5[k5]
            _, h_3, l_3, _ = m5[k5 - 2]
            for direction, top, bot, ok in (
                (1, l_1, h_3, gt(l_1, h_3)),
                (-1, l_3, h_1, lt(h_1, l_3)),
            ):
                if ok:
                    zones.append(
                        {
                            "dir": direction,
                            "top": top,
                            "bot": bot,
                            "tapped": False,
                            "tap": None,
                            "ext": NAN,
                            "ext_bar": None,
                            "cisd": NAN,
                            "used": False,
                        }
                    )
                    if len(zones) > 6:
                        del zones[0]
        for j in range(len(zones) - 1, -1, -1):
            z = zones[j]
            if lt(c[i], z["bot"]) if z["dir"] > 0 else gt(c[i], z["top"]):
                del zones[j]
                continue
            if z["dir"] > 0 and le(lo[i], z["top"]):
                if not z["tapped"]:
                    z["tapped"], z["tap"] = True, i
                if math.isnan(z["ext"]) or lt(lo[i], z["ext"]):
                    z["ext"], z["ext_bar"], z["cisd"] = lo[i], i, bear_run
            if z["dir"] < 0 and ge(h[i], z["bot"]):
                if not z["tapped"]:
                    z["tapped"], z["tap"] = True, i
                if math.isnan(z["ext"]) or gt(h[i], z["ext"]):
                    z["ext"], z["ext_bar"], z["cisd"] = h[i], i, bull_run
        inside = in_window(t, 570, 720)
        if inside and not prev_in:
            taken = 0
        prev_in = inside
        if not (inside and taken < 1 and bias != 0):
            continue
        for j in range(len(zones) - 1, -1, -1):
            z = zones[j]
            if not (z["dir"] == bias and z["tapped"] and not z["used"]):
                continue
            if i - z["ext_bar"] > look:
                continue
            d = z["dir"]
            via_ifvg = trig != "CISD only" and (
                (inv_bull and inv_bull_bar >= z["tap"] - look)
                if d > 0
                else (inv_bear and inv_bear_bar >= z["tap"] - look)
            )
            via_cisd = (
                trig != "IFVG only"
                and not math.isnan(z["cisd"])
                and (gt(c[i], z["cisd"]) if d > 0 else lt(c[i], z["cisd"]))
            )
            sl = z["ext"] - sl_buf if d > 0 else z["ext"] + sl_buf
            risk = abs(c[i] - sl)
            if (via_ifvg or via_cisd) and gt(risk, 0.0):
                dol = bsl if d > 0 else ssl
                dist = dol - c[i] if d > 0 else c[i] - dol
                ok = tgt == "Draw on liquidity" and not math.isnan(dol) and gt(dist, 0.0)
                ok = ok and ge(dist, min_rr * risk)
                tp = dol if ok else c[i] + d * rr * risk
                trades.append((t, d, c[i], sl, tp))
                z["used"] = True
                taken += 1
                break
    return trades


def tape(seed: int, days: int = 12) -> list[Bar]:
    calendar = real_catalog().sessions.calendar(XAUUSD.trading_hours)
    return list(
        synthetic_bars(
            "XAUUSD",
            start=START,
            count=days * 23 * 60,
            start_price=Decimal("2000"),
            tick_size=XAUUSD.tick_size,
            volatility=0.0006,
            seed=seed,
            is_open=calendar.is_open,
        )
    )


def port(bars: list[Bar], params: dict[str, Any]) -> list[tuple[Any, ...]]:
    result = run_1m(IctModelC, with_htf(bars, M5, H1), params=params)
    assert result.fault is None and result.rejected == []
    out = []
    for s in result.signals:
        meta = s.metadata
        if meta.get("trigger") not in ("C long", "C short"):
            continue
        direction = 1 if meta["trigger"] == "C long" else -1
        out.append(
            (
                s.bar_time,
                direction,
                meta["script_entry"],
                meta["script_stop"],
                meta["script_target"],
            )
        )
    return out


PARAMS: list[dict[str, Any]] = [
    {},
    {"c_trig": "IFVG only"},
    {"c_trig": "CISD only", "c_look": 10},
    {"c_tgt": "Fixed RR", "c_rr": 3.0, "sl_buf_ticks": 7},
    {"min_rr": 2.5, "c_liq_len": 2, "min_fvg_ticks": 5},
]


@pytest.mark.parametrize("seed", [3, 11])
@pytest.mark.parametrize(
    "params", PARAMS, ids=lambda p: ",".join(f"{k}={v}" for k, v in p.items()) or "defaults"
)
def test_port_matches_the_transcription(seed: int, params: dict[str, Any]) -> None:
    bars = tape(seed)
    expected = transcribe(bars, params)
    assert len(expected) >= 5  # the run exercises the model
    assert port(bars, params) == expected
