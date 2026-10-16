"""Straightforward whole-array reference implementations of the Pine semantics.

They are written from the Pine definitions (docs/14), not from the streaming
classes: windows are sliced, extremes found with ``max``/``index``, EMAs
evaluated in closed form, and the reference Pine functions (``pine_dmi``,
``pine_sar``, ``pine_supertrend``) transcribed with ``x[k]`` array look-ups.
The property tests compare the streaming objects with them on random input.
"""

import math
from collections.abc import Sequence

import numpy as np

NAN = math.nan
EPS = 1e-10


def isna(x: float) -> bool:
    return not math.isfinite(x)


def at(xs: Sequence[float], t: int, k: int = 0) -> float:
    """Pine ``xs[k]`` evaluated on bar ``t`` (na before the first bar)."""
    return xs[t - k] if t - k >= 0 else NAN


def defined(xs: Sequence[float]) -> list[int]:
    return [i for i, x in enumerate(xs) if not isna(x)]


# ── na-compacted windows ─────────────────────────────────────────────────────────────


def ref_sum(xs: Sequence[float], n: int) -> list[float]:
    out = [NAN] * len(xs)
    positions = defined(xs)
    for j, i in enumerate(positions):
        if j + 1 >= n:
            out[i] = math.fsum(xs[k] for k in positions[j - n + 1 : j + 1])
    return out


def ref_sma(xs: Sequence[float], n: int) -> list[float]:
    return [s / n for s in ref_sum(xs, n)]


def _closed_form(xs: Sequence[float], n: int, alpha: float) -> list[float]:
    """seed = mean of the first n defined values; e_j = (1-a)^k seed + Σ a (1-a)^(j-m) y_m."""
    out = [NAN] * len(xs)
    positions = defined(xs)
    ys = [xs[i] for i in positions]
    if len(ys) < n:
        return out
    seed = math.fsum(ys[:n]) / n
    keep = 1.0 - alpha
    for j in range(n - 1, len(ys)):
        terms = [keep ** (j - n + 1) * seed]
        terms.extend(alpha * keep ** (j - m) * ys[m] for m in range(n, j + 1))
        out[positions[j]] = math.fsum(terms)
    return out


def ref_ema(xs: Sequence[float], n: int) -> list[float]:
    return _closed_form(xs, n, 2.0 / (n + 1))


def ref_rma(xs: Sequence[float], n: int) -> list[float]:
    return _closed_form(xs, n, 1.0 / n)


def ref_variance(xs: Sequence[float], n: int, biased: bool) -> list[float]:
    out = [NAN] * len(xs)
    positions = defined(xs)
    for j, i in enumerate(positions):
        if j + 1 >= n and (biased or n > 1):
            window = np.array([xs[k] for k in positions[j - n + 1 : j + 1]])
            out[i] = float(np.var(window, ddof=0 if biased else 1))
    return out


# ── extremes and pivots ──────────────────────────────────────────────────────────────


def ref_extreme(
    xs: Sequence[float], lengths: Sequence[int], is_max: bool, offset: bool
) -> list[float]:
    """Window = last n bars, cut at the last na; oldest of equal extremes."""
    out: list[float] = []
    last_na = -1
    for t, x in enumerate(xs):
        n = lengths[t]
        if isna(x):
            last_na = t
        if t < n - 1:
            out.append(NAN)
            continue
        if isna(x):
            out.append(0.0 if offset else NAN)
            continue
        start = max(t - n + 1, last_na + 1)
        window = list(xs[start : t + 1])
        best = max(window) if is_max else min(window)
        first = start + window.index(best)
        out.append(float(first - t) if offset else best)
    return out


def ref_pivot(
    xs: Sequence[float], lefts: Sequence[int], rights: Sequence[int], is_high: bool
) -> list[float]:
    """Pivot value >= every left value and > every right value (mirrored for lows)."""
    out: list[float] = []
    last_na = -1
    for t, x in enumerate(xs):
        left, right = lefts[t], rights[t]
        if isna(x):
            last_na = t
            out.append(NAN)
            continue
        center = t - right
        start = max(t - left - right, last_na + 1)
        if t < left + right or center < start:
            out.append(NAN)
            continue
        v = xs[center]
        before, after = xs[start:center], xs[center + 1 : t + 1]
        if is_high:
            ok = all(v >= y for y in before) and all(v > y for y in after)
        else:
            ok = all(v <= y for y in before) and all(v < y for y in after)
        out.append(v if ok else NAN)
    return out


# ── crosses and series helpers ───────────────────────────────────────────────────────


