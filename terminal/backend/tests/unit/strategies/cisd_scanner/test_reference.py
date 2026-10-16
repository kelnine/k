"""S10 against an independent transcription of script 1's ``scanCisd`` and A+ grade.

``scan`` re-implements ``scanCisd`` (L778-871) in plain procedural code over a list of
bars, line by line and without the port's classes — notably without the main model's
``bar_index > bullRunX`` test, which the port's shared run tracker keeps. ``transcribe``
builds the slot bars itself from the 1m bars (UTC-aligned 5m, 15m, 1h, 4h buckets),
runs ``scan`` on each slot, and grades each 5m signal A+ against the bias of every
higher slot as of the 5m bar's open (``request.security(..., scanCisd(1),
lookahead_on)``: the state after the last slot bar that closed by then, L874-877,
L896-911). The port, fed by the lab's aggregator, must signal the same CISDs on the
same bars with the same level, stop and grade.

The data are 1m random walks over two weeks, round the clock and with the gold
calendar's closed weekends and daily breaks.
"""

import math
from bisect import bisect_right
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from kterminal.domain.market import Bar
from kterminal.domain.timeframes import M1, Timeframe
from kterminal.marketdata.aggregator import aggregate_stream
from kterminal.marketdata.synthetic import synthetic_bars
from kterminal.strategies.cisd_scanner import HIGHER_SLOTS, CisdScanner
from tests.fixtures.instruments import XAUUSD
from tests.unit.strategies.pine_port_support import real_catalog, run

EPS = 1e-10
NAN = math.nan
START = datetime(2026, 2, 2, 0, 0, tzinfo=UTC)  # a Monday, aligned to every slot
SLOTS = ("5m", *HIGHER_SLOTS)

Ohlc = tuple[datetime, float, float, float, float]  # open time, o, h, l, c
Signal = tuple[int, int, float, float]  # bar index, direction, entry, stop


def gt(a: float, b: float) -> bool:
    return not (math.isnan(a) or math.isnan(b)) and a - b > EPS


def lt(a: float, b: float) -> bool:
    return not (math.isnan(a) or math.isnan(b)) and a - b < -EPS


def ge(a: float, b: float) -> bool:
    return not (math.isnan(a) or math.isnan(b)) and a - b >= -EPS


def pivot(values: list[float], i: int, n: int, highs: bool) -> float:
    if i < 2 * n:
        return NAN
    p = i - n
    v = values[p]
    left, right = values[p - n : p], values[p + 1 : i + 1]
    if highs and all(v >= x for x in left) and all(v > x for x in right):
        return v
    if not highs and all(v <= x for x in left) and all(v < x for x in right):
        return v
    return NAN


def buckets(minutes: list[Bar], tf: Timeframe) -> list[Ohlc]:
    """UTC-aligned slot bars from 1m bars: every bucket with at least one minute."""
    out: list[Ohlc] = []
    seconds = tf.seconds
    for bar in minutes:
        epoch = int(bar.open_time.timestamp())
        start = datetime.fromtimestamp(epoch - epoch % seconds, tz=UTC)
        o, h, lo, c = (float(x) for x in (bar.open, bar.high, bar.low, bar.close))
        if out and out[-1][0] == start:
            t, o0, h0, l0, _ = out[-1]
            out[-1] = (t, o0, max(h0, h), min(l0, lo), c)
        else:
            out.append((start, o, h, lo, c))
    return out


def scan(
    rows: list[Ohlc], *, min_body: float = 0.3, req_sweep: bool = True, sweep_look: int = 12
) -> tuple[list[Signal | None], list[int]]:
    """``scanCisd`` on one slot: each bar's signal and its bias after the bar."""
    o = [r[1] for r in rows]
    h = [r[2] for r in rows]
    lo = [r[3] for r in rows]
    c = [r[4] for r in rows]
    signals: list[Signal | None] = []
    biases: list[int] = []
    atr = NAN
    trs: list[float] = []
    sw_h = sw_l = bos_h = bos_l = NAN
    bias = 0
    bsl = ssl = -100000
    u_open = u_high = d_open = d_low = NAN
    prev_up = prev_dn = False
    for i in range(len(rows)):
        tr = h[i] - lo[i]
        if i > 0:
            tr = max(tr, abs(h[i] - c[i - 1]), abs(lo[i] - c[i - 1]))
        trs.append(tr)
        if i == 13:
            atr = sum(trs) / 14
        elif i > 13:
            atr = (atr * 13 + tr) / 14
        s_ph, s_pl = pivot(h, i, 3, True), pivot(lo, i, 3, False)
        if not math.isnan(s_ph):
            sw_h = bos_h = s_ph
        if not math.isnan(s_pl):
            sw_l = bos_l = s_pl
        if not math.isnan(bos_h) and gt(c[i], bos_h):
            bias, bos_h = 1, NAN
        if not math.isnan(bos_l) and lt(c[i], bos_l):
            bias, bos_l = -1, NAN
        if not math.isnan(sw_h) and gt(h[i], sw_h):
            bsl, sw_h = i, NAN
        if not math.isnan(sw_l) and lt(lo[i], sw_l):
            ssl, sw_l = i, NAN
        up, dn = gt(c[i], o[i]), lt(c[i], o[i])
        if up and not prev_up:
            u_open, u_high = o[i], h[i]
        elif not math.isnan(u_open):
            u_high = max(u_high, h[i])
        if dn and not prev_dn:
            d_open, d_low = o[i], lo[i]
        elif not math.isnan(d_open):
            d_low = min(d_low, lo[i])
        prev_up, prev_dn = up, dn
        big = ge(abs(c[i] - o[i]), min_body * (0.0 if math.isnan(atr) else atr))
        sig: Signal | None = None
        if not math.isnan(u_open) and lt(c[i], u_open):
            if big and (not req_sweep or i - bsl <= sweep_look):
                sig = (i, -1, u_open, u_high)
            u_open = NAN
        if sig is None and not math.isnan(d_open) and gt(c[i], d_open):
            if big and (not req_sweep or i - ssl <= sweep_look):
                sig = (i, 1, d_open, d_low)
            d_open = NAN
        signals.append(sig)
        biases.append(bias)
    return signals, biases


