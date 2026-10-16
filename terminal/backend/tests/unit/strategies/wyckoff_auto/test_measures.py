"""``BarMeasures`` (L1062-1159) against an independent transcription over whole arrays.

The reference re-reads each line with plain lists: windows sliced by hand, pivots by
brute force over the ``2 x pLen + 1`` bars ending at the bar (left ``>=``, right
strictly ``>``) with the per-bar length, ``f_priorTrendScore`` (L573-613) as a loop over
``x[k]`` look-ups, ``x[1]`` as the previous element. The streaming object must agree on
every field of every bar of long synthetic runs whose swing length switches between the
live ATR-adaptive length and frozen campaign lengths, as the engine's does.
"""

import math
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

import numpy as np
import pytest

from kterminal.domain.timeframes import Timeframe
from kterminal.indicators import Atr, feed
from kterminal.marketdata.synthetic import synthetic_bars
from kterminal.strategies.wyckoff_auto.measures import BarMeasures, Measures

TOL = 1e-10
NAN = math.nan
Row = tuple[float, float, float, float, float]


def isna(x: float) -> bool:
    return x is None or math.isnan(x)


def nz(x: float, r: float = 0.0) -> float:
    return r if isna(x) else x


def p_ge(a: float, b: float) -> bool:
    return not (isna(a) or isna(b)) and a - b >= -TOL


def p_le(a: float, b: float) -> bool:
    return not (isna(a) or isna(b)) and a - b <= TOL


def p_gt(a: float, b: float) -> bool:
    return not (isna(a) or isna(b)) and a - b > TOL


def p_lt(a: float, b: float) -> bool:
    return not (isna(a) or isna(b)) and a - b < -TOL


def hist(xs: Sequence[float], i: int, k: int) -> float:
    """``x[k]`` on bar ``i``."""
    return xs[i - k] if i - k >= 0 else NAN


def sma(xs: Sequence[float], i: int, n: int) -> float:
    """ta.sma over defined values (the inputs here are never na)."""
    if i < n - 1:
        return NAN
    return math.fsum(xs[i - n + 1 : i + 1]) / n


def window(xs: Sequence[float], i: int, n: int, fn: object) -> float:
    if i < n - 1:
        return NAN
    assert callable(fn)
    return float(fn(xs[i - n + 1 : i + 1]))


def pivot(xs: Sequence[float], i: int, n: int, *, high: bool) -> float:
    if i < 2 * n:
        return NAN
    j = i - n
    v = xs[j]
    left, right = xs[j - n : j], xs[j + 1 : i + 1]
    if high:
        ok = all(v >= x for x in left) and all(v > x for x in right)
    else:
        ok = all(v <= x for x in left) and all(v < x for x in right)
    return v if ok else NAN


def pine_round(x: float) -> int:
    return math.floor(x + 0.5)  # non-negative arguments only


def trend_score(
    i: int, n_in: int, e_in: int, close: list[float], a: list[float], ph: list[float],
    pl: list[float], smas: list[float], mintick: float,
) -> float:  # fmt: skip
    n, e = max(n_in, 2), max(e_in, 0)
    c_end, c_start = hist(close, i, e), hist(close, i, e + n)
    if isna(c_end) or isna(c_start):
        return 0.0
    unit = max(nz(hist(a, i, e), a[i]), mintick)
    net = c_end - c_start
    disp = max(-3.0, min(3.0, net / (unit * math.sqrt(n)))) * 15.0
    path = 0.0
    hh = ll = lh = hl = 0
    last_ph = last_pl = NAN
    for k in range(n - 1, -1, -1):
        o = e + k
        path += abs(nz(hist(close, i, o)) - nz(hist(close, i, o + 1), nz(hist(close, i, o))))
        vph, vpl = hist(ph, i, o), hist(pl, i, o)
        if not isna(vph):
            if not isna(last_ph):
                hh += p_gt(vph, last_ph)
                lh += p_lt(vph, last_ph)
            last_ph = vph
        if not isna(vpl):
            if not isna(last_pl):
                hl += p_gt(vpl, last_pl)
                ll += p_lt(vpl, last_pl)
            last_pl = vpl
    er = abs(net) / path if path > TOL else 0.0
    er_part = (1.0 if p_ge(net, 0.0) else -1.0) * er * 25.0
    swings = hh + ll + lh + hl
    swing_part = (hh + hl - lh - ll) / swings * 20.0 if swings > 0 else 0.0
    s_end, s_start = hist(smas, i, e), hist(smas, i, e + n)
    sma_part = 0.0
    if not isna(s_end) and not isna(s_start):
        sma_part = 10.0 if p_gt(s_end, s_start) else -10.0 if p_lt(s_end, s_start) else 0.0
    return max(-100.0, min(100.0, disp + er_part + swing_part + sma_part))


