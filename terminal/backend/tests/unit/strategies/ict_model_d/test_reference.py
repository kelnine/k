"""Model D against an independent transcription of script 2 on long synthetic runs.

``transcribe`` below re-implements, in plain procedural code and without the port's
classes, the lines Model D executes: ``ta.atr(14)`` (Wilder, SMA-seeded) and the level
tolerance (L160-161); the candle-estimate delta and the aggressive flags (L627-643); the
script's own trade (L452-464, L779); the overnight 18:00-09:30 store and its value area
(L307-339, L835-854) by New York wall-clock minute; 15m bars bucketed by wall clock with
``f_htfFvg`` read through ``lookahead_on`` (a 1m bar sees the gap of the last three 15m
bars that ended by its open, fresh when that changes, L301-304, L619, L624); the zones and
their touch (L358-414, L856-865); the key levels (L866-871) with the previous trading
day's high/low (L620: the instrument's trading day, the first partial day never counted);
and the window, candidates and triggers (L873-924). The port must signal the same trades
on the same bars with the same unrounded entry, stop and target.

The data are 1m random walks with random volume: gold on the metals calendar (17:00 New
York trading day, closed at weekends) and bitcoin round the clock (UTC day), across the
2026-11-01 New York clock change.
"""

import math
from bisect import bisect_right
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from kterminal.domain.instruments import Instrument
from kterminal.domain.market import Bar
from kterminal.domain.timeframes import M15
from kterminal.marketdata.synthetic import synthetic_bars
from kterminal.strategies.ict_model_d import IctModelD
from tests.fixtures.instruments import XAUUSD
from tests.unit.strategies.ict_model_d.scenario import run_1m, with_htf
from tests.unit.strategies.pine_port_support import real_catalog

EPS = 1e-10
NAN = math.nan
NY = ZoneInfo("America/New_York")
START = datetime(2026, 10, 21, 0, 0, tzinfo=UTC)


def gt(a: float, b: float) -> bool:
    return not (math.isnan(a) or math.isnan(b)) and a - b > EPS


def ge(a: float, b: float) -> bool:
    return not (math.isnan(a) or math.isnan(b)) and a - b >= -EPS


def lt(a: float, b: float) -> bool:
    return gt(b, a)


def le(a: float, b: float) -> bool:
    return ge(b, a)


def ny_minute(t: datetime) -> int:
    local = t.astimezone(NY)
    return local.hour * 60 + local.minute


def buckets(bars: list[Bar], minutes: int) -> list[tuple[datetime, float, float]]:
    """Higher-timeframe bars by wall clock: ``(end, high, low)``, oldest first."""
    out: list[list[Any]] = []
    span = timedelta(minutes=minutes)
    for bar in bars:
        start = bar.open_time - timedelta(
            minutes=(bar.open_time.hour * 60 + bar.open_time.minute) % minutes
        )
        h, low = float(bar.high), float(bar.low)
        if out and out[-1][0] == start + span:
            out[-1][1] = max(out[-1][1], h)
            out[-1][2] = min(out[-1][2], low)
        else:
            out.append([start + span, h, low])
    return [(e, h, low) for e, h, low in out]


def value_area(
    hs: list[float], ls: list[float], vs: list[float], lo: float, hi: float, rows: int, pct: float
) -> tuple[float, float]:
    """``[vah, val]`` of f_valueArea (L307-339)."""
    if not hs or not gt(hi, lo):
        return NAN, NAN
    step = (hi - lo) / rows
    bins = [0.0] * rows
    for h, low, v in zip(hs, ls, vs, strict=True):
        r0 = max(0, min(rows - 1, math.floor((low - lo) / step)))
        r1 = max(0, min(rows - 1, math.floor((h - lo) / step)))
        for r in range(r0, r1 + 1):
            bins[r] += v / (r1 - r0 + 1)
    total = 0.0
    for b in bins:
        total += b
    if not gt(total, 0.0):
        return NAN, NAN
    poc = bins.index(max(bins))
    up = dn = poc
    acc = bins[poc]
    while lt(acc, total * pct / 100.0) and (up < rows - 1 or dn > 0):
        v_up = bins[up + 1] if up < rows - 1 else -1.0
        v_dn = bins[dn - 1] if dn > 0 else -1.0
        if ge(v_up, v_dn):
            up += 1
            acc += v_up
        else:
            dn -= 1
            acc += v_dn
    return lo + (up + 1) * step, lo + dn * step


def day_key(t: datetime, rule: str) -> tuple[Any, datetime]:
    """The trading day a bar opening at ``t`` belongs to, and that day's start (D8)."""
    if rule == "utc_midnight":
        day = t.date()
        return day, datetime(day.year, day.month, day.day, tzinfo=UTC)
    local = t.astimezone(NY)
    day = (local + timedelta(hours=7)).date()
    previous = day - timedelta(days=1)
    start = datetime(previous.year, previous.month, previous.day, 17, 0, tzinfo=NY)
    return day, start.astimezone(UTC)