def ref_crossover(a: Sequence[float], b: Sequence[float], under: bool = False) -> list[bool]:
    out: list[bool] = []
    previous: tuple[float, float] | None = None
    for x, y in zip(a, b, strict=True):
        if isna(x) or isna(y):
            out.append(False)
            continue
        if previous is None:
            out.append(False)
        elif under:
            out.append(x < y and previous[0] >= previous[1])
        else:
            out.append(x > y and previous[0] <= previous[1])
        previous = (x, y)
    return out


def ref_cross(a: Sequence[float], b: Sequence[float]) -> list[bool]:
    out: list[bool] = []
    differences: list[float] = []
    for x, y in zip(a, b, strict=True):
        if isna(x) or isna(y):
            out.append(False)
            continue
        side = 0
        for d in reversed(differences):
            if abs(d) > EPS:
                side = 1 if d > 0 else -1
                break
        out.append((side < 0 and x > y) or (side > 0 and x < y))
        differences.append(x - y)
    return out


def ref_change(xs: Sequence[float], n: int) -> list[float]:
    return [
        xs[t] - xs[t - n] if t >= n and not isna(xs[t]) and not isna(xs[t - n]) else NAN
        for t in range(len(xs))
    ]


# ── volatility and oscillators ───────────────────────────────────────────────────────


def ref_tr(
    h: Sequence[float], low: Sequence[float], c: Sequence[float], handle_na: bool
) -> list[float]:
    out = []
    for t in range(len(h)):
        pc = at(c, t, 1)
        if isna(pc):
            out.append(h[t] - low[t] if handle_na else NAN)
        else:
            out.append(max(h[t] - low[t], abs(h[t] - pc), abs(low[t] - pc)))
    return out


def ref_atr(h: Sequence[float], low: Sequence[float], c: Sequence[float], n: int) -> list[float]:
    return ref_rma(ref_tr(h, low, c, handle_na=True), n)


def ref_rsi(xs: Sequence[float], n: int) -> list[float]:
    out = [NAN] * len(xs)
    positions = defined(xs)
    ys = [xs[i] for i in positions]
    ups = [NAN] + [max(ys[j] - ys[j - 1], 0.0) for j in range(1, len(ys))]
    downs = [NAN] + [max(ys[j - 1] - ys[j], 0.0) for j in range(1, len(ys))]
    for j, (u, d) in enumerate(zip(ref_rma(ups, n), ref_rma(downs, n), strict=True)):
        if isna(u) or isna(d):
            continue
        out[positions[j]] = 100.0 if d <= EPS else 0.0 if u <= EPS else 100 - 100 / (1 + u / d)
    return out


def ref_wavetrend(
    src: Sequence[float], n1: int, n2: int, signal: int
) -> tuple[list[float], list[float]]:
    esa = ref_ema(src, n1)
    de = ref_ema([abs(s - e) for s, e in zip(src, esa, strict=True)], n1)
    ci = [
        (s - e) / (0.015 * d) if not isna(d) and abs(d) > EPS else 0.0
        for s, e, d in zip(src, esa, de, strict=True)
    ]
    wt1 = ref_ema(ci, n2)
    return wt1, ref_sma(wt1, signal)


# ── reference Pine functions, transcribed ────────────────────────────────────────────


def _fixnan(xs: Sequence[float]) -> list[float]:
    out, last = [], NAN
    for x in xs:
        if not isna(x):
            last = x
        out.append(last)
    return out


def ref_dmi(
    h: Sequence[float], low: Sequence[float], c: Sequence[float], n: int, smooth: int
) -> tuple[list[float], list[float], list[float]]:
    size = len(h)
    up = [at(h, t) - at(h, t, 1) for t in range(size)]
    down = [-(at(low, t) - at(low, t, 1)) for t in range(size)]
    plus_dm = [
        NAN if isna(u) else (u if u - d > EPS and u > EPS else 0.0)
        for u, d in zip(up, down, strict=True)
    ]
    minus_dm = [
        NAN if isna(d) else (d if d - u > EPS and d > EPS else 0.0)
        for u, d in zip(up, down, strict=True)
    ]
    trur = ref_rma(ref_tr(h, low, c, handle_na=False), n)

    def ratio(xs: list[float]) -> list[float]:
        return [
            100 * x / r if not isna(x) and not isna(r) and r != 0 else NAN
            for x, r in zip(xs, trur, strict=True)
        ]

    plus = _fixnan(ratio(ref_rma(plus_dm, n)))
    minus = _fixnan(ratio(ref_rma(minus_dm, n)))
    adx_in = []
    for p, m in zip(plus, minus, strict=True):
        total = p + m
        adx_in.append(abs(p - m) / (1.0 if abs(total) <= EPS else total))
    adx = [100 * x for x in ref_rma(adx_in, smooth)]
    return plus, minus, adx


