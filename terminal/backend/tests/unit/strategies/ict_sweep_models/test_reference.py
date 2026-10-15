"""Models A and B against an independent transcription of script 2 on long synthetic runs.

``transcribe`` below re-implements, in plain procedural code and without the port's
classes, the lines the two models execute: the shared series (L159-173), the stored MSS
pivots (L726-737) and ``f_pivotBefore`` (L184-194), ``f_liqSwings`` through
``request.security(..., lookahead_on)`` with its ``[1]`` (L197-222, L616: a 1m bar in 15m
bar k sees the state after bar k-1), the 08:00 range (L786-797), the New York windows by
local wall-clock minute (L646-653) and ``SweepModel.run`` (L466-595). The port must arm
the same setups on the same bars with the same levels, its book must fill exactly where
the script fills, and every "missed" must cancel the resting order on that bar.

The data are 1m random walks around the clock across the 2026-11-01 New York clock
change, so the 20:00-02:00 window is seven hours long once.
"""

import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from kterminal.core.enums import Direction, OrderType, SignalAction
from kterminal.domain.market import Bar
from kterminal.domain.timeframes import M1
from kterminal.marketdata.synthetic import synthetic_bars
from kterminal.strategies.ict_sweep_models import IctModelA, IctModelB
from kterminal.strategy_engine import PositionEventKind
from tests.fixtures.instruments import XAUUSD
from tests.unit.strategies.ict_sweep_models.scenario import run_1m, with_15m

EPS = 1e-10
NAN = math.nan
NY = ZoneInfo("America/New_York")
START = datetime(2026, 10, 24, 0, 0, tzinfo=UTC)
TICK = 0.01


def gt(a: float, b: float) -> bool:
    return not (math.isnan(a) or math.isnan(b)) and a - b > EPS


def ge(a: float, b: float) -> bool:
    return not (math.isnan(a) or math.isnan(b)) and a - b >= -EPS


def minute_of_day(t: datetime) -> int:
    local = t.astimezone(NY)
    return local.hour * 60 + local.minute


def inside(t: datetime, session: str) -> bool:
    """``not na(time(timeframe.period, session + ":1234567", "America/New_York"))``."""
    start = int(session[:2]) * 60 + int(session[2:4])
    end = int(session[5:7]) * 60 + int(session[7:9])
    m = minute_of_day(t)
    return start <= m < end if start < end else (m >= start or m < end)


def pivot(values: list[float], i: int, length: int, highs: bool) -> float:
    """``ta.pivothigh/pivotlow(values, length, length)`` on bar ``i`` (>= on the left,
    strictly beyond on the right: the newer of equal extremes)."""
    if i < 2 * length:
        return NAN
    p = i - length
    v = values[p]
    left = values[p - length : p]
    right = values[p + 1 : i + 1]
    if highs and all(v >= x for x in left) and all(v > x for x in right):
        return v
    if not highs and all(v <= x for x in left) and all(v < x for x in right):
        return v
    return NAN


class LiqSwings:
    """``f_liqSwings`` on 15m bars, fed bucket by bucket."""

    def __init__(self, length: int) -> None:
        self.length = length
        self.high: list[float] = []
        self.low: list[float] = []
        self.hs: list[float] = []
        self.ls: list[float] = []

    def bar(self, high: float, low: float) -> None:
        self.high.append(high)
        self.low.append(low)
        i = len(self.high) - 1
        ph = pivot(self.high, i, self.length, True)
        pl = pivot(self.low, i, self.length, False)
        if not math.isnan(ph):
            self.hs.append(ph)
            if len(self.hs) > 50:
                self.hs.pop(0)
        if not math.isnan(pl):
            self.ls.append(pl)
            if len(self.ls) > 50:
                self.ls.pop(0)
        for j in range(len(self.hs) - 1, -1, -1):
            if gt(high, self.hs[j]):
                del self.hs[j]
        for j in range(len(self.ls) - 1, -1, -1):
            if gt(self.ls[j], low):
                del self.ls[j]


