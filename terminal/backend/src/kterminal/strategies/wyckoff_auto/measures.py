"""The per-bar series of script 6's ``f_engine`` (L1062-1159): effort, ATR, swing pivots,
prior trend, extremes and the strength scores, computed before the campaign logic.

``f_engine`` runs on every chart bar (L1795), so every ``ta.*`` call inside it sees every
bar: each call site is one streaming object of ``kterminal.indicators`` updated once per
bar, in ``BarMeasures.update``. Calls that are textually different but identical in
source and length (``ta.highest(close, 3)`` is ``hiCDep``, ``hiCA``, ``hiCConf`` and
``hiCFail``, L1138-1147) return the same value on every bar and share one object.

Comparisons use the Pine helpers (``gt``/``ge``/``lt``/``le``): Pine compares floats with a
1e-10 tolerance and any comparison with na is false (docs/14 §14.3).
"""

import math
from dataclasses import dataclass

from kterminal.indicators import (
    Atr,
    Cum,
    Highest,
    History,
    Lowest,
    PivotHigh,
    PivotLow,
    Sma,
    Sum,
    ge,
    gt,
    le,
    lt,
    na,
    nz,
    pine_round,
)
from kterminal.strategies.wyckoff_auto.thresholds import (
    ADAPTIVE_SWING_MAX,
    ADAPTIVE_SWING_MIN,
    ADAPTIVE_SWING_VOL_LEN,
    ATR_LEN,
    CLIMAX_ABSORPTION_MIN_BARS,
    CONTINUATION_TREND_LEN,
    DIRECT_ACCEPTANCE_BARS,
    EXTREME_LEN,
    HISTORY_DEPTH,
    PHASE_D_FAIL_BARS,
    PIVOT_LEN,
    PRELIM_EFFICIENCY_LOOKBACK,
    PRELIM_EFFICIENCY_RATIO,
    PRELIM_EXTREME_ATR,
    PRIOR_TREND_MAX_BARS,
    PRIOR_TREND_NEUTRAL,
    PRIOR_TREND_PIVOT_FACTOR,
    PRIOR_TREND_STRONG,
    SOS_CLOSE_MIN,
    SOS_MULTI_BAR_ATR,
    SOS_MULTI_BAR_EFFORT,
    SOS_MULTI_BAR_LEN,
    SOW_CLOSE_MAX,
    STRENGTH_SPREAD_ATR,
    STRENGTH_VOL_MULT,
    STRUCTURE_INVALIDATION_BARS,
    TREND_LEN,
    VOL_LEN,
)


def pmax(a: float, b: float) -> float:
    """Pine ``math.max``: na when either argument is na (Python's ``max`` is order-dependent)."""
    if na(a) or na(b):
        return math.nan
    return a if a >= b else b


def pmin(a: float, b: float) -> float:
    """Pine ``math.min``: na when either argument is na."""
    if na(a) or na(b):
        return math.nan
    return a if a <= b else b


def clamp(value: float, lo: float, hi: float) -> float:
    """``f_clamp`` (L561-562)."""
    return pmax(lo, pmin(hi, value))


def pine_int_round(value: float) -> int:
    """``int(math.round(x))`` for the script's non-negative arguments (ties go up, L657,
    L667, L1087, L1117-1118): Python's ``round`` would send 4.5 to 4."""
    return int(pine_round(value))