def transcribe(
    minutes: list[Bar], *, slots_on: tuple[bool, bool, bool] = (True, True, True), **kw: Any
) -> list[tuple[int, bool, float, float, bool]]:
    rows = {tf: buckets(minutes, Timeframe.parse(tf)) for tf in SLOTS}
    five = rows["5m"]
    signals, _ = scan(five, **kw)
    closes: dict[str, list[datetime]] = {}
    biases: dict[str, list[int]] = {}
    for tf in HIGHER_SLOTS:
        _, biases[tf] = scan(rows[tf], **kw)
        duration = Timeframe.parse(tf).duration
        closes[tf] = [r[0] + duration for r in rows[tf]]
    out = []
    for sig in signals:
        if sig is None:
            continue
        i, d, entry, stop = sig
        opened = five[i][0]
        aplus = d != 0 and any(slots_on)
        for on, tf in zip(slots_on, HIGHER_SLOTS, strict=True):
            seen = bisect_right(closes[tf], opened)  # slot bars closed by the 5m open
            if on and (biases[tf][seen - 1] if seen else 0) != d:
                aplus = False
        out.append((i, d > 0, entry, stop, aplus))
    return out


def port(result: Any) -> list[tuple[int, bool, float, float, bool]]:
    """``(bar index, long, entry, stop, A+)`` of every scanner setup (entry or NO_TRADE)."""
    out = []
    for s in result.signals:
        meta = s.metadata
        if meta.get("pine_signal") == "scanCisd":
            long = meta["script_stop"] < meta["script_entry"]
            out.append(
                (meta["bar_index"], long, meta["script_entry"], meta["script_stop"], meta["aplus"])
            )
    return out


def minutes_of(seed: int, *, calendar: bool, days: int = 14) -> list[Bar]:
    is_open = real_catalog().sessions.calendar("metals_otc").is_open if calendar else None
    return list(
        synthetic_bars(
            "XAUUSD",
            start=START,
            count=days * 1_440,
            start_price=Decimal("2650"),
            tick_size=XAUUSD.tick_size,
            volatility=0.0007,
            seed=seed,
            is_open=is_open,
        )
    )


def run_scanner(minutes: list[Bar], params: dict[str, Any] | None = None) -> Any:
    targets = [Timeframe.parse(tf) for tf in SLOTS]
    bars = [b for batch in aggregate_stream(minutes, M1, targets) for b in batch]
    result = run(CisdScanner, bars, params=params, context_timeframes=HIGHER_SLOTS)
    assert result.fault is None and result.rejected == []
    return result


@pytest.mark.parametrize("calendar", [False, True], ids=["24x7", "gold-calendar"])
@pytest.mark.parametrize("seed", [4, 9])
def test_port_matches_the_transcription(seed: int, calendar: bool) -> None:
    minutes = minutes_of(seed, calendar=calendar)
    expected = transcribe(minutes)
    got = port(run_scanner(minutes))
    assert len(expected) > 100 and any(e[4] for e in expected)
    assert got == expected
    aplus_only = port(run_scanner(minutes, {"aplus_only": True}))
    assert aplus_only == [e for e in expected if e[4]]


@pytest.mark.parametrize(
    ("params", "kwargs"),
    [
        ({"on4": False}, {"slots_on": (True, True, False)}),
        ({"on2": False, "on3": False}, {"slots_on": (False, False, True)}),
        ({"on2": False, "on3": False, "on4": False}, {"slots_on": (False, False, False)}),
        ({"req_sweep": False, "min_body": 0.0}, {"req_sweep": False, "min_body": 0.0}),
        ({"sweep_look": 3, "min_body": 0.6}, {"sweep_look": 3, "min_body": 0.6}),
    ],
    ids=["no-4h", "4h-only", "no-slots", "no-filters", "look-3-body-0.6"],
)
def test_port_matches_the_transcription_for_each_input(
    params: dict[str, Any], kwargs: dict[str, Any]
) -> None:
    minutes = minutes_of(6, calendar=True)
    expected = transcribe(minutes, **kwargs)
    assert expected and port(run_scanner(minutes, params)) == expected
    if kwargs.get("slots_on") == (False, False, False):
        assert not any(e[4] for e in expected)  # A+ needs at least one higher slot


def test_the_higher_slots_lag_one_slot_bar_like_lookahead_on() -> None:
    # every A+ grade uses only slot bars that closed by the 5m bar's open
    minutes = minutes_of(4, calendar=False, days=5)
    result = run_scanner(minutes)
    entries = [s for s in result.signals if s.signal.is_entry]
    assert entries
    for signal in entries:
        slots = signal.metadata["slots"]
        assert isinstance(slots, dict)
        for tf in HIGHER_SLOTS:
            row = slots[tf]
            assert isinstance(row, dict)
            last = row["last_bar"]
            if last is None:
                continue
            closes = datetime.fromisoformat(str(last)) + Timeframe.parse(tf).duration
            assert signal.bar_time is not None and closes <= signal.bar_time
            assert signal.bar_time - closes < Timeframe.parse(tf).duration