def reference(rows: list[Row], lengths: list[int | None], mintick: float) -> list[dict[str, float]]:
    o = [r[0] for r in rows]
    h = [r[1] for r in rows]
    lo = [r[2] for r in rows]
    c = [r[3] for r in rows]
    vol = [nz(r[4]) for r in rows]
    atr_raw = feed(Atr(14).update, h, lo, c)
    cum = np.cumsum(vol)
    eff: list[float] = []
    avg_raws: list[float] = []
    a: list[float] = []
    live: list[int] = []
    ph: list[float] = []
    pl: list[float] = []
    smas: list[float] = []
    dn: list[float] = []
    up: list[float] = []
    out = []
    for i in range(len(rows)):
        spr = max(h[i] - lo[i], mintick)
        eff.append(spr if cum[i] <= TOL else vol[i])
        avg_raws.append(sma(eff, i, 50))
        avg = nz(avg_raws[i], eff[i])
        a.append(nz(atr_raw[i], spr))
        base = sma(a, i, 50)
        ratio = a[i] / base if nz(base) > TOL else 1.0
        live.append(max(2, min(10, pine_round(4 * ratio))))
        p = live[i] if lengths[i] is None else lengths[i]
        assert p is not None
        ph.append(pivot(h, i, p, high=True))
        pl.append(pivot(lo, i, p, high=False))
        smas.append(sma(c, i, 200))
        unit = max(a[i], mintick)
        rel_e = eff[i] / max(avg, 1e-10)
        spr_atr = spr / unit
        effort2 = max(rel_e, 0.01) * max(spr_atr, 0.01)
        c1 = nz(hist(c, i, 1), c[i])
        dn.append(max(c1 - c[i], 0.0) / unit / effort2)
        up.append(max(c[i] - c1, 0.0) / unit / effort2)
        prior_lo = window(lo, i - 1, 30, min) if i >= 1 else NAN
        prior_hi = window(h, i - 1, 30, max) if i >= 1 else NAN
        n_trend = max(25, min(200, pine_round(live[i] * 8.0)))
        e_trend = max(2, min(8, pine_round(live[i] * 0.75)))
        score = trend_score(i, n_trend, e_trend, c, a, ph, pl, smas, mintick)
        mb_low, mb_high = window(lo, i, 5, min), window(h, i, 5, max)
        mb_sum = window(eff, i, 5, math.fsum)
        mb_ratio = mb_sum / max(avg * 5, 1e-10)
        c_pos = (c[i] - lo[i]) / spr
        s1, s20 = hist(smas, i, 1), hist(smas, i, 20)
        p_spr = max(nz(hist(h, i, p), h[i]) - nz(hist(lo, i, p), lo[i]), mintick)
        dn_base = sma(dn, i - 1, 10) if i >= 1 else NAN
        up_base = sma(up, i - 1, 10) if i >= 1 else NAN
        out.append(
            {
                "eff": eff[i],
                "no_vol": float(cum[i] <= TOL),
                "avg_eff": avg,
                "avg_eff_prev": nz(hist(avg_raws, i, 1), avg),
                "a": a[i],
                "a_prev": nz(hist(atr_raw, i, 1), a[i]),
                "rel_e": rel_e,
                "c_pos": c_pos,
                "recent_eff": sma(eff, i, 3),
                "recent_low": window(lo, i, 3, min),
                "prior_lo": prior_lo,
                "prior_hi": prior_hi,
                "eff_hi_prior": window(eff, i - 1, 30, max) if i >= 1 else NAN,
                "new_low": float(not isna(prior_lo) and p_le(lo[i], prior_lo)),
                "new_high": float(not isna(prior_hi) and p_ge(h[i], prior_hi)),
                "live_len": live[i],
                "pre_len": live[i - 3] if i >= 3 else live[i],
                "p_len": p,
                "ph": ph[i],
                "pl": pl[i],
                "piv_bar": i - p,
                "p_a": max(nz(hist(atr_raw, i, p), a[i]), mintick),
                "p_eff": nz(hist(eff, i, p), eff[i]),
                "p_spr": p_spr,
                "p_c_pos": (nz(hist(c, i, p), c[i]) - nz(hist(lo, i, p), lo[i])) / p_spr,
                "p_avg_eff": nz(hist(avg_raws, i, p), avg),
                "trend_score": score,
                "down_trend": float(p_le(score, -15.0)),
                "strong_trend": float(p_ge(abs(score), 35.0)),
                "long_bull": float(p_gt(nz(hist(c, i, 1)), nz(s1)) and p_gt(nz(s1), nz(s20))),
                "long_bear": float(
                    not isna(s20) and p_lt(nz(hist(c, i, 1)), nz(s1)) and p_lt(nz(s1), nz(s20))
                ),
                "dn_base": dn_base,
                "dn_absorb": float(not isna(dn_base) and p_le(dn[i], dn_base * 0.8)),
                "up_absorb": float(not isna(up_base) and p_le(up[i], up_base * 0.8)),
                "near_recent_low": float(
                    not isna(prior_lo) and p_le(lo[i], prior_lo + a[i] * 0.75)
                ),
                "hi_c_inv": window(c, i, 2, max),
                "lo_c3": window(c, i, 3, min),
                "hi_c_dir": window(c, i, 5, max),
                "mb_eff_ratio": mb_ratio,
                "mb_sos": float(
                    p_ge((c[i] - mb_low) / unit, 2.0) and p_ge(mb_ratio, 1.1) and p_ge(c_pos, 0.5)
                ),
                "mb_sow": float(
                    p_ge((mb_high - c[i]) / unit, 2.0) and p_ge(mb_ratio, 1.1) and p_le(c_pos, 0.5)
                ),
                "res3_up": max(c[i] - nz(hist(c, i, 3), c[i]), 0.0) / unit,
                "sos_score": float(
                    p_ge(rel_e, 1.15)
                    + p_ge(spr_atr, 1.15)
                    + p_ge(c_pos, 0.65)
                    + (p_gt(c[i], o[i]) and p_ge(c[i] - o[i], a[i] * 0.5))
                ),
                "sow_score": float(
                    p_ge(rel_e, 1.15)
                    + p_ge(spr_atr, 1.15)
                    + p_le(c_pos, 0.35)
                    + (p_lt(c[i], o[i]) and p_ge(o[i] - c[i], a[i] * 0.5))
                ),
                "close2": nz(hist(c, i, 2), c[i]),
            }
        )
    return out