@dataclass(slots=True)
class Measures:
    """One bar's values of L1062-1159, with the Pine names in the comments."""

    bar_index: int
    time: float  # time: the bar's open, ms since the epoch
    open: float
    high: float
    low: float
    close: float
    raw_vol: float  # rawVol = nz(volume)
    no_vol: bool  # noVol = ta.cum(rawVol) <= 0
    spr: float  # spr = max(high - low, mintick)
    eff: float  # eff = noVol ? spr : rawVol
    avg_eff_raw: float  # avgEffRaw = ta.sma(eff, volLen)
    avg_eff: float  # avgEff = nz(avgEffRaw, eff)
    avg_eff_prev: float  # avgEffPrev = nz(avgEffRaw[1], avgEff)
    atr_raw: float  # atrRaw = ta.atr(atrLen)
    a: float  # a = nz(atrRaw, spr)
    a_prev: float  # aPrev = nz(atrRaw[1], a)
    unit: float  # unit = max(a, mintick)
    c_pos: float  # cPos = (close - low) / spr
    rel_e: float  # relE = eff / max(avgEff, 1e-10)
    spr_atr: float  # sprATR = spr / unit
    recent_eff: float  # recentEff = ta.sma(eff, 3)
    recent_low: float  # recentLow = ta.lowest(low, 3)
    recent_high: float  # recentHigh = ta.highest(high, 3)
    prior_lo: float  # priorLo = ta.lowest(low, extremeLen)[1]
    prior_hi: float  # priorHi = ta.highest(high, extremeLen)[1]
    eff_hi_prior: float  # effHiPrior = ta.highest(eff, extremeLen)[1]
    new_low: bool  # newLow
    new_high: bool  # newHigh
    a_base: float  # aBase = ta.sma(a, adaptiveSwingVolLen)
    a_ratio: float  # aRatio
    adapt_len: int  # adaptLen
    live_len: int  # liveLen
    pre_len: int  # preLen = nz(liveLen[3], liveLen)
    p_len: int  # pLen: the campaign's frozen length, or liveLen when idle (L1105)
    ph: float  # ph = ta.pivothigh(high, pLen, pLen)
    pl: float  # pl = ta.pivotlow(low, pLen, pLen)
    piv_bar: int  # pivBar = bar_index - pLen
    p_a: float  # pA = max(nz(atrRaw[pLen], a), mintick)
    p_eff: float  # pEff
    p_spr: float  # pSpr
    p_c_pos: float  # pCPos
    p_avg_eff: float  # pAvgEff
    p_time: float  # pTime = time[pLen]
    long_sma: float  # longSma = ta.sma(close, continuationTrendLen)
    trend_bars: int  # trendBars
    trend_end: int  # trendEnd
    trend_score: float  # trendScore = f_priorTrendScore(...)
    down_trend: bool  # downTrend
    up_trend: bool  # upTrend
    strong_trend: bool  # strongTrend
    long_bull: bool  # longBull
    long_bear: bool  # longBear
    dn_effc: float  # dnEffc
    up_effc: float  # upEffc
    dn_base: float  # dnBase = ta.sma(dnEffc, 10)[1]
    up_base: float  # upBase
    dn_absorb: bool  # dnAbsorb
    up_absorb: bool  # upAbsorb
    near_recent_low: bool  # nearRecentLow
    near_recent_high: bool  # nearRecentHigh
    hi_c_inv: float  # hiCInv = ta.highest(close, 2)
    lo_c_inv: float  # loCInv = ta.lowest(close, 2)
    hi_c3: float  # hiCDep = hiCA = hiCConf = hiCFail = ta.highest(close, 3)
    lo_c3: float  # loCDep = loCA = loCConf = loCFail = ta.lowest(close, 3)
    hi_c_dir: float  # hiCDir = ta.highest(close, 5)
    lo_c_dir: float  # loCDir = ta.lowest(close, 5)
    mb_low: float  # mbLow = ta.lowest(low, 5)
    mb_high: float  # mbHigh = ta.highest(high, 5)
    mb_eff_ratio: float  # mbEffRatio
    mb_sos: bool  # mbSOS
    mb_sow: bool  # mbSOW
    res3_up: float  # res3Up
    res3_dn: float  # res3Dn
    sos_score: int  # sosScore
    sow_score: int  # sowScore
    close1: float  # close1 = nz(close[1], close)
    close2: float  # close2 = nz(close[2], close)