def transcribe(bars: list[Bar], model: str, p: dict[str, Any]) -> list[tuple[Any, ...]]:
    """Events of the script: ("armed", i, dir, entry, sl, tp), ("filled", i, price),
    ("missed", i)."""
    mss_len = p.get("mss_len", 2)
    disp_mult = p.get("disp_mult", 1.5)
    min_gap = p.get("min_fvg_ticks", 0) * TICK
    sl_buf = p.get("sl_buf_ticks", 0) * TICK
    min_rr = p.get("min_rr", 1.0)
    edge = p.get("entry_mode", "FVG edge") == "FVG edge"
    if model == "A":
        win, tgt_mode, rr, need_back = (
            p.get("a_win", "2000-0200"),
            p.get("a_tgt"),
            p.get("a_rr", 2.0),
            False,
        )
        swings = LiqSwings(p.get("a_swing", 2))
    else:
        win, tgt_mode, rr, need_back = (
            p.get("b_win", "0900-1200"),
            p.get("b_tgt"),
            p.get("b_rr", 2.0),
            True,
        )
    target_level = (tgt_mode or "Opposite level") == "Opposite level"

    o_, h_, l_, c_, body, avg = [], [], [], [], [], []  # type: ignore[var-annotated]
    p_hp: list[float] = []
    p_hb: list[int] = []
    p_lp: list[float] = []
    p_lb: list[int] = []
    s: dict[str, Any] = {"hi": NAN, "lo": NAN, "state": 4, "dir": 0, "ext": NAN, "extBar": 0}
    s.update(backIn=False, mss=False, mssBar=0, fvgTop=NAN, fvgBot=NAN, fvgBar=0)
    s.update(entry=NAN, sl=NAN, tp=NAN)
    b_hi = b_lo = NAN
    b_t0: datetime | None = None
    bucket: datetime | None = None
    bucket_hl: list[float] = []
    prev_in = prev_range = False
    events: list[tuple[Any, ...]] = []
    for i, bar in enumerate(bars):
        o, h, lo, c = float(bar.open), float(bar.high), float(bar.low), float(bar.close)
        o_.append(o), h_.append(h), l_.append(lo), c_.append(c)
        body.append(abs(c - o))
        avg.append(math.fsum(body[-20:]) / 20 if len(body) >= 20 else NAN)
        h2 = h_[i - 2] if i >= 2 else NAN
        l2 = l_[i - 2] if i >= 2 else NAN
        bull_gap = gt(lo, h2) and ge(lo - h2, min_gap)
        bear_gap = gt(l2, h) and ge(l2 - h, min_gap)
        a1 = avg[i - 1] if i >= 1 and not math.isnan(avg[i - 1]) else 0.0
        b1 = body[i - 1] if i >= 1 else NAN
        bull_disp = i >= 1 and bull_gap and gt(c_[i - 1], o_[i - 1]) and ge(b1, disp_mult * a1)
        bear_disp = i >= 1 and bear_gap and gt(o_[i - 1], c_[i - 1]) and ge(b1, disp_mult * a1)
        ph, pl = pivot(h_, i, mss_len, True), pivot(l_, i, mss_len, False)
        if not math.isnan(ph):
            p_hp.append(ph), p_hb.append(i - mss_len)
            if len(p_hp) > 100:
                p_hp.pop(0), p_hb.pop(0)
        if not math.isnan(pl):
            p_lp.append(pl), p_lb.append(i - mss_len)
            if len(p_lp) > 100:
                p_lp.pop(0), p_lb.pop(0)

        if model == "A":  # lookahead_on + [1]: the state after the previous 15m bucket
            k = bar.open_time.replace(minute=bar.open_time.minute // 15 * 15)
            if bucket is not None and k != bucket:
                swings.bar(max(bucket_hl[0::2]), min(bucket_hl[1::2]))
                bucket_hl = []
            bucket = k
            bucket_hl += [h, lo]
            n_hi = swings.hs[-1] if swings.hs else NAN
            n_lo = swings.ls[-1] if swings.ls else NAN
        else:
            in_range = inside(bar.open_time, p.get("b_range", "0800-0900"))
            if in_range and not prev_range:
                b_hi, b_lo, b_t0 = h, lo, bar.open_time
            elif in_range:
                b_hi, b_lo = max(b_hi, h), min(b_lo, lo)
            prev_range = in_range
            fresh = b_t0 is not None and bar.open_time - b_t0 < timedelta(hours=24)
            n_hi, n_lo = (b_hi, b_lo) if fresh else (NAN, NAN)

        active = inside(bar.open_time, win)
        start_now = active and not prev_in
        prev_in = active
        # ── SweepModel.run ──
        if start_now:
            s.update(hi=n_hi, lo=n_lo, dir=0, mss=False, backIn=False, fvgTop=NAN, fvgBot=NAN)
            bad = math.isnan(n_hi) or math.isnan(n_lo) or not gt(n_hi, n_lo)
            s["state"] = 4 if bad else 0
        if not active and s["state"] <= 2:
            s["state"] = 4
        if not (active and s["state"] <= 2):
            continue
        if s["state"] == 2:
            d = s["dir"]
            filled = ge(s["entry"], lo) if d > 0 else ge(h, s["entry"])
            missed = ge(h, s["tp"]) if d > 0 else ge(s["tp"], lo)
            if filled:
                px = min(o, s["entry"]) if d > 0 else max(o, s["entry"])
                events.append(("filled", i, px))
                s["state"] = 3
            elif missed:
                events.append(("missed", i))
                s["state"] = 4
        if s["state"] <= 1:
            if (s["dir"] == -1 and gt(h, s["ext"])) or (s["dir"] != -1 and gt(h, s["hi"])):
                s.update(dir=-1, ext=h, extBar=i, mss=False, backIn=False, fvgTop=NAN, fvgBot=NAN)
                s["state"] = 1
            if (s["dir"] == 1 and gt(s["ext"], lo)) or (s["dir"] != 1 and gt(s["lo"], lo)):
                s.update(dir=1, ext=lo, extBar=i, mss=False, backIn=False, fvgTop=NAN, fvgBot=NAN)
                s["state"] = 1
        if s["state"] != 1:
            continue
        long = s["dir"] == 1
        if gt(c, s["lo"]) if long else gt(s["hi"], c):
            s["backIn"] = True
        disp = bull_disp if long else bear_disp
        if disp and i - 2 >= s["extBar"] and (not s["mss"] or i - 1 <= s["mssBar"] + 3):
            s.update(fvgTop=lo if long else l2, fvgBot=h2 if long else h, fvgBar=i - 1)
        if long and not math.isnan(s["fvgBot"]) and gt(s["fvgBot"], c):
            s.update(fvgTop=NAN, fvgBot=NAN)
        if not long and not math.isnan(s["fvgTop"]) and gt(c, s["fvgTop"]):
            s.update(fvgTop=NAN, fvgBot=NAN)
        if not s["mss"]:
            prices, pbars = (p_hp, p_hb) if long else (p_lp, p_lb)
            level = NAN
            for j in range(len(prices) - 1, -1, -1):
                if pbars[j] < s["extBar"]:
                    level = prices[j]
                    break
            if gt(c, level) if long else gt(level, c):
                s.update(mss=True, mssBar=i)
        ready = s["mss"] and not math.isnan(s["fvgTop"]) and s["fvgBar"] <= s["mssBar"] + 3
        if ready and (s["backIn"] or not need_back):
            top, bot = s["fvgTop"], s["fvgBot"]
            entry = (top if long else bot) if edge else (top + bot) / 2
            sl = s["ext"] - sl_buf if long else s["ext"] + sl_buf
            risk = entry - sl if long else sl - entry
            tgt = (s["hi"] if long else s["lo"]) if target_level else NAN
            dist = tgt - entry if long else entry - tgt
            ok = not math.isnan(tgt) and gt(dist, 0.0) and ge(dist, min_rr * risk)
            tp = tgt if ok else (entry + rr * risk if long else entry - rr * risk)
            s.update(entry=entry, sl=sl, tp=tp, state=2)
            events.append(("armed", i, 1 if long else -1, entry, sl, tp))
    return events


def tape(seed: int, days: int = 12) -> list[Bar]:
    return list(
        synthetic_bars(
            "XAUUSD",
            start=START,
            count=days * 1440,
            start_price=Decimal("2650.00"),
            tick_size=Decimal("0.01"),
            timeframe=M1,
            seed=seed,
            volatility=0.0006,
        )
    )


CASES = [
    ("A", {}),
    ("A", {"a_swing": 3, "mss_len": 3, "min_rr": 2.0, "sl_buf_ticks": 5}),
    ("A", {"entry_mode": "FVG 50% (CE)", "a_tgt": "Fixed RR", "a_rr": 1.5}),
    ("B", {}),
    ("B", {"disp_mult": 1.2, "min_fvg_ticks": 5, "b_rr": 3.0, "min_rr": 1.5}),
    ("B", {"entry_mode": "FVG 50% (CE)", "b_win": "0830-1300", "b_range": "0700-0830"}),
]


@pytest.mark.parametrize(
    ("model", "params"), CASES, ids=[f"{m}-{i}" for i, (m, _) in enumerate(CASES)]
)
@pytest.mark.parametrize("seed", [4, 6])
def test_port_matches_the_script_transcription(
    model: str, params: dict[str, Any], seed: int
) -> None:
    minutes = tape(seed)
    strategy = IctModelA if model == "A" else IctModelB
    result = run_1m(strategy, with_15m(minutes) if model == "A" else minutes, params=params)
    assert result.fault is None and result.rejected == []
    index = {bar.open_time: i for i, bar in enumerate(minutes)}
    events = transcribe(minutes, model, params)

    armed = [e[1:] for e in events if e[0] == "armed"]
    assert len(armed) >= 5
    setups = [s for s in result.signals if str(s.metadata.get("trigger", "")).endswith("setup")]
    got = [
        (
            index[s.bar_time] if s.bar_time else -1,
            s.metadata["ev"],
            s.metadata["script_entry"],
            s.metadata["script_stop"],
            s.metadata["script_target"],
        )
        for s in setups
    ]
    assert got == armed  # same bars, directions and unrounded levels
    placed = {
        index[s.bar_time]
        for s in setups
        if s.bar_time is not None and s.signal is not SignalAction.NO_TRADE
    }
    for signal in setups:
        if signal.signal is SignalAction.NO_TRADE:
            continue
        assert signal.order_type is OrderType.LIMIT
        assert signal.entry == XAUUSD.round_price(Decimal(repr(signal.metadata["script_entry"])))

    # A fill or a "missed" belongs to the latest setup armed before it (state 2 lasts
    # until then); only setups that placed an order (not a NO_TRADE) reach the book.
    armed_bars = [e[1] for e in events if e[0] == "armed"]

    def placed_before(i: int) -> bool:
        return max(a for a in armed_bars if a < i) in placed

    missed = [e[1] for e in events if e[0] == "missed" and placed_before(e[1])]
    cancels = [
        index[s.bar_time]
        for s in result.signals
        if s.bar_time and s.metadata.get("trigger") == f"{model} missed"
    ]
    assert cancels == missed

    if params.get("entry_mode", "FVG edge") == "FVG edge":  # on-grid limits: same fills
        fills = [(e[1], e[2]) for e in events if e[0] == "filled" and placed_before(e[1])]
        opened = [
            (index[e.time], float(e.price))
            for e in result.events
            if e.kind is PositionEventKind.OPENED and e.price is not None
        ]
        assert opened == fills
        assert not any(
            s.metadata.get("trigger") in ("late fill", "fill not matched") for s in result.signals
        )


def test_short_and_long_setups_both_occur() -> None:
    minutes = tape(4)
    result = run_1m(IctModelB, minutes)
    directions = {
        s.signal.direction
        for s in result.signals
        if s.signal in (SignalAction.LONG, SignalAction.SHORT)
    }
    assert directions == {Direction.LONG, Direction.SHORT}