def lengths_schedule(n: int, seed: int) -> list[int | None]:
    """None (idle: the live length) and frozen campaign lengths 2-10, in runs."""
    rng = np.random.default_rng(seed)
    out: list[int | None] = []
    while len(out) < n:
        run = int(rng.integers(5, 120))
        value = None if rng.random() < 0.5 else int(rng.integers(2, 11))
        out += [value] * run
    return out[:n]


def synthetic_rows(seed: int, count: int, *, silent: int = 0) -> list[Row]:
    bars = synthetic_bars(
        "XAUUSD",
        start=datetime(2026, 1, 5, tzinfo=UTC),
        count=count,
        start_price=Decimal(2000),
        tick_size=Decimal("0.01"),
        timeframe=Timeframe.parse("15m"),
        seed=seed,
        volatility=0.003,
        regime_change_probability=0.02,
    )
    rows: list[Row] = []
    for i, b in enumerate(bars):
        volume = 0.0 if i < silent else float(b.volume)
        rows.append((float(b.open), float(b.high), float(b.low), float(b.close), volume))
    return rows


def streamed(rows: list[Row], lengths: list[int | None], mintick: float) -> list[Measures]:
    measures = BarMeasures(mintick)
    return [measures.update(i, 1e12 + i * 9e5, *row, lengths[i]) for i, row in enumerate(rows)]


def same(got: float, want: float) -> bool:
    if isna(want):
        return isna(got)
    return not isna(got) and math.isclose(got, want, rel_tol=1e-9, abs_tol=1e-9)


@pytest.mark.parametrize(("seed", "silent"), [(1, 0), (2, 0), (3, 120), (4, 0)])
def test_measures_match_the_transcription(seed: int, silent: int) -> None:
    rows = synthetic_rows(seed, 900, silent=silent)
    lengths = lengths_schedule(len(rows), seed)
    want = reference(rows, lengths, 0.01)
    got = streamed(rows, lengths, 0.01)
    pivots = 0
    for i, (g, w) in enumerate(zip(got, want, strict=True)):
        for name, value in w.items():
            assert same(float(getattr(g, name)), value), (i, name, getattr(g, name), value)
        pivots += int(not isna(w["ph"])) + int(not isna(w["pl"]))
    assert pivots > 50  # the comparison is not vacuous
    assert {w["live_len"] for w in want} >= {3, 4, 5}
    assert any(w["trend_score"] <= -15 for w in want) and any(w["trend_score"] >= 15 for w in want)


def test_effort_falls_back_to_the_range_only_while_no_volume_has_traded() -> None:
    """L1063-1066: ``noVol = ta.cum(nz(volume)) <= 0`` — all or nothing: once any volume
    has traded, a bar without volume is zero effort, not its range (spec D9)."""
    rows: list[Row] = [
        (100.0, 101.0, 99.0, 100.5, 0.0),
        (100.5, 101.5, 100.0, 101.0, 0.0),
        (101.0, 102.0, 100.5, 101.5, 50.0),
        (101.5, 102.5, 101.0, 102.0, 0.0),
    ]
    got = streamed(rows, [None] * 4, 0.01)
    assert [m.no_vol for m in got] == [True, True, False, False]
    assert [m.eff for m in got] == [2.0, 1.5, 50.0, 0.0]


def test_the_pivot_snapshot_reads_the_pivot_bar() -> None:
    """pTime, pEff, pSpr, pCPos (L1108-1114) are the values of the bar pLen bars back."""
    rows = synthetic_rows(5, 300)
    lengths: list[int | None] = [None] * 150 + [7] * 150
    got = streamed(rows, lengths, 0.01)
    m = got[200]
    assert m.p_len == 7 and m.piv_bar == 193
    _, h, low, c, v = rows[193]
    assert m.p_time == 1e12 + 193 * 9e5
    assert m.p_eff == v and m.p_spr == pytest.approx(h - low)
    assert m.p_c_pos == pytest.approx((c - low) / (h - low))