class BarMeasures:
    """The streaming state behind :class:`Measures`: one object per Pine call site."""

    __slots__ = (
        "_a",
        "_a_base",
        "_atr",
        "_atr_raw",
        "_avg_eff",
        "_avg_eff_raw",
        "_close",
        "_cum_vol",
        "_dn_base",
        "_dn_base_prev",
        "_eff",
        "_eff_hi",
        "_eff_hi_prev",
        "_hi_c2",
        "_hi_c3",
        "_hi_c5",
        "_high",
        "_live_len",
        "_lo_c2",
        "_lo_c3",
        "_lo_c5",
        "_long_sma",
        "_low",
        "_mb_eff",
        "_mb_high",
        "_mb_low",
        "_ph",
        "_ph_hist",
        "_pl",
        "_pl_hist",
        "_prior_hi",
        "_prior_hi_prev",
        "_prior_lo",
        "_prior_lo_prev",
        "_recent_eff",
        "_recent_high",
        "_recent_low",
        "_sma_hist",
        "_time",
        "_up_base",
        "_up_base_prev",
        "mintick",
    )

    def __init__(self, mintick: float) -> None:
        self.mintick = mintick
        self._cum_vol = Cum()  # ta.cum(rawVol) (L1064)
        self._avg_eff = Sma(VOL_LEN)  # ta.sma(eff, volLen) (L1067)
        self._atr = Atr(ATR_LEN)  # ta.atr(atrLen) (L1070)
        self._recent_eff = Sma(CLIMAX_ABSORPTION_MIN_BARS)  # L1077
        self._recent_low = Lowest(CLIMAX_ABSORPTION_MIN_BARS)  # L1078
        self._recent_high = Highest(CLIMAX_ABSORPTION_MIN_BARS)  # L1079
        self._prior_lo = Lowest(EXTREME_LEN)  # L1080, read as [1]
        self._prior_hi = Highest(EXTREME_LEN)  # L1081
        self._eff_hi = Highest(EXTREME_LEN)  # L1082
        self._prior_lo_prev = math.nan
        self._prior_hi_prev = math.nan
        self._eff_hi_prev = math.nan
        self._a_base = Sma(ADAPTIVE_SWING_VOL_LEN)  # ta.sma(a, adaptiveSwingVolLen) (L1085)
        # ta.pivothigh/low(high/low, pLen, pLen) with a per-bar length 2-10 (L1106-1107)
        self._ph = PivotHigh(max_left=ADAPTIVE_SWING_MAX, max_right=ADAPTIVE_SWING_MAX)
        self._pl = PivotLow(max_left=ADAPTIVE_SWING_MAX, max_right=ADAPTIVE_SWING_MAX)
        self._long_sma = Sma(CONTINUATION_TREND_LEN)  # L1116
        self._dn_base = Sma(PRELIM_EFFICIENCY_LOOKBACK)  # L1129, read as [1]
        self._up_base = Sma(PRELIM_EFFICIENCY_LOOKBACK)  # L1130
        self._dn_base_prev = math.nan
        self._up_base_prev = math.nan
        self._hi_c2 = Highest(STRUCTURE_INVALIDATION_BARS)  # hiCInv (L1136)
        self._lo_c2 = Lowest(STRUCTURE_INVALIDATION_BARS)  # loCInv (L1137)
        self._hi_c3 = Highest(PHASE_D_FAIL_BARS)  # hiCDep, hiCA, hiCConf, hiCFail
        self._lo_c3 = Lowest(PHASE_D_FAIL_BARS)  # loCDep, loCA, loCConf, loCFail
        self._hi_c5 = Highest(DIRECT_ACCEPTANCE_BARS)  # hiCDir (L1144)
        self._lo_c5 = Lowest(DIRECT_ACCEPTANCE_BARS)  # loCDir (L1145)
        self._mb_low = Lowest(SOS_MULTI_BAR_LEN)  # L1148
        self._mb_high = Highest(SOS_MULTI_BAR_LEN)  # L1149
        self._mb_eff = Sum(SOS_MULTI_BAR_LEN)  # math.sum(eff, sosMultiBarLen) (L1150)
        # x[i] look-backs: x[pLen] (<= 10), x[3], longSma[20] and f_priorTrendScore's
        # close[e + n], a[e], ph[o], pl[o], longSma[e + n] (<= 88)
        self._time = History(HISTORY_DEPTH)
        self._high = History(HISTORY_DEPTH)
        self._low = History(HISTORY_DEPTH)
        self._close = History(HISTORY_DEPTH)
        self._eff = History(HISTORY_DEPTH)
        self._atr_raw = History(HISTORY_DEPTH)
        self._avg_eff_raw = History(HISTORY_DEPTH)
        self._a = History(HISTORY_DEPTH)
        self._ph_hist = History(HISTORY_DEPTH)
        self._pl_hist = History(HISTORY_DEPTH)
        self._sma_hist = History(HISTORY_DEPTH)
        self._live_len = History(4)  # liveLen[3]

    def update(
        self,
        bar_index: int,
        time: float,
        open_: float,
        high: float,
        low: float,
        close: float,
        volume: float,
        campaign_len: int | None,
    ) -> Measures:
        """One closed bar. ``campaign_len`` is ``s.pivLen`` while a campaign is active
        (``s.phase != PHASE_NONE``) and None otherwise: L1105's ``pLen``."""
        mintick = self.mintick
        # ── bar measurements (L1062-1089) ──
        raw_vol = nz(volume)
        no_vol = le(self._cum_vol.update(raw_vol), 0.0)
        spr = pmax(high - low, mintick)
        eff = spr if no_vol else raw_vol
        avg_eff_raw = self._avg_eff.update(eff)
        avg_eff_raw_prev = self._avg_eff_raw[0]  # avgEffRaw[1]: last bar's value
        avg_eff = nz(avg_eff_raw, eff)
        avg_eff_prev = nz(avg_eff_raw_prev, avg_eff)
        atr_raw = self._atr.update(high, low, close)
        atr_raw_prev = self._atr_raw[0]
        a = nz(atr_raw, spr)
        a_prev = nz(atr_raw_prev, a)
        unit = pmax(a, mintick)
        c_pos = (close - low) / spr
        rel_e = eff / pmax(avg_eff, 1e-10)
        spr_atr = spr / unit
        recent_eff = self._recent_eff.update(eff)
        recent_low = self._recent_low.update(low)
        recent_high = self._recent_high.update(high)
        prior_lo, prior_hi, eff_hi_prior = (
            self._prior_lo_prev,
            self._prior_hi_prev,
            self._eff_hi_prev,
        )
        self._prior_lo_prev = self._prior_lo.update(low)
        self._prior_hi_prev = self._prior_hi.update(high)
        self._eff_hi_prev = self._eff_hi.update(eff)
        new_low = not na(prior_lo) and le(low, prior_lo)
        new_high = not na(prior_hi) and ge(high, prior_hi)
        a_base = self._a_base.update(a)
        a_ratio = a / a_base if gt(nz(a_base), 0.0) else 1.0
        adapt_len = max(
            ADAPTIVE_SWING_MIN, min(ADAPTIVE_SWING_MAX, pine_int_round(PIVOT_LEN * a_ratio))
        )
        live_len = adapt_len  # swingModeInput == "ATR Adaptive" (L58, L1088)
        self._live_len.update(live_len)
        live_len_3 = self._live_len[3]
        pre_len = live_len if na(live_len_3) else int(live_len_3)

        # history for x[i] (this bar first, so h[i] is the value i bars ago)
        self._time.update(time)
        self._high.update(high)
        self._low.update(low)
        self._close.update(close)
        self._eff.update(eff)
        self._atr_raw.update(atr_raw)
        self._avg_eff_raw.update(avg_eff_raw)
        self._a.update(a)

        # ── swing pivots and their bar's snapshot (L1105-1114) ──
        p_len = live_len if campaign_len is None else campaign_len
        ph = self._ph.update(high, p_len, p_len)
        pl = self._pl.update(low, p_len, p_len)
        self._ph_hist.update(ph)
        self._pl_hist.update(pl)
        piv_bar = bar_index - p_len
        p_a = pmax(nz(self._atr_raw[p_len], a), mintick)
        p_eff = nz(self._eff[p_len], eff)
        p_high = nz(self._high[p_len], high)
        p_low = nz(self._low[p_len], low)
        p_spr = pmax(p_high - p_low, mintick)
        p_c_pos = (nz(self._close[p_len], close) - p_low) / p_spr
        p_avg_eff = nz(self._avg_eff_raw[p_len], avg_eff)
        p_time = nz(self._time[p_len], time)

        # ── prior trend (L1116-1124) ──
        long_sma = self._long_sma.update(close)
        self._sma_hist.update(long_sma)
        trend_bars = max(
            TREND_LEN,
            min(PRIOR_TREND_MAX_BARS, pine_int_round(live_len * PRIOR_TREND_PIVOT_FACTOR)),
        )
        trend_end = max(2, min(8, pine_int_round(live_len * 0.75)))
        trend_score = self._prior_trend_score(trend_bars, trend_end, a)
        down_trend = le(trend_score, -PRIOR_TREND_NEUTRAL)
        up_trend = ge(trend_score, PRIOR_TREND_NEUTRAL)
        strong_trend = ge(abs(trend_score), PRIOR_TREND_STRONG)
        close_1 = self._close[1]
        sma_1, sma_20 = self._sma_hist[1], self._sma_hist[20]
        long_bull = gt(nz(close_1), nz(sma_1)) and gt(nz(sma_1), nz(sma_20))
        long_bear = not na(sma_20) and lt(nz(close_1), nz(sma_1)) and lt(nz(sma_1), nz(sma_20))

        # ── preliminary support/supply efficiency (L1126-1134) ──
        effort2 = pmax(rel_e, 0.01) * pmax(spr_atr, 0.01)
        close1 = nz(close_1, close)
        dn_effc = pmax(close1 - close, 0.0) / unit / effort2
        up_effc = pmax(close - close1, 0.0) / unit / effort2
        dn_base, up_base = self._dn_base_prev, self._up_base_prev  # ta.sma(...)[1]
        self._dn_base_prev = self._dn_base.update(dn_effc)
        self._up_base_prev = self._up_base.update(up_effc)
        dn_absorb = not na(dn_base) and le(dn_effc, dn_base * PRELIM_EFFICIENCY_RATIO)
        up_absorb = not na(up_base) and le(up_effc, up_base * PRELIM_EFFICIENCY_RATIO)
        near_recent_low = not na(prior_lo) and le(low, prior_lo + a * PRELIM_EXTREME_ATR)
        near_recent_high = not na(prior_hi) and ge(high, prior_hi - a * PRELIM_EXTREME_ATR)

        # ── closes windows, multi-bar strength, scores (L1136-1158) ──
        hi_c_inv = self._hi_c2.update(close)
        lo_c_inv = self._lo_c2.update(close)
        hi_c3 = self._hi_c3.update(close)
        lo_c3 = self._lo_c3.update(close)
        hi_c_dir = self._hi_c5.update(close)
        lo_c_dir = self._lo_c5.update(close)
        mb_low = self._mb_low.update(low)
        mb_high = self._mb_high.update(high)
        mb_eff_ratio = self._mb_eff.update(eff) / pmax(avg_eff * SOS_MULTI_BAR_LEN, 1e-10)
        mb_sos = (
            ge((close - mb_low) / unit, SOS_MULTI_BAR_ATR)
            and ge(mb_eff_ratio, SOS_MULTI_BAR_EFFORT)
            and ge(c_pos, 0.50)
        )
        mb_sow = (
            ge((mb_high - close) / unit, SOS_MULTI_BAR_ATR)
            and ge(mb_eff_ratio, SOS_MULTI_BAR_EFFORT)
            and le(c_pos, 0.50)
        )
        close3 = nz(self._close[3], close)
        res3_up = pmax(close - close3, 0.0) / unit
        res3_dn = pmax(close3 - close, 0.0) / unit
        sos_score = (
            int(ge(rel_e, STRENGTH_VOL_MULT))
            + int(ge(spr_atr, STRENGTH_SPREAD_ATR))
            + int(ge(c_pos, SOS_CLOSE_MIN))
            + int(gt(close, open_) and ge(close - open_, a * 0.50))
        )
        sow_score = (
            int(ge(rel_e, STRENGTH_VOL_MULT))
            + int(ge(spr_atr, STRENGTH_SPREAD_ATR))
            + int(le(c_pos, SOW_CLOSE_MAX))
            + int(lt(close, open_) and ge(open_ - close, a * 0.50))
        )
        close2 = nz(self._close[2], close)

        return Measures(
            bar_index=bar_index,
            time=time,
            open=open_,
            high=high,
            low=low,
            close=close,
            raw_vol=raw_vol,
            no_vol=no_vol,
            spr=spr,
            eff=eff,
            avg_eff_raw=avg_eff_raw,
            avg_eff=avg_eff,
            avg_eff_prev=avg_eff_prev,
            atr_raw=atr_raw,
            a=a,
            a_prev=a_prev,
            unit=unit,
            c_pos=c_pos,
            rel_e=rel_e,
            spr_atr=spr_atr,
            recent_eff=recent_eff,
            recent_low=recent_low,
            recent_high=recent_high,
            prior_lo=prior_lo,
            prior_hi=prior_hi,
            eff_hi_prior=eff_hi_prior,
            new_low=new_low,
            new_high=new_high,
            a_base=a_base,
            a_ratio=a_ratio,
            adapt_len=adapt_len,
            live_len=live_len,
            pre_len=pre_len,
            p_len=p_len,
            ph=ph,
            pl=pl,
            piv_bar=piv_bar,
            p_a=p_a,
            p_eff=p_eff,
            p_spr=p_spr,
            p_c_pos=p_c_pos,
            p_avg_eff=p_avg_eff,
            p_time=p_time,
            long_sma=long_sma,
            trend_bars=trend_bars,
            trend_end=trend_end,
            trend_score=trend_score,
            down_trend=down_trend,
            up_trend=up_trend,
            strong_trend=strong_trend,
            long_bull=long_bull,
            long_bear=long_bear,
            dn_effc=dn_effc,
            up_effc=up_effc,
            dn_base=dn_base,
            up_base=up_base,
            dn_absorb=dn_absorb,
            up_absorb=up_absorb,
            near_recent_low=near_recent_low,
            near_recent_high=near_recent_high,
            hi_c_inv=hi_c_inv,
            lo_c_inv=lo_c_inv,
            hi_c3=hi_c3,
            lo_c3=lo_c3,
            hi_c_dir=hi_c_dir,
            lo_c_dir=lo_c_dir,
            mb_low=mb_low,
            mb_high=mb_high,
            mb_eff_ratio=mb_eff_ratio,
            mb_sos=mb_sos,
            mb_sow=mb_sow,
            res3_up=res3_up,
            res3_dn=res3_dn,
            sos_score=sos_score,
            sow_score=sow_score,
            close1=close1,
            close2=close2,
        )

    def _prior_trend_score(self, n_bars: int, end_off: int, a_now: float) -> float:
        """``f_priorTrendScore(trendBars, trendEnd, a, ph, pl, longSma)`` (L573-613): the
        trend into the bar ``end_off`` bars ago over ``n_bars`` bars, -100 … +100."""
        n = max(n_bars, 2)
        e = max(end_off, 0)
        close, ph, pl, sma = self._close, self._ph_hist, self._pl_hist, self._sma_hist
        c_end = close[e]
        c_start = close[e + n]
        score = 0.0
        if na(c_end) or na(c_start):
            return score
        unit_a = pmax(nz(self._a[e], a_now), self.mintick)
        net = c_end - c_start
        disp = clamp(net / (unit_a * math.sqrt(n)), -3.0, 3.0) * 15.0
        path = 0.0
        hh = ll = lh = hl = 0
        last_ph = math.nan
        last_pl = math.nan
        for k in range(n - 1, -1, -1):  # for k = n - 1 to 0: oldest bar first
            o = e + k
            c_o = nz(close[o])
            path += abs(c_o - nz(close[o + 1], c_o))
            vph = ph[o]
            vpl = pl[o]
            if not na(vph):
                if not na(last_ph):
                    hh += 1 if gt(vph, last_ph) else 0
                    lh += 1 if lt(vph, last_ph) else 0
                last_ph = vph
            if not na(vpl):
                if not na(last_pl):
                    hl += 1 if gt(vpl, last_pl) else 0
                    ll += 1 if lt(vpl, last_pl) else 0
                last_pl = vpl
        er = abs(net) / path if gt(path, 0.0) else 0.0
        er_part = (1.0 if ge(net, 0.0) else -1.0) * er * 25.0
        swings = hh + ll + lh + hl
        swing_part = float(hh + hl - lh - ll) / swings * 20.0 if swings > 0 else 0.0
        sma_end = sma[e]
        sma_start = sma[e + n]
        sma_part = 0.0
        if not na(sma_end) and not na(sma_start):
            sma_part = 10.0 if gt(sma_end, sma_start) else -10.0 if lt(sma_end, sma_start) else 0.0
        return clamp(disp + er_part + swing_part + sma_part, -100.0, 100.0)