def transcribe(bars: list[Bar], p: dict[str, Any], tick: float, rule: str) -> list[Any]:
    """``(open time, dir, entry, sl, tp)`` of every Model D trade the script opens."""
    zone_mode = p.get("d_zone_mode", "HTF FVG + key levels")
    use_zones, use_levels = zone_mode != "Key levels only", zone_mode != "HTF FVG only"
    vol_mult = p.get("d_vol_mult", 1.5)
    delta_pct = p.get("d_delta_pct", 30.0)
    max_bars = p.get("d_max_bars", 10)
    rr = p.get("d_rr", 2.0)
    tol_atr = p.get("d_tol_atr", 0.25)
    va_pct, rows = p.get("d_va_pct", 70.0), p.get("d_rows", 50)
    use_va, use_on, use_pd = p.get("use_va", True), p.get("use_on", True), p.get("use_pd", True)
    manual = [m for m in (p.get("d_man1", 0.0), p.get("d_man2", 0.0)) if m > 0]
    sl_buf = p.get("sl_buf_ticks", 0) * tick
    m15 = buckets(bars, 15)
    m15_ends = [b[0] for b in m15]
    trs: list[float] = []
    atr = NAN
    vols: list[float] = []
    trade: dict[str, Any] | None = None
    on_h: list[float] = []
    on_l: list[float] = []
    on_v: list[float] = []
    on_hi = on_lo = NAN
    vah = val = onh = onl = NAN
    prev_on = prev_in = False
    prev_ct: datetime | None = None
    zones: list[dict[str, Any]] = []
    first_day, first_start = day_key(bars[0].open_time, rule)
    cur_day, cur_complete = first_day, bars[0].open_time == first_start
    cur_hi, cur_lo = -math.inf, math.inf
    pdh = pdl = NAN
    long_c: dict[str, Any] | None = None
    short_c: dict[str, Any] | None = None
    trades = []
    for i, bar in enumerate(bars):
        t = bar.open_time
        o, h, low, c = float(bar.open), float(bar.high), float(bar.low), float(bar.close)
        v = float(bar.volume)
        # ta.atr(14) (L160)
        tr = h - low if i == 0 else max(h - low, abs(h - float(bars[i - 1].close)),
                                        abs(low - float(bars[i - 1].close)))  # fmt: skip
        trs.append(tr)
        if len(trs) == 14:
            atr = sum(trs) / 14
        elif len(trs) > 14:
            atr = (atr * 13 + tr) / 14
        tol = tol_atr * atr
        # order flow (L635-643)
        rng = h - low
        buy = v * (c - low) / rng if gt(rng, 0.0) else v / 2
        sell = v - buy
        delta, bar_vol = buy - sell, buy + sell
        vols.append(bar_vol)
        avg = sum(vols[-20:]) / 20 if len(vols) >= 20 else NAN
        loud = gt(bar_vol, 0.0) and ge(bar_vol, vol_mult * avg)
        aggr_buy = loud and ge(delta, delta_pct / 100.0 * bar_vol)
        aggr_sell = loud and ge(-delta, delta_pct / 100.0 * bar_vol)
        # previous trading day (L620)
        key, _ = day_key(t, rule)
        if key != cur_day:
            if cur_complete:
                pdh, pdl = cur_hi, cur_lo
            cur_day, cur_complete, cur_hi, cur_lo = key, True, -math.inf, math.inf
        cur_hi, cur_lo = max(cur_hi, h), min(cur_lo, low)
        # manage (L779)
        if trade is not None and trade["live"] and i > trade["bar"]:
            long = trade["dir"] > 0
            hit_sl = le(low, trade["sl"]) if long else ge(h, trade["sl"])
            hit_tp = ge(h, trade["tp"]) if long else le(low, trade["tp"])
            trade["live"] = not (hit_sl or hit_tp)
        live = trade is not None and trade["live"]
        # overnight (L835-854)
        m = ny_minute(t)
        inside_on = m >= 18 * 60 or m < 9 * 60 + 30
        if inside_on:
            if not prev_on:
                on_h, on_l, on_v = [], [], []
                on_hi, on_lo = h, low
            else:
                on_hi = NAN if math.isnan(on_hi) else max(on_hi, h)
                on_lo = NAN if math.isnan(on_lo) else min(on_lo, low)
            on_h.append(h)
            on_l.append(low)
            on_v.append(v)
        elif prev_on:
            vah, val = value_area(on_h, on_l, on_v, on_lo, on_hi, rows, va_pct)
            onh, onl = on_hi, on_lo
        prev_on = inside_on
        # zones (L856-865)
        at_sup = at_res = False
        if use_zones:
            k = bisect_right(m15_ends, t) - 1
            ct = m15[k - 2][0] if k >= 2 else None
            if ct is not None and ct != prev_ct:
                _, h1, l1 = m15[k]
                _, h3, l3 = m15[k - 2]
                for direction, top, bot, ok in ((1, l1, h3, gt(l1, h3)), (-1, l3, h1, lt(h1, l3))):
                    if ok:
                        zones.append({"dir": direction, "top": top, "bot": bot})
                        if len(zones) > 6:
                            del zones[0]
            prev_ct = ct
            zones = [z for z in zones if not (lt(c, z["bot"]) if z["dir"] > 0 else gt(c, z["top"]))]
            for z in zones:
                overlaps = le(low, z["top"]) and ge(h, z["bot"])
                at_sup = at_sup or (z["dir"] > 0 and overlaps)
                at_res = at_res or (z["dir"] < 0 and overlaps)
        # key levels (L866-871)
        if use_levels:
            levels = [vah, val] if use_va else []
            levels += [onh, onl] if use_on else []
            levels += [pdh, pdl] if use_pd else []
            for lvl in levels + manual:
                if not math.isnan(lvl) and le(low, lvl + tol) and ge(h, lvl - tol):
                    at_sup = at_res = True
        # window, candidates, triggers (L873-924)
        inside = 570 <= m < 960
        if inside and not prev_in:
            long_c = short_c = None
            if live:
                assert trade is not None
                trade["live"] = live = False
        prev_in = inside
        if not inside:
            long_c = short_c = None
            continue
        if live:
            continue
        if long_c is not None:
            long_c["ext"] = min(long_c["ext"], low)
            if lt(c, long_c["low0"]) or i - long_c["bar"] > max_bars:
                long_c = None
            elif aggr_buy and gt(c, long_c["top"]):
                sl = long_c["ext"] - sl_buf
                if gt(c - sl, 0.0):
                    trade = {"dir": 1, "sl": sl, "tp": c + rr * (c - sl), "bar": i, "live": True}
                    live = True
                    trades.append((t, 1, c, sl, trade["tp"]))
                long_c = short_c = None
        if long_c is None and not live and aggr_sell and at_sup:
            long_c = {"top": max(o, c), "low0": low, "ext": low, "bar": i}
        if live:
            continue
        if short_c is not None:
            short_c["ext"] = max(short_c["ext"], h)
            if gt(c, short_c["high0"]) or i - short_c["bar"] > max_bars:
                short_c = None
            elif aggr_sell and lt(c, short_c["bot"]):
                sl = short_c["ext"] + sl_buf
                if gt(sl - c, 0.0):
                    trade = {"dir": -1, "sl": sl, "tp": c - rr * (sl - c), "bar": i, "live": True}
                    live = True
                    trades.append((t, -1, c, sl, trade["tp"]))
                long_c = short_c = None
        if short_c is None and not live and aggr_buy and at_res:
            short_c = {"bot": min(o, c), "high0": h, "ext": h, "bar": i}
    return trades