def ref_sar(
    h: Sequence[float],
    low: Sequence[float],
    c: Sequence[float],
    start: float,
    inc: float,
    maximum: float,
) -> list[float]:
    """``pine_sar`` from the Pine reference manual, with ``x[k]`` as array look-ups."""
    out: list[float] = []
    result = max_min = acceleration = NAN
    is_below: bool | None = None
    for t in range(len(h)):
        if t == 0:
            out.append(NAN)
            continue
        first_trend_bar = False
        if t == 1:
            if c[t] > c[t - 1]:
                is_below, max_min, result = True, h[t], low[t - 1]
            else:
                is_below, max_min, result = False, low[t], h[t - 1]
            first_trend_bar = True
            acceleration = start
        result = result + acceleration * (max_min - result)
        if is_below:
            if result > low[t]:
                first_trend_bar, is_below = True, False
                result, max_min, acceleration = max(h[t], max_min), low[t], start
        elif result < h[t]:
            first_trend_bar, is_below = True, True
            result, max_min, acceleration = min(low[t], max_min), h[t], start
        if not first_trend_bar:
            if is_below and h[t] > max_min:
                max_min, acceleration = h[t], min(acceleration + inc, maximum)
            elif not is_below and low[t] < max_min:
                max_min, acceleration = low[t], min(acceleration + inc, maximum)
        if is_below:
            result = min(result, low[t - 1])
            if t > 1:
                result = min(result, low[t - 2])
        else:
            result = max(result, h[t - 1])
            if t > 1:
                result = max(result, h[t - 2])
        out.append(result)
    return out


def _nz(x: float) -> float:
    return 0.0 if isna(x) else x


def ref_supertrend(
    h: Sequence[float], low: Sequence[float], c: Sequence[float], factor: float, period: int
) -> tuple[list[float], list[int]]:
    """``pine_supertrend`` from the Pine reference manual, with arrays for the bands."""
    atr = ref_atr(h, low, c, period)
    lower: list[float] = []
    upper: list[float] = []
    line: list[float] = []
    direction: list[int] = []
    for t in range(len(h)):
        src = (h[t] + low[t]) / 2
        up, lo = src + factor * atr[t], src - factor * atr[t]
        prev_lo, prev_up = _nz(at(lower, t, 1)), _nz(at(upper, t, 1))
        prev_close = at(c, t, 1)
        lo = lo if (lo > prev_lo or prev_close < prev_lo) else prev_lo
        up = up if (up < prev_up or prev_close > prev_up) else prev_up
        if isna(at(atr, t, 1)):
            d = 1
        elif at(line, t, 1) == prev_up:
            d = -1 if c[t] > up else 1
        else:
            d = 1 if c[t] < lo else -1
        lower.append(lo)
        upper.append(up)
        direction.append(d)
        line.append(lo if d == -1 else up)
    return line, direction


def ref_vwap(
    src: Sequence[float], volume: Sequence[float], anchor: Sequence[bool]
) -> tuple[list[float], list[float]]:
    vwap, stdev = [], []
    last_anchor = -1
    for t, s in enumerate(src):
        if isna(s):
            vwap.append(NAN)
            stdev.append(NAN)
            continue
        if anchor[t]:
            last_anchor = t
        if last_anchor < 0:
            vwap.append(NAN)
            stdev.append(NAN)
            continue
        bars = [k for k in range(last_anchor, t + 1) if not isna(src[k])]
        vol = math.fsum(volume[k] for k in bars)
        if isna(vol) or vol == 0:
            vwap.append(NAN)
            stdev.append(NAN)
            continue
        mean = math.fsum(src[k] * volume[k] for k in bars) / vol
        square = math.fsum(src[k] * src[k] * volume[k] for k in bars) / vol
        vwap.append(mean)
        stdev.append(math.sqrt(max(0.0, square - mean * mean)))
    return vwap, stdev


# ── comparison ───────────────────────────────────────────────────────────────────────


def assert_series_close(
    actual: Sequence[float], expected: Sequence[float], tol: float = 1e-9
) -> None:
    """Element-wise equality where na == na and numbers agree within ``tol`` (abs + rel)."""
    assert len(actual) == len(expected), (len(actual), len(expected))
    for i, (a, e) in enumerate(zip(actual, expected, strict=True)):
        if isna(e):
            assert isna(a), f"bar {i}: expected na, got {a!r}"
        else:
            assert not isna(a), f"bar {i}: expected {e!r}, got na"
            assert abs(a - e) <= tol * max(1.0, abs(e)), f"bar {i}: {a!r} != {e!r}"