def tape(instrument: Instrument, seed: int, days: int = 12) -> list[Bar]:
    calendar = real_catalog().sessions.calendar(instrument.trading_hours)
    return list(
        synthetic_bars(
            instrument.symbol,
            start=START,
            count=days * 23 * 60,
            start_price=Decimal("2000"),
            tick_size=instrument.tick_size,
            volatility=0.0006,
            seed=seed,
            is_open=calendar.is_open,
        )
    )


def port(bars: list[Bar], params: dict[str, Any], instrument: Instrument) -> list[Any]:
    result = run_1m(IctModelD, with_htf(bars, M15), params=params, instrument=instrument)
    assert result.fault is None and result.rejected == []
    out = []
    for s in result.signals:
        meta = s.metadata
        if meta.get("trigger") not in ("D long", "D short"):
            continue
        direction = 1 if meta["trigger"] == "D long" else -1
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
    {"d_zone_mode": "HTF FVG only"},
    {"d_zone_mode": "Key levels only", "d_tol_atr": 0.5},
    {"d_vol_mult": 1.3, "d_delta_pct": 50.0, "d_max_bars": 5, "d_rr": 1.5, "sl_buf_ticks": 3},
    {"use_va": False, "d_va_pct": 60.0, "d_rows": 20, "d_man1": 2000.0, "use_pd": False},
]


# (seed, days): bitcoin trades round the clock, so 14 × 23 hours reach the first window
# after the clock change
RUNS = {"XAUUSD": (5, 12), "BTCUSD": (17, 14)}


@pytest.mark.parametrize("symbol", list(RUNS))
@pytest.mark.parametrize(
    "params", PARAMS, ids=lambda p: ",".join(f"{k}={v}" for k, v in p.items()) or "defaults"
)
def test_port_matches_the_transcription(symbol: str, params: dict[str, Any]) -> None:
    instrument = XAUUSD if symbol == "XAUUSD" else real_catalog().instrument(symbol)
    seed, days = RUNS[symbol]
    bars = tape(instrument, seed=seed, days=days)
    expected = transcribe(bars, params, float(instrument.tick_size), instrument.trading_day)
    assert len(expected) >= 5  # the run exercises the model
    assert port(bars, params, instrument) == expected
