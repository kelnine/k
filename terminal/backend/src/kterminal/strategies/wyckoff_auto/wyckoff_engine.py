"""Script 6's Wyckoff campaign engine: ``f_engine`` (L1060-1764) on the chart timeframe.

One :class:`WyckoffEngine` per instrument runs the script's single chart-timeframe
campaign: climax detection (SC/BC) with the ATR-adaptive swing length, absorption, the
automatic rally/reaction (AR), secondary tests (ST) and Phase B opposite tests and
traversals, Spring/UTAD probes (pending, provisional, confirmed), Phase C tests and
terminal tests (C-Test), SOS/SOW promotion to Phase D, LPS/LPSY, Phase E acceptance, the
seven reset paths, the D→B demotion and the regime, then the Auto entry for the chosen
Entry Strictness (L1729-1747).

The code follows the script's order statement by statement; the comments give the Pine
line of each block. ``f_engine(barstate.isconfirmed)`` commits on closed bars only, and
the port sees closed bars only, so ``_commit`` is always true. The higher-timeframe
override (L1766-2008), the historical schematics and every drawing are not ported.

Pine's ``na`` is ``nan`` for floats and ``None`` for ints; float comparisons use the
tolerant Pine helpers (``gt``, ``ge``…, false with na) and ``int(math.round(x))`` is
:func:`pine_int_round` (ties up). Arithmetic keeps the script's operand order, so the
doubles round as TradingView's do.
"""

import math
from dataclasses import dataclass, field
from typing import Literal

from kterminal.indicators import ge, gt, le, lt, na, nz
from kterminal.strategies.wyckoff_auto.measures import (
    BarMeasures,
    Measures,
    pine_int_round,
    pmax,
    pmin,
)
from kterminal.strategies.wyckoff_auto.state import (
    BIT_AR,
    BIT_BC,
    BIT_CTEST,
    BIT_E,
    BIT_LPS,
    BIT_LPSY,
    BIT_PS,
    BIT_SC,
    BIT_SOS,
    BIT_SOW,
    BIT_SPRING,
    BIT_ST,
    BIT_TEST,
    BIT_UTAD,
    DIR_ACCUM,
    DIR_DIST,
    DIR_NONE,
    ENTRY_LPS,
    ENTRY_NONE,
    ENTRY_STRENGTH,
    ENTRY_TEST,
    EV_BC,
    EV_CTEST_ACC,
    EV_CTEST_DST,
    EV_LPS,
    EV_LPSY,
    EV_MARKDOWN,
    EV_MARKUP,
    EV_SC,
    EV_SOS,
    EV_SOW,
    EV_SPRING,
    EV_ST,
    EV_TEST,
    EV_UTAD,
    PHASE_A,
    PHASE_B,
    PHASE_C,
    PHASE_D,
    PHASE_E,
    PHASE_NONE,
    REGIME_MARKDOWN,
    REGIME_MARKUP,
    REGIME_NONE,
    RS_ABSORB,
    RS_DEMOTE,
    RS_DEPART,
    RS_EEND,
    RS_INVALID,
    RS_NORANGE,
    RS_STALE,
    TEST_FAILED,
    TEST_GOOD,
    TEST_NONE,
    TEST_POOR,
    TYPE_ACCUM,
    TYPE_DIST,
    TYPE_NONE,
    TYPE_REACCUM,
    TYPE_REDIST,
    WS,
    PivotTriplet,
)
from kterminal.strategies.wyckoff_auto.thresholds import (
    AR_MAX_EXTENSION_ATR,
    BC_CLOSE_MAX,
    BOUNDARY_TOL_ATR,
    BREAK_ATR,
    CLIMAX_ABSORPTION_EXTREME_ATR,
    CLIMAX_ABSORPTION_MAX_BARS,
    CLIMAX_ABSORPTION_MIN_BARS,
    CLIMAX_ABSORPTION_REBOUND_ATR,
    CLIMAX_ABSORPTION_VOL_FLOOR,
    CLIMAX_MIN_SCORE,
    CLIMAX_SPREAD_MULT,
    CLIMAX_VOL_MULT,
    CONFIRM_BARS,
    CONTINUATION_TREND_LEN,
    DIRECT_ACCEPTANCE_BARS,
    DIRECT_ACCEPTANCE_CONFIDENCE,
    ENTRY_MIN_CONFIDENCE_AGGRESSIVE,
    ENTRY_MIN_CONFIDENCE_CONSERVATIVE,
    ENTRY_MIN_CONFIDENCE_STANDARD,
    ENTRY_MIN_TESTS_AGGRESSIVE,
    ENTRY_MIN_TESTS_CONSERVATIVE,
    ENTRY_MIN_TESTS_STANDARD,
    EXCURSION_MIN_SCORE,
    EXCURSION_RECOVERY_BARS,
    EXTREME_LEN,
    LPS_BOUNDARY_ATR,
    LPS_MIN_SCORE,
    LPS_SPREAD_ATR,
    LPS_VOL_MULT,
    MAX_AR_BARS,
    MIN_AR_ATR,
    MIN_CONFIDENCE_PHASE_C,
    MIN_CONFIDENCE_PHASE_D,
    MIN_PHASE_B_BARS,
    MIN_PHASE_B_OPPOSITE_TESTS,
    MIN_PHASE_B_TESTS,
    MIN_PHASE_B_TRAVERSALS,
    OPPOSITE_CYCLE_MIN_BARS,
    PHASE_A_AFTER_AR_MAX_BARS,
    PHASE_A_MIN_BARS,
    PHASE_A_PREMATURE_DEPARTURE_ATR,
    PHASE_A_PREMATURE_DEPARTURE_TR_FRAC,
    PHASE_B_BAD_TEST_COOLDOWN_FACTOR,
    PHASE_B_DEPARTURE_ATR,
    PHASE_B_DEPARTURE_TR_FRAC,
    PHASE_B_EDGE_EXPANSION_CAP,
    PHASE_B_IDLE_MAX_BARS,
    PHASE_B_RANGE_MAX_ATR,
    PHASE_B_RANGE_MIN_ATR,
    PHASE_B_ZONE_FRAC,
    PHASE_C_IDLE_MAX_BARS,
    PHASE_C_TO_D_MIN_BARS,
    PHASE_D_DOMINANCE_FRAC,
    PHASE_D_MIN_BARS,
    PHASE_D_VALIDATION_MIN,
    PHASE_E_MAX_BARS,
    PIVOT_LEN,
    PRELIM_MIN_SCORE,
    PRELIM_VOL_MULT,
    PRIOR_TREND_MAX_BARS,
    PRIOR_TREND_NEUTRAL,
    PRIOR_TREND_STRONG,
    RELAXED_CLIMAX_FACTOR,
    SC_CLOSE_MIN,
    SOS_CLOSE_MIN,
    SOW_CLOSE_MAX,
    SPRING_CLOSE_MIN,
    SPRING_EFFORT_MAX_MULT,
    SPRING_MAX_PEN_ATR,
    SPRING_MIN_PEN_ATR,
    ST_MAX_SPREAD_RATIO,
    ST_MAX_VOL_RATIO,
    ST_MIN_SCORE,
    STRENGTH_MIN_SCORE,
    STRENGTH_VOL_MULT,
    STRUCTURE_INVALIDATION_ATR,
    TERMINAL_TEST_MIN_BARS_AFTER_ST,
    TERMINAL_TEST_OTHER_MAX_RATIO,
    TERMINAL_TEST_SPREAD_RATIO,
    TERMINAL_TEST_VOL_RATIO,
    TEST_EXTREME_TOLERANCE_ATR,
    TEST_MAX_SPREAD_RATIO,
    TEST_MAX_VOL_RATIO,
    TEST_MIN_SCORE,
    TEST_TOL_ATR,
    UTAD_CLOSE_MAX,
)

Strictness = Literal["Conservative", "Standard", "Aggressive"]
Detail = dict[str, float | int | bool | str | None]  # the values that decided an event

# Every reset reason the script counts (rsCounts, L1102) and the reseed.
RESEED = "RESEED"


# ── pure helpers (L614-702) ───────────────────────────────────────────────────────────────
def structure_confidence(
    prior: bool,
    climax: bool,
    ar: bool,
    st: bool,
    c_done: bool,
    strength: bool,
    lps: bool,
    accept: bool,
) -> int:
    """``f_structureConfidence`` (L615-616), 0-100."""
    return (
        (10 if prior else 0)
        + (15 if climax else 0)
        + (10 if ar else 0)
        + (15 if st else 0)
        + (15 if c_done else 0)
        + (15 if strength else 0)
        + (10 if lps else 0)
        + (10 if accept else 0)
    )


def validation_score(
    trend: float,
    absorbed: bool,
    range_atr: float,
    st: int,
    opp: int,
    trav: int,
    clean: bool,
    cause: float,
    terminal: bool,
    strength: bool,
    lps: bool,
    accept: bool,
) -> int:
    """``f_validationScore`` (L618-633), 0-100."""
    v = 0
    v += (
        10
        if ge(abs(trend), PRIOR_TREND_STRONG)
        else 5
        if ge(abs(trend), PRIOR_TREND_NEUTRAL)
        else 0
    )
    v += 15 if absorbed else 0
    if ge(range_atr, PHASE_B_RANGE_MIN_ATR) and le(range_atr, PHASE_B_RANGE_MAX_ATR):
        v += 10
    elif ge(range_atr, PHASE_B_RANGE_MIN_ATR * 0.75) and le(range_atr, PHASE_B_RANGE_MAX_ATR * 1.5):
        v += 5
    v += 15 if st >= MIN_PHASE_B_TESTS else 8 if st >= 1 else 0
    v += 15 if opp >= 1 and trav >= 2 else 8 if opp >= 1 or trav >= 1 else 0
    v += 10 if clean else 0
    v += 10 if ge(cause, 3.0) else 5 if ge(cause, 1.5) else 0
    v += 10 if terminal else 0
    v += 3 if strength else 0
    v += 2 if lps else 0
    return min(v, 100)


def cause_units(trav: int, b_age: int, p: int, range_atr: float) -> float:
    """``f_causeUnits`` (L635-638)."""
    time_units = float(b_age) / max(float(p) * 6.0, 1.0)
    width_bonus = 0.5 if ge(range_atr, PHASE_B_RANGE_MIN_ATR) else 0.0
    return time_units + float(trav) * 0.5 + width_bonus


def test_class(
    near: bool, holds: bool, close_ok: bool, e: float, sp: float, c_e: float, c_s: float
) -> int:
    """``f_testClass`` (L640-649): GOOD, POOR, FAILED or NONE."""
    r = TEST_NONE
    if near:
        if not holds:
            r = TEST_FAILED
        elif close_ok and le(e, c_e * ST_MAX_VOL_RATIO) and le(sp, c_s * ST_MAX_SPREAD_RATIO):
            r = TEST_GOOD
        else:
            r = TEST_POOR
    return r


def phase_a_min_bars(p: int) -> int:
    """``f_phaseAMinBars`` (L651-652)."""
    return max(PHASE_A_MIN_BARS, max(p, 1) * 2)


def phase_b_min_bars(p_in: int, range_atr: float) -> int:
    """``f_phaseBMinBars`` (L654-658)."""
    p = max(p_in, 1)
    raw = pine_int_round(pmax(float(p * 6), range_atr * float(p) * 1.00))
    return max(MIN_PHASE_B_BARS, min(raw, MIN_PHASE_B_BARS * 2))


def phase_c_to_d_min_bars(p: int) -> int:
    """``f_phaseCToDMinBars`` (L660-661): ``int(max(p, 1) / 2)`` truncates."""
    return max(PHASE_C_TO_D_MIN_BARS, max(p, 1) // 2)


def phase_d_min_bars(p: int) -> int:
    """``f_phaseDMinBars`` (L663-664)."""
    return max(PHASE_D_MIN_BARS, max(p, 1))


def excursion_recovery_limit(p: int) -> int:
    """``f_excursionRecoveryLimit`` (L666-667): ``round(6 * 0.75) = 5`` (Python: 4)."""
    return max(EXCURSION_RECOVERY_BARS, pine_int_round(max(p, 1) * 0.75))


def phase_idle_limit(phase: int, has_ar: bool, p_in: int) -> int | None:
    """``f_phaseIdleLimit`` (L669-680): bars without activity before RS_STALE; na in
    phases NONE and E."""
    p = max(p_in, 1)
    if phase == PHASE_A:
        return max(PHASE_A_AFTER_AR_MAX_BARS, p * 6) if has_ar else max(MAX_AR_BARS, p * 4)
    if phase == PHASE_B:
        return max(PHASE_B_IDLE_MAX_BARS, p * 20)
    if phase == PHASE_C:
        return max(PHASE_C_IDLE_MAX_BARS, p * 8)
    if phase == PHASE_D:
        return max(PHASE_C_IDLE_MAX_BARS * 2, p * 16)
    return None


def phase_b_character_improving(
    n: int, eff_sum: float, spr_sum: float, last_e: float, last_s: float
) -> bool:
    """``f_phaseBCharacterImproving`` (L682-688): the last good ST is quieter than average."""
    ok = False
    if n >= 2 and not na(last_e) and not na(last_s):
        avg_e = eff_sum / n
        avg_s = spr_sum / n
        ok = le(last_e, avg_e) and le(last_s, avg_s * 1.05)
    return ok


def robust_edge(e1: float, e2: float, e3: float, orig: float, is_low: bool) -> float:
    """``f_robustEdge`` (L690-698): the median of the last three tests, capped at the
    original edge."""
    med = math.nan
    if not na(e1) and not na(e2) and not na(e3):
        med = e1 + e2 + e3 - pmax(e1, pmax(e2, e3)) - pmin(e1, pmin(e2, e3))
    elif not na(e1) and not na(e2):
        med = ((e1 + e2) / 2.0 + orig) / 2.0
    elif not na(e1):
        med = (e1 + orig) / 2.0
    if na(med):
        return orig
    return pmax(orig, med) if is_low else pmin(orig, med)


def type_from(stop: int, out: int, bull: bool, bear: bool) -> int:
    """``f_typeFrom`` (L700-702): accumulation, re-accumulation, distribution or
    re-distribution."""
    if out == DIR_ACCUM:
        return TYPE_REACCUM if stop == DIR_DIST or bull else TYPE_ACCUM
    if out == DIR_DIST:
        return TYPE_REDIST if stop == DIR_ACCUM or bear else TYPE_DIST
    return TYPE_NONE


def bias_dir(s: WS) -> int:
    """``f_biasDir`` (L713-714)."""
    if s.stop_side == DIR_ACCUM:
        return DIR_DIST if s.ctx_bear else DIR_ACCUM
    if s.stop_side == DIR_DIST:
        return DIR_ACCUM if s.ctx_bull else DIR_DIST
    return DIR_NONE


def type_ws(s: WS) -> int:
    """``f_typeWS`` (L716-718)."""
    o = s.outcome if s.outcome != DIR_NONE else bias_dir(s)
    return (
        TYPE_NONE if s.stop_side == DIR_NONE else type_from(s.stop_side, o, s.ctx_bull, s.ctx_bear)
    )


def hard_level(s: WS, side: int) -> float:
    """``f_hardLevel`` (L723-729): the structure-invalidation level of a side — the
    Spring/UTAD extreme when the campaign has one for that outcome, else the more extreme
    of the original edge and the current range edge."""
    if side == DIR_ACCUM:
        if s.exc and s.outcome == DIR_ACCUM and not na(s.exc_price):
            return s.exc_price
        if na(s.orig_low):
            return s.range_low
        return pmin(s.orig_low, nz(s.range_low, s.orig_low))
    if s.exc and s.outcome == DIR_DIST and not na(s.exc_price):
        return s.exc_price
    if na(s.orig_high):
        return s.range_high
    return pmax(s.orig_high, nz(s.range_high, s.orig_high))


def confidence(s: WS) -> int:
    """``f_confWS`` (L932-934)."""
    c_done = s.cf_test or (s.cf_exc and s.cf_strength)
    return structure_confidence(
        s.cf_prior,
        s.cf_climax,
        s.cf_ar,
        s.cf_st,
        c_done,
        s.cf_strength,
        s.cf_lps,
        s.cf_accept,
    )


def _nz_int(value: int | None, replacement: int) -> int:
    return replacement if value is None else value


# ── what one bar did, for the strategy ────────────────────────────────────────────────────
@dataclass(slots=True)
class CampaignEnd:
    """A campaign retired (a reset, L1230-1234 / L1672-1676), demoted D→B (L1210-1218) or
    replaced by a new climax (L1265-1271) on this bar, with the values that decided it."""

    kind: str  # RS_INVALID … RS_EEND (state.RESET_NAMES) or RESEED
    serial: int
    phase: int  # the phase it was in
    outcome: int
    stop_side: int
    detail: Detail = field(default_factory=dict)


@dataclass(slots=True)
class EntryCheck:
    """The Auto entry evaluation (L1729-1747) on a bar that set a Test, C-Test, SOS/SOW or
    LPS/LPSY bit while the campaign had an outcome and no entry yet."""

    strictness: str
    direction: int  # the campaign outcome: ACCUM = long, DIST = short
    confidence: int
    min_confidence: int
    validation: int
    validation_floor: int
    readiness: int
    min_readiness: int
    quality: bool  # eQuality
    test_bit: bool
    strength_bit: bool
    lps_bit: bool
    triggers: list[str]  # the Pine trigger names that are true
    kind: int  # entryKind when taken, ENTRY_NONE otherwise

    @property
    def taken(self) -> bool:
        return bool(self.triggers)


@dataclass(slots=True)
class EngineStep:
    """One closed bar of the engine."""

    m: Measures
    sig: int  # the bar's event bits (cMask, L1764)
    serial: int  # the campaign alive after the bar
    ends: list[CampaignEnd] = field(default_factory=list)
    seeded: int = DIR_NONE  # side of a climax seeded on this bar (L1265)
    entry_check: EntryCheck | None = None


@dataclass(slots=True)
class _Turn:
    """Locals shared by the sections of one bar's commit block."""

    sig: int = 0
    probe_open: bool = False  # probeOpen (L1171)
    age_ok_bull: bool = True  # ageOKBull (L1175)
    age_ok_bear: bool = True  # ageOKBear (L1176)
    ends: list[CampaignEnd] = field(default_factory=list)
    seeded: int = DIR_NONE
    new_pl: bool = False  # newPL (L1319)
    new_ph: bool = False  # newPH (L1320)


class WyckoffEngine:
    """The chart-timeframe ``f_engine`` with its ``var`` state (L1091-1103)."""

    __slots__ = (
        "_serials",
        "last_ph_bar",
        "last_pl_bar",
        "last_reset_why",
        "measures",
        "mintick",
        "prelim_bar",
        "prelim_dir",
        "prelim_price",
        "prelim_score",
        "prelim_time",
        "regime",
        "regime_bar",
        "rs_counts",
        "s",
        "strictness",
        "tf_seconds",
    )

    def __init__(self, mintick: float, tf_seconds: float, strictness: Strictness) -> None:
        self.mintick = mintick
        self.tf_seconds = tf_seconds  # timeframe.in_seconds(timeframe.period)
        self.strictness: Strictness = strictness  # entryStrictness (L28)
        self.measures = BarMeasures(mintick)
        self._serials = 0
        self.s = self._new_ws()  # var WS s = WS.new() (L1091)
        self.regime = REGIME_NONE  # L1093
        self.regime_bar: int | None = None  # L1094
        self.prelim_bar: int | None = None  # L1095
        self.prelim_time = math.nan  # L1096
        self.prelim_price = math.nan  # L1097
        self.prelim_dir = DIR_NONE  # L1098
        self.prelim_score = 0  # L1099
        self.last_pl_bar: int | None = None  # L1100: survives resets
        self.last_ph_bar: int | None = None  # L1101
        self.rs_counts = [0] * 7  # rsCounts (L1102)
        self.last_reset_why = -1  # L1103

    def _new_ws(self) -> WS:
        """``WS.new()`` followed by ``f_initPivotHistory`` (L768-773)."""
        self._serials += 1
        return WS(st_hist=PivotTriplet(), op_hist=PivotTriplet(), serial=self._serials)

    # ── one bar ───────────────────────────────────────────────────────────────────────────
    def update(
        self,
        bar_index: int,
        time: float,
        open_: float,
        high: float,
        low: float,
        close: float,
        volume: float,
    ) -> EngineStep:
        s = self.s
        campaign_len = s.piv_len if s.phase != PHASE_NONE else None  # pLen (L1105)
        m = self.measures.update(bar_index, time, open_, high, low, close, volume, campaign_len)
        t = _Turn()
        self._retire(m, t)  # L1164-1234
        self._seed(m, t)  # L1236-1275
        self._phase_a(m, t)  # L1277-1311
        self._pivots(m, t)  # L1313-1475
        self._tests_and_lps(m, t)  # L1477-1529
        p2, r_h2, r_l2, mature2 = self._probes(m, t)  # L1531-1610
        self._promote(m, t, p2, r_h2, r_l2)  # L1612-1641
        self._depart(m, t, p2, r_h2, r_l2, mature2)  # L1643-1676
        self._re_sos(m, t)  # L1678-1693
        self._accept(m, t)  # L1695-1727
        check = self._entry(m, t)  # L1729-1747
        return EngineStep(
            m=m,
            sig=t.sig,
            serial=self.s.serial,
            ends=t.ends,
            seeded=t.seeded,
            entry_check=check,
        )

    # ── campaign helpers that read the bar (L705-930) ─────────────────────────────────────
    def _set_event(self, s: WS, ev: int, m: Measures) -> None:
        """``f_setEvent`` (L705-711)."""
        s.ev = ev
        s.last_event_bar = m.bar_index
        s.last_event_time = m.time
        s.last_event_price = m.close
        s.last_act_bar = m.bar_index

    def range_atr(self, s: WS, atr_now: float) -> float:
        """``f_rangeATRWS`` (L720-721): range height in climax ATRs, 0 without a range."""
        if na(s.range_high) or na(s.range_low):
            return 0.0
        return abs(s.range_high - s.range_low) / pmax(nz(s.climax_atr, atr_now), self.mintick)

    def _seed_ws(
        self,
        s: WS,
        side: int,
        score: int,
        p_len: int,
        trend: float,
        bull: bool,
        bear: bool,
        m: Measures,
    ) -> None:
        """``f_seed`` (L731-753)."""
        s.stop_side = side
        s.phase = PHASE_A
        s.start_bar = m.bar_index
        s.piv_len = p_len
        s.birth_trend = trend
        s.ctx_bull = bull
        s.ctx_bear = bear
        s.climax_bar = m.bar_index
        s.climax_time = m.time
        s.climax_price = m.low if side == DIR_ACCUM else m.high
        s.climax_eff = m.eff
        s.climax_spr = m.spr
        s.climax_atr = m.a
        s.climax_score = score
        if side == DIR_ACCUM:
            s.orig_low = m.low
            s.range_low = m.low
        else:
            s.orig_high = m.high
            s.range_high = m.high
        s.cf_prior = True
        self._set_event(s, EV_SC if side == DIR_ACCUM else EV_BC, m)

    @staticmethod
    def _freeze_ar(s: WS) -> None:
        """``f_freezeAR`` (L755-766)."""
        s.ar_bar = s.ar_run_bar
        s.ar_time = s.ar_run_time
        s.ar_price = s.ar_run_price
        s.cf_ar = True
        if s.stop_side == DIR_ACCUM:
            s.orig_high = s.ar_run_price
            s.range_high = s.ar_run_price
        else:
            s.orig_low = s.ar_run_price
            s.range_low = s.ar_run_price

    def _register_st(
        self,
        s: WS,
        price: float,
        t: float,
        pb: int,
        e: float,
        sp: float,
        score: int,
        m: Measures,
    ) -> None:
        """``f_registerST`` (L775-807): a climax-side test; the range edge becomes the
        robust median of the last three tests."""
        s.st_count = s.st_count + 1
        s.st_n = s.st_n + 1
        s.st_eff_sum = s.st_eff_sum + e
        s.st_spr_sum = s.st_spr_sum + sp
        s.last_good_eff = e
        s.last_good_spr = sp
        s.st_bar = pb
        s.st_time = t
        s.st_price = price
        hist = s.st_hist if s.st_hist is not None else PivotTriplet()
        s.st_hist = hist
        _push_triplet(hist, pb, t, price)
        s.st_score = score
        s.edge3 = s.edge2
        s.edge2 = s.edge1
        s.edge1 = price
        if s.stop_side == DIR_ACCUM:
            s.range_low = robust_edge(s.edge1, s.edge2, s.edge3, s.orig_low, True)
        else:
            s.range_high = robust_edge(s.edge1, s.edge2, s.edge3, s.orig_high, False)
        s.cf_st = True
        self._set_event(s, EV_ST, m)

    @staticmethod
    def _register_opp(
        s: WS, price: float, t: float, pb: int, e: float, sp: float, bar_index: int
    ) -> None:
        """``f_registerOpp`` (L809-830): a test of the opposite edge."""
        s.opp_count = s.opp_count + 1
        s.op_n = s.op_n + 1
        s.op_eff_sum = s.op_eff_sum + e
        s.op_spr_sum = s.op_spr_sum + sp
        s.op_last_bar = pb
        s.op_last_price = price
        hist = s.op_hist if s.op_hist is not None else PivotTriplet()
        s.op_hist = hist
        _push_triplet(hist, pb, t, price)
        s.last_act_bar = bar_index

    @staticmethod
    def _clear_terminal(s: WS) -> None:
        """``f_clearTerminal`` (L832-848)."""
        s.exc = False
        s.exc_tested = False
        s.exc_bar = None
        s.exc_price = math.nan
        s.exc_time = math.nan
        s.exc_eff = math.nan
        s.exc_spr = math.nan
        s.exc_score = 0
        s.test_time = math.nan
        s.test_price = math.nan
        s.test_score = 0
        s.cf_exc = False
        s.cf_test = False
        s.c_ready_bar = None
        s.c_start_time = math.nan

    def _exc_from_pend(self, s: WS, score: int, m: Measures) -> None:
        """``f_excFromPend`` (L850-866): the pending probe becomes the Spring/UTAD."""
        s.exc = True
        s.exc_tested = False
        s.exc_bar = s.pend_ext_bar
        s.exc_price = s.pend_ext
        s.exc_time = s.pend_ext_time
        s.exc_eff = s.pend_eff
        s.exc_spr = s.pend_spr
        s.exc_score = score
        s.cf_exc = True
        s.outcome = s.pend_edge
        s.c_start_time = s.pend_ext_time
        s.phase = PHASE_C
        s.c_ready_bar = None
        s.pend = False
        s.prov_edge = 0
        self._set_event(s, EV_SPRING if s.outcome == DIR_ACCUM else EV_UTAD, m)

    @staticmethod
    def _adopt_prov(s: WS) -> None:
        """``f_adoptProv`` (L868-881): the provisional Spring/UTAD is adopted."""
        s.exc = True
        s.exc_tested = False
        s.exc_bar = s.prov_bar
        s.exc_price = s.prov_price
        s.exc_time = s.prov_time
        s.exc_eff = s.prov_eff
        s.exc_spr = s.prov_spr
        s.exc_score = s.prov_score
        s.cf_exc = True
        s.outcome = s.prov_edge
        s.c_start_time = s.prov_time
        s.prov_edge = 0

    def _enter_c_test(
        self, s: WS, outc: int, t: float, price: float, score: int, m: Measures
    ) -> None:
        """``f_enterCTest`` (L883-893): the terminal test of a mature Phase B."""
        s.phase = PHASE_C
        s.outcome = outc
        s.c_start_time = t
        s.c_ready_bar = m.bar_index
        s.test_time = t
        s.test_price = price
        s.test_score = score
        s.cf_test = True
        s.pend = False
        self._set_event(s, EV_CTEST_ACC if outc == DIR_ACCUM else EV_CTEST_DST, m)

    def _promote_d(self, s: WS, outc: int, score: int, price: float, m: Measures) -> None:
        """``f_promoteD`` (L895-907): SOS/SOW, Phase D."""
        s.outcome = outc
        s.phase = PHASE_D
        s.d_start_bar = m.bar_index
        s.d_start_time = m.time
        s.str_bar = m.bar_index
        s.str_time = m.time
        s.str_price = price
        s.str_score = score
        s.cf_strength = True
        s.pend = False
        s.out_count = 0
        self._set_event(s, EV_SOS if outc == DIR_ACCUM else EV_SOW, m)

    def _demote_to_b(self, s: WS, bar_index: int) -> None:
        """``f_demoteToB`` (L909-930). The entry fields survive: a demoted campaign can
        never enter again (the spec's "no re-entry after demotion")."""
        self._clear_terminal(s)
        s.outcome = DIR_NONE
        s.phase = PHASE_B
        s.str_bar = None
        s.str_time = math.nan
        s.str_price = math.nan
        s.str_score = 0
        s.lps_time = math.nan
        s.lps_price = math.nan
        s.lps_bar = None
        s.lps_score = 0
        s.d_start_bar = None
        s.d_start_time = math.nan
        s.cf_strength = False
        s.cf_lps = False
        s.prov_edge = 0
        s.pend = False
        s.out_count = 0
        s.last_bad_bar = bar_index
        s.last_act_bar = bar_index

    def validation(self, s: WS, p: int, trend_now: float, atr_now: float, bar_index: int) -> int:
        """``f_validationWS`` (L936-943)."""
        r_atr = self.range_atr(s, atr_now)
        b_age = max(bar_index - s.b_start_bar, 0) if s.b_start_bar is not None else 0
        bad_age = -1 if s.last_bad_bar is None else bar_index - s.last_bad_bar
        clean = bad_age < 0 or bad_age >= pine_int_round(p * PHASE_B_BAD_TEST_COOLDOWN_FACTOR)
        cause = cause_units(s.trav_count, b_age, p, r_atr)
        terminal = (s.cf_test and (not s.exc or s.exc_tested)) or (s.cf_exc and s.cf_strength)
        if s.stop_side == DIR_NONE:
            return 0
        return validation_score(
            nz(s.birth_trend, trend_now),
            s.absorbed,
            r_atr,
            s.st_count,
            s.opp_count,
            s.trav_count,
            clean,
            cause,
            terminal,
            s.cf_strength,
            s.cf_lps,
            s.cf_accept,
        )

    def mature(self, s: WS, p: int, atr_now: float, bar_index: int) -> bool:
        """``f_matureWS`` (L945-956): Phase B has built enough cause for Phase C."""
        r_atr = self.range_atr(s, atr_now)
        b_age = bar_index - s.b_start_bar if s.b_start_bar is not None else 0
        b_min = phase_b_min_bars(p, r_atr)
        bad_age = -1 if s.last_bad_bar is None else bar_index - s.last_bad_bar
        clean = bad_age < 0 or bad_age >= pine_int_round(p * PHASE_B_BAD_TEST_COOLDOWN_FACTOR)
        opp = MIN_PHASE_B_OPPOSITE_TESTS <= 0 or s.opp_count >= MIN_PHASE_B_OPPOSITE_TESTS
        trav = MIN_PHASE_B_TRAVERSALS <= 0 or s.trav_count >= MIN_PHASE_B_TRAVERSALS
        ch = phase_b_character_improving(
            s.st_n, s.st_eff_sum, s.st_spr_sum, s.last_good_eff, s.last_good_spr
        )
        support = int(opp) + int(trav) + int(clean) + int(ch)
        sane = ge(r_atr, PHASE_B_RANGE_MIN_ATR * 0.75) and le(r_atr, PHASE_B_RANGE_MAX_ATR * 2.0)
        return (
            s.phase == PHASE_B
            and b_age >= b_min
            and s.st_count >= MIN_PHASE_B_TESTS
            and sane
            and support >= 2
        )

    def readiness(self, s: WS, min_conf: int, val_floor: int, atr_now: float, m: Measures) -> int:
        """``f_entryReadinessWS`` (L958-974): nine readiness checks."""
        bull = s.outcome == DIR_ACCUM
        unit = pmax(atr_now, self.mintick)
        if na(s.range_high) or na(s.range_low):
            dist_atr = 99.0
        elif bull:
            dist_atr = (m.close - s.range_high) / unit
        else:
            dist_atr = (s.range_low - m.close) / unit
        age_bars = (
            (m.time - s.last_event_time) / max(self.tf_seconds * 1000.0, 1.0)
            if not na(s.last_event_time)
            else 999.0
        )
        terminal = (s.exc and s.exc_tested) or (not s.exc and s.cf_test)
        conf = confidence(s)
        valid = self.validation(
            s, _nz_int(s.piv_len, PIVOT_LEN), s.birth_trend, atr_now, m.bar_index
        )
        r = 0
        r += 1 if s.outcome != DIR_NONE else 0
        r += 1 if s.phase >= PHASE_C else 0
        r += 1 if terminal else 0
        r += 1 if s.cf_strength else 0
        r += 1 if s.cf_lps else 0
        r += 1 if conf >= min_conf else 0
        r += 1 if valid >= val_floor else 0
        r += 1 if le(dist_atr, 2.0) else 0
        r += 1 if le(age_bars, 50.0) else 0
        return r

    # ── L1164-1234: retire structures that no longer fit ──────────────────────────────────
    def _retire(self, m: Measures, t: _Turn) -> None:
        s = self.s
        a = m.a
        bi = m.bar_index
        mintick = self.mintick
        p0 = _nz_int(s.piv_len, m.live_len)
        rk0 = not na(s.range_high) and not na(s.range_low)
        r_h0 = s.range_high
        r_l0 = s.range_low
        r_ht0 = pmax(r_h0 - r_l0, mintick) if rk0 else math.nan
        r_mid0 = (r_h0 + r_l0) / 2.0 if rk0 else math.nan
        t.probe_open = (
            s.pend
            and s.pend_start_bar is not None
            and bi - s.pend_start_bar <= excursion_recovery_limit(p0)
        )
        struct_age = bi - s.start_bar if s.start_bar is not None else 0
        t.age_ok_bull = self.regime != REGIME_MARKDOWN or struct_age >= OPPOSITE_CYCLE_MIN_BARS
        t.age_ok_bear = self.regime != REGIME_MARKUP or struct_age >= OPPOSITE_CYCLE_MIN_BARS
        hard_bull0 = hard_level(s, DIR_ACCUM)
        hard_bear0 = hard_level(s, DIR_DIST)
        reset_why = -1
        detail: Detail = {}
        inv = STRUCTURE_INVALIDATION_ATR

        if s.phase == PHASE_A:  # L1182-1196
            age = bi - s.climax_bar if s.climax_bar is not None else None
            a_inv_acc = s.stop_side == DIR_ACCUM and lt(m.hi_c_inv, s.climax_price - a * inv)
            a_inv_dst = s.stop_side == DIR_DIST and gt(m.lo_c_inv, s.climax_price + a * inv)
            a_absorb_exp = not s.absorbed and age is not None and age > CLIMAX_ABSORPTION_MAX_BARS
            a_no_ar = not s.ar_ok and age is not None and age > MAX_AR_BARS
            a_over_ext = (
                s.ar_ok
                and not na(s.ar_run_price)
                and gt(
                    abs(s.ar_run_price - s.climax_price) / pmax(nz(s.climax_atr, a), mintick),
                    AR_MAX_EXTENSION_ATR,
                )
            )
            a_buf = (
                pmax(
                    r_ht0 * PHASE_A_PREMATURE_DEPARTURE_TR_FRAC, a * PHASE_A_PREMATURE_DEPARTURE_ATR
                )
                if rk0
                else math.nan
            )
            a_depart = (
                age is not None
                and age > MAX_AR_BARS
                and rk0
                and (
                    (s.stop_side == DIR_ACCUM and gt(m.lo_c3, r_h0 + a_buf))
                    or (s.stop_side == DIR_DIST and lt(m.hi_c3, r_l0 - a_buf))
                )
            )
            if a_inv_acc or a_inv_dst:
                reset_why = RS_INVALID
                detail = {"climax_price": s.climax_price, "atr": a}
            elif a_absorb_exp:
                reset_why = RS_ABSORB
            elif a_no_ar or a_over_ext or a_depart:
                reset_why = RS_NORANGE

        if s.phase == PHASE_C and not t.probe_open and reset_why < 0:  # L1198-1204
            c_bull_dead = (
                s.outcome == DIR_ACCUM
                and not na(hard_bull0)
                and lt(m.hi_c_inv, hard_bull0 - a * inv)
            )
            c_bear_dead = (
                s.outcome == DIR_DIST
                and not na(hard_bear0)
                and gt(m.lo_c_inv, hard_bear0 + a * inv)
            )
            if c_bull_dead or c_bear_dead:
                reset_why = RS_INVALID
                detail = self._invalid_detail(s, m, hard_bull0, hard_bear0)

        if s.phase == PHASE_D and rk0 and reset_why < 0:  # L1206-1218
            if s.outcome == DIR_ACCUM:
                if not na(hard_bull0) and lt(m.hi_c_inv, hard_bull0 - a * inv):
                    reset_why = RS_INVALID
                    detail = self._invalid_detail(s, m, hard_bull0, hard_bear0)
                elif lt(m.hi_c3, r_mid0):
                    self._demote(s, m, t, r_mid0, m.hi_c3)
            elif s.outcome == DIR_DIST:
                if not na(hard_bear0) and gt(m.lo_c_inv, hard_bear0 + a * inv):
                    reset_why = RS_INVALID
                    detail = self._invalid_detail(s, m, hard_bull0, hard_bear0)
                elif gt(m.lo_c3, r_mid0):
                    self._demote(s, m, t, r_mid0, m.lo_c3)

        if s.phase == PHASE_E and rk0 and reset_why < 0:  # L1220-1224
            e_fail = lt(m.hi_c3, r_mid0) if s.outcome == DIR_ACCUM else gt(m.lo_c3, r_mid0)
            e_old = (
                PHASE_E_MAX_BARS > 0
                and s.e_start_bar is not None
                and bi - s.e_start_bar > PHASE_E_MAX_BARS
            )
            if e_fail or e_old:
                reset_why = RS_EEND
                detail = {
                    "e_fail": e_fail,
                    "e_old": e_old,
                    "range_mid": r_mid0,
                    "closes_3": m.hi_c3 if s.outcome == DIR_ACCUM else m.lo_c3,
                    "phase_e_bars": None if s.e_start_bar is None else bi - s.e_start_bar,
                }

        idle_lim = phase_idle_limit(s.phase, s.ar_ok, p0)  # L1226-1228
        if (
            reset_why < 0
            and not t.probe_open
            and idle_lim is not None
            and s.last_act_bar is not None
            and bi - s.last_act_bar > idle_lim
        ):
            reset_why = RS_STALE
            detail = {"idle_bars": bi - s.last_act_bar, "idle_limit": idle_lim}

        if reset_why >= 0:  # L1230-1234
            self._reset(s, reset_why, t, detail)

    def _invalid_detail(self, s: WS, m: Measures, hard_bull: float, hard_bear: float) -> Detail:
        bull = s.outcome == DIR_ACCUM
        level = hard_bull if bull else hard_bear
        buffer = m.a * STRUCTURE_INVALIDATION_ATR
        return {
            "hard_level": level,
            "invalidation_level": level - buffer if bull else level + buffer,
            "closes_2": m.hi_c_inv if bull else m.lo_c_inv,
            "atr": m.a,
        }

    def _demote(self, s: WS, m: Measures, t: _Turn, r_mid: float, closes: float) -> None:
        t.ends.append(
            CampaignEnd(
                kind="RS_DEMOTE",
                serial=s.serial,
                phase=s.phase,
                outcome=s.outcome,
                stop_side=s.stop_side,
                detail={"range_mid": r_mid, "closes_3": closes},
            )
        )
        self._demote_to_b(s, m.bar_index)
        self.rs_counts[RS_DEMOTE] += 1

    def _reset(self, s: WS, why: int, t: _Turn, detail: Detail) -> None:
        t.ends.append(
            CampaignEnd(
                kind=_RESET_KINDS[why],
                serial=s.serial,
                phase=s.phase,
                outcome=s.outcome,
                stop_side=s.stop_side,
                detail=detail,
            )
        )
        self.rs_counts[why] += 1
        self.last_reset_why = why
        self.s = self._new_ws()

    # ── L1236-1275: preliminary support/supply and new climaxes ───────────────────────────
    def _seed(self, m: Measures, t: _Turn) -> None:
        s = self.s
        bi = m.bar_index
        if s.phase == PHASE_NONE or s.phase == PHASE_E:  # L1237-1252
            vol_ok = ge(m.rel_e, PRELIM_VOL_MULT)
            ps_sc = (
                int(m.down_trend)
                + int(m.near_recent_low)
                + int(vol_ok)
                + int(ge(m.spr_atr, 0.80))
                + int(ge(m.c_pos, 0.45))
                + int(m.dn_absorb)
            )
            psy_sc = (
                int(m.up_trend)
                + int(m.near_recent_high)
                + int(vol_ok)
                + int(ge(m.spr_atr, 0.80))
                + int(le(m.c_pos, 0.55))
                + int(m.up_absorb)
            )
            ps_stale = self.prelim_bar is None or bi - self.prelim_bar > EXTREME_LEN
            if (
                m.down_trend
                and m.near_recent_low
                and vol_ok
                and ps_sc >= PRELIM_MIN_SCORE
                and (self.prelim_dir != DIR_ACCUM or ps_stale or ps_sc >= self.prelim_score)
            ):
                self._prelim(bi, m.time, m.low, DIR_ACCUM, ps_sc)
            elif (
                m.up_trend
                and m.near_recent_high
                and vol_ok
                and psy_sc >= PRELIM_MIN_SCORE
                and (self.prelim_dir != DIR_DIST or ps_stale or psy_sc >= self.prelim_score)
            ):
                self._prelim(bi, m.time, m.high, DIR_DIST, psy_sc)

        relax_k = RELAXED_CLIMAX_FACTOR if m.strong_trend else 1.0  # L1254-1264
        vol_hit = ge(m.eff, m.avg_eff_prev * CLIMAX_VOL_MULT * relax_k)
        spr_hit = ge(m.spr, m.a_prev * CLIMAX_SPREAD_MULT * relax_k)
        exceptional = (not na(m.eff_hi_prior) and ge(m.eff, m.eff_hi_prior)) or ge(
            m.spr, m.a_prev * CLIMAX_SPREAD_MULT * 1.5
        )
        sc_sc = (
            int(m.down_trend)
            + int(m.new_low)
            + int(vol_hit)
            + int(spr_hit)
            + int(ge(m.c_pos, SC_CLOSE_MIN))
            + int(exceptional)
        )
        bc_sc = (
            int(m.up_trend)
            + int(m.new_high)
            + int(vol_hit)
            + int(spr_hit)
            + int(le(m.c_pos, BC_CLOSE_MAX))
            + int(exceptional)
        )
        seed_open = s.phase == PHASE_NONE or s.phase == PHASE_E
        can_sc = seed_open or (
            s.phase == PHASE_A and s.stop_side == DIR_ACCUM and lt(m.low, s.climax_price)
        )
        can_bc = seed_open or (
            s.phase == PHASE_A and s.stop_side == DIR_DIST and gt(m.high, s.climax_price)
        )
        is_sc = (
            can_sc
            and m.down_trend
            and m.new_low
            and vol_hit
            and spr_hit
            and sc_sc >= CLIMAX_MIN_SCORE
        )
        is_bc = (
            can_bc
            and m.up_trend
            and m.new_high
            and vol_hit
            and spr_hit
            and bc_sc >= CLIMAX_MIN_SCORE
        )
        if is_sc == is_bc:
            return
        seed_side = DIR_ACCUM if is_sc else DIR_DIST  # L1265-1275
        ctx_bars = max(PRIOR_TREND_MAX_BARS, CONTINUATION_TREND_LEN) * 2
        recent_markup = (
            self.regime == REGIME_MARKUP
            and self.regime_bar is not None
            and bi - self.regime_bar <= ctx_bars
        )
        recent_markdown = (
            self.regime == REGIME_MARKDOWN
            and self.regime_bar is not None
            and bi - self.regime_bar <= ctx_bars
        )
        if s.phase != PHASE_NONE:
            t.ends.append(
                CampaignEnd(
                    kind=RESEED,
                    serial=s.serial,
                    phase=s.phase,
                    outcome=s.outcome,
                    stop_side=s.stop_side,
                    detail={"new_side": seed_side, "climax_price": m.low if is_sc else m.high},
                )
            )
        new = self._new_ws()
        self.s = new
        self._seed_ws(
            new,
            seed_side,
            sc_sc if is_sc else bc_sc,
            m.pre_len,
            m.trend_score,
            recent_markup or m.long_bull,
            recent_markdown or m.long_bear,
            m,
        )
        if (
            self.prelim_dir == seed_side
            and self.prelim_bar is not None
            and self.prelim_bar < bi
            and bi - self.prelim_bar <= EXTREME_LEN
        ):
            new.ps_time = self.prelim_time
            new.ps_price = self.prelim_price
            new.ps_score = self.prelim_score
        t.seeded = seed_side

    def _prelim(self, bar_index: int, time: float, price: float, side: int, score: int) -> None:
        self.prelim_bar = bar_index
        self.prelim_time = time
        self.prelim_price = price
        self.prelim_dir = side
        self.prelim_score = score

    # ── L1277-1311: confirm stopping action and build the AR ──────────────────────────────
    def _phase_a(self, m: Measures, t: _Turn) -> None:
        s = self.s
        bi = m.bar_index
        a = m.a
        if s.phase == PHASE_A and not s.absorbed and s.climax_bar is not None:  # L1278-1290
            abs_age = bi - s.climax_bar
            if CLIMAX_ABSORPTION_MIN_BARS <= abs_age <= CLIMAX_ABSORPTION_MAX_BARS:
                effort_ok = ge(m.recent_eff, m.avg_eff * CLIMAX_ABSORPTION_VOL_FLOOR)
                acc_abs = (
                    s.stop_side == DIR_ACCUM
                    and ge(
                        m.recent_low, s.climax_price - s.climax_atr * CLIMAX_ABSORPTION_EXTREME_ATR
                    )
                    and ge(m.close, s.climax_price + s.climax_atr * CLIMAX_ABSORPTION_REBOUND_ATR)
                )
                dst_abs = (
                    s.stop_side == DIR_DIST
                    and le(
                        m.recent_high, s.climax_price + s.climax_atr * CLIMAX_ABSORPTION_EXTREME_ATR
                    )
                    and le(m.close, s.climax_price - s.climax_atr * CLIMAX_ABSORPTION_REBOUND_ATR)
                )
                if effort_ok and (acc_abs or dst_abs):
                    s.absorbed = True
                    s.cf_climax = True
                    s.last_act_bar = bi
                    t.sig |= BIT_SC if s.stop_side == DIR_ACCUM else BIT_BC
                    if not na(s.ps_time):
                        t.sig |= BIT_PS

        if (  # L1292-1304
            s.phase == PHASE_A
            and s.ar_bar is None
            and s.climax_bar is not None
            and bi > s.climax_bar
            and bi - s.climax_bar <= MAX_AR_BARS
        ):
            if s.stop_side == DIR_ACCUM:
                if na(s.ar_run_price) or gt(m.high, s.ar_run_price):
                    s.ar_run_price = m.high
                    s.ar_run_bar = bi
                    s.ar_run_time = m.time
                s.ar_ok = s.ar_ok or ge(s.ar_run_price - s.climax_price, a * MIN_AR_ATR)
            else:
                if na(s.ar_run_price) or lt(m.low, s.ar_run_price):
                    s.ar_run_price = m.low
                    s.ar_run_bar = bi
                    s.ar_run_time = m.time
                s.ar_ok = s.ar_ok or ge(s.climax_price - s.ar_run_price, a * MIN_AR_ATR)
        if s.phase == PHASE_A and s.ar_ok and s.absorbed and s.ar_bar is None:  # L1305-1311
            if s.stop_side == DIR_ACCUM:
                s.range_high = s.ar_run_price
                s.orig_high = s.ar_run_price
            else:
                s.range_low = s.ar_run_price
                s.orig_low = s.ar_run_price

    # ── L1313-1475: pivots — C-Tests, A→B, Phase B tests, traversals ──────────────────────
    def _pivots(self, m: Measures, t: _Turn) -> None:
        s = self.s
        bi = m.bar_index
        mintick = self.mintick
        pl, ph, piv_bar, p_a = m.pl, m.ph, m.piv_bar, m.p_a
        p_eff, p_spr, p_c_pos, p_time = m.p_eff, m.p_spr, m.p_c_pos, m.p_time
        p1 = _nz_int(s.piv_len, m.live_len)
        rk1 = not na(s.range_high) and not na(s.range_low)
        r_h1 = s.range_high
        r_l1 = s.range_low
        orig_ht1 = pmax(nz(s.orig_high, r_h1) - nz(s.orig_low, r_l1), mintick) if rk1 else math.nan
        mature1 = self.mature(s, p1, m.a, bi)
        new_pl = not na(pl) and (self.last_pl_bar is None or piv_bar > self.last_pl_bar)
        new_ph = not na(ph) and (self.last_ph_bar is None or piv_bar > self.last_ph_bar)
        if new_pl:
            self.last_pl_bar = piv_bar
        if new_ph:
            self.last_ph_bar = piv_bar
        pl_used = False
        ph_used = False

        if new_pl and s.phase == PHASE_B and mature1 and rk1:  # L1328-1348: C-Test at the low
            lo_ref_st = s.stop_side == DIR_ACCUM
            t_ref_n = s.st_n if lo_ref_st else s.op_n
            t_ref_bar = s.st_bar if lo_ref_st else s.op_last_bar
            t_ref_price = s.st_price if lo_ref_st else s.op_last_price
            if t_ref_n > 0 and t_ref_bar is not None:
                t_ref_eff = (s.st_eff_sum if lo_ref_st else s.op_eff_sum) / t_ref_n
                t_ref_spr = (s.st_spr_sum if lo_ref_st else s.op_spr_sum) / t_ref_n
                t_later = piv_bar >= t_ref_bar + TERMINAL_TEST_MIN_BARS_AFTER_ST
                t_near = le(pl, r_l1 + p_a * TEST_TOL_ATR)
                t_holds = ge(
                    pl, pmin(nz(s.orig_low, r_l1), r_l1) - p_a * TEST_EXTREME_TOLERANCE_ATR
                )
                t_higher = na(t_ref_price) or ge(pl, t_ref_price - p_a * TEST_EXTREME_TOLERANCE_ATR)
                tq_v = le(p_eff, t_ref_eff * TERMINAL_TEST_VOL_RATIO)
                tq_s = le(p_spr, t_ref_spr * TERMINAL_TEST_SPREAD_RATIO)
                tn_v = le(p_eff, t_ref_eff * TERMINAL_TEST_OTHER_MAX_RATIO)
                tn_s = le(p_spr, t_ref_spr * TERMINAL_TEST_OTHER_MAX_RATIO)
                t_sc = int(tq_v) + int(tq_s) + int(ge(p_c_pos, 0.50))
                if (
                    t_later
                    and t_near
                    and t_holds
                    and t_higher
                    and ((tq_v and tn_s) or (tq_s and tn_v))
                    and t_sc >= TEST_MIN_SCORE
                ):
                    self._enter_c_test(s, DIR_ACCUM, p_time, pl, t_sc, m)
                    t.sig |= BIT_CTEST
                    pl_used = True
        if new_ph and s.phase == PHASE_B and mature1 and rk1:  # L1349-1369: C-Test at the high
            hi_ref_st = s.stop_side == DIR_DIST
            u_ref_n = s.st_n if hi_ref_st else s.op_n
            u_ref_bar = s.st_bar if hi_ref_st else s.op_last_bar
            u_ref_price = s.st_price if hi_ref_st else s.op_last_price
            if u_ref_n > 0 and u_ref_bar is not None:
                u_ref_eff = (s.st_eff_sum if hi_ref_st else s.op_eff_sum) / u_ref_n
                u_ref_spr = (s.st_spr_sum if hi_ref_st else s.op_spr_sum) / u_ref_n
                u_later = piv_bar >= u_ref_bar + TERMINAL_TEST_MIN_BARS_AFTER_ST
                u_near = ge(ph, r_h1 - p_a * TEST_TOL_ATR)
                u_holds = le(
                    ph, pmax(nz(s.orig_high, r_h1), r_h1) + p_a * TEST_EXTREME_TOLERANCE_ATR
                )
                u_lower = na(u_ref_price) or le(ph, u_ref_price + p_a * TEST_EXTREME_TOLERANCE_ATR)
                uq_v = le(p_eff, u_ref_eff * TERMINAL_TEST_VOL_RATIO)
                uq_s = le(p_spr, u_ref_spr * TERMINAL_TEST_SPREAD_RATIO)
                un_v = le(p_eff, u_ref_eff * TERMINAL_TEST_OTHER_MAX_RATIO)
                un_s = le(p_spr, u_ref_spr * TERMINAL_TEST_OTHER_MAX_RATIO)
                u_sc = int(uq_v) + int(uq_s) + int(le(p_c_pos, 0.50))
                if (
                    u_later
                    and u_near
                    and u_holds
                    and u_lower
                    and ((uq_v and un_s) or (uq_s and un_v))
                    and u_sc >= TEST_MIN_SCORE
                ):
                    self._enter_c_test(s, DIR_DIST, p_time, ph, u_sc, m)
                    t.sig |= BIT_CTEST
                    ph_used = True

        if (  # L1371-1390: the first ST fixes the AR and starts Phase B (SC campaigns)
            new_pl
            and not pl_used
            and s.phase == PHASE_A
            and s.stop_side == DIR_ACCUM
            and s.absorbed
            and s.ar_ok
            and s.ar_run_bar is not None
            and piv_bar > s.ar_run_bar
        ):
            a_zone_top = s.orig_low + (s.ar_run_price - s.orig_low) * PHASE_B_ZONE_FRAC
            a_near_l = le(abs(pl - s.orig_low), p_a * BOUNDARY_TOL_ATR) or le(pl, a_zone_top)
            a_holds_l = ge(pl, s.orig_low - p_a * BOUNDARY_TOL_ATR)
            a_close_l = ge(p_c_pos, 0.45)
            a_tc_l = test_class(
                a_near_l, a_holds_l, a_close_l, p_eff, p_spr, s.climax_eff, s.climax_spr
            )
            a_sc_l = (
                int(a_near_l)
                + int(le(p_eff, s.climax_eff * ST_MAX_VOL_RATIO))
                + int(le(p_spr, s.climax_spr * ST_MAX_SPREAD_RATIO))
                + int(a_holds_l)
                + int(a_close_l)
                + 1
            )
            a_age_l = s.start_bar is not None and piv_bar - s.start_bar >= phase_a_min_bars(p1)
            a_space_l = piv_bar - s.ar_run_bar >= max(2, p1)
            if a_near_l:
                s.last_act_bar = bi
            if a_tc_l == TEST_GOOD and a_sc_l >= ST_MIN_SCORE and a_age_l and a_space_l:
                self._freeze_ar(s)
                self._register_st(s, pl, p_time, piv_bar, p_eff, p_spr, a_sc_l, m)
                s.phase = PHASE_B
                s.b_start_bar = piv_bar
                s.b_start_time = p_time
                t.sig |= BIT_AR | BIT_ST
                pl_used = True
        if (  # L1391-1410: the same for BC campaigns
            new_ph
            and not ph_used
            and s.phase == PHASE_A
            and s.stop_side == DIR_DIST
            and s.absorbed
            and s.ar_ok
            and s.ar_run_bar is not None
            and piv_bar > s.ar_run_bar
        ):
            a_zone_bot = s.orig_high - (s.orig_high - s.ar_run_price) * PHASE_B_ZONE_FRAC
            a_near_h = le(abs(ph - s.orig_high), p_a * BOUNDARY_TOL_ATR) or ge(ph, a_zone_bot)
            a_holds_h = le(ph, s.orig_high + p_a * BOUNDARY_TOL_ATR)
            a_close_h = le(p_c_pos, 0.55)
            a_tc_h = test_class(
                a_near_h, a_holds_h, a_close_h, p_eff, p_spr, s.climax_eff, s.climax_spr
            )
            a_sc_h = (
                int(a_near_h)
                + int(le(p_eff, s.climax_eff * ST_MAX_VOL_RATIO))
                + int(le(p_spr, s.climax_spr * ST_MAX_SPREAD_RATIO))
                + int(a_holds_h)
                + int(a_close_h)
                + 1
            )
            a_age_h = s.start_bar is not None and piv_bar - s.start_bar >= phase_a_min_bars(p1)
            a_space_h = piv_bar - s.ar_run_bar >= max(2, p1)
            if a_near_h:
                s.last_act_bar = bi
            if a_tc_h == TEST_GOOD and a_sc_h >= ST_MIN_SCORE and a_age_h and a_space_h:
                self._freeze_ar(s)
                self._register_st(s, ph, p_time, piv_bar, p_eff, p_spr, a_sc_h, m)
                s.phase = PHASE_B
                s.b_start_bar = piv_bar
                s.b_start_time = p_time
                t.sig |= BIT_AR | BIT_ST
                ph_used = True

        rk1 = not na(s.range_high) and not na(s.range_low)  # L1412
        after_b_start = s.b_start_bar is not None and piv_bar > s.b_start_bar
        if new_pl and not pl_used and s.phase == PHASE_B and rk1 and after_b_start:  # L1413-1437
            b_ht = pmax(s.range_high - s.range_low, mintick)
            if s.stop_side == DIR_ACCUM:
                b_near = (
                    le(abs(pl - s.range_low), p_a * BOUNDARY_TOL_ATR)
                    or le(abs(pl - s.orig_low), p_a * BOUNDARY_TOL_ATR)
                    or le(pl, s.range_low + b_ht * PHASE_B_ZONE_FRAC)
                )
                b_holds = ge(pl, s.orig_low - p_a * BOUNDARY_TOL_ATR)
                b_close = ge(p_c_pos, 0.45)
                b_tc = test_class(
                    b_near, b_holds, b_close, p_eff, p_spr, s.climax_eff, s.climax_spr
                )
                b_sc = (
                    int(b_near)
                    + int(le(p_eff, s.climax_eff * ST_MAX_VOL_RATIO))
                    + int(le(p_spr, s.climax_spr * ST_MAX_SPREAD_RATIO))
                    + int(b_holds)
                    + int(b_close)
                    + 1
                )
                b_is_prov = (
                    s.prov_edge == DIR_ACCUM
                    and s.prov_bar is not None
                    and abs(piv_bar - s.prov_bar) <= p1
                )
                if b_near:
                    s.last_act_bar = bi
                if b_tc == TEST_FAILED and not b_is_prov:
                    s.last_bad_bar = piv_bar
                elif b_tc == TEST_GOOD and b_sc >= ST_MIN_SCORE:
                    self._register_st(s, pl, p_time, piv_bar, p_eff, p_spr, b_sc, m)
                    t.sig |= BIT_ST
            else:
                if lt(pl, s.range_low) and ge(
                    pl, nz(s.orig_low, s.range_low) - orig_ht1 * PHASE_B_EDGE_EXPANSION_CAP
                ):
                    s.range_low = pl
                o_ht_l = pmax(s.range_high - s.range_low, mintick)
                o_near_l = le(pl, s.range_low + p_a * BOUNDARY_TOL_ATR) or le(
                    pl, s.range_low + o_ht_l * PHASE_B_ZONE_FRAC
                )
                o_inside_l = ge(
                    pl, nz(s.orig_low, s.range_low) - orig_ht1 * PHASE_B_EDGE_EXPANSION_CAP
                )
                o_ctrl_l = le(p_eff, s.climax_eff * 1.20) and le(p_spr, s.climax_spr * 1.20)
                if (
                    o_near_l
                    and o_inside_l
                    and o_ctrl_l
                    and (s.op_last_bar is None or piv_bar > s.op_last_bar)
                ):
                    self._register_opp(s, pl, p_time, piv_bar, p_eff, p_spr, bi)
        after_b_start = s.b_start_bar is not None and piv_bar > s.b_start_bar
        if new_ph and not ph_used and s.phase == PHASE_B and rk1 and after_b_start:  # L1438-1462
            b_ht_h = pmax(s.range_high - s.range_low, mintick)
            if s.stop_side == DIR_DIST:
                h_near = (
                    le(abs(ph - s.range_high), p_a * BOUNDARY_TOL_ATR)
                    or le(abs(ph - s.orig_high), p_a * BOUNDARY_TOL_ATR)
                    or ge(ph, s.range_high - b_ht_h * PHASE_B_ZONE_FRAC)
                )
                h_holds = le(ph, s.orig_high + p_a * BOUNDARY_TOL_ATR)
                h_close = le(p_c_pos, 0.55)
                h_tc = test_class(
                    h_near, h_holds, h_close, p_eff, p_spr, s.climax_eff, s.climax_spr
                )
                h_sc = (
                    int(h_near)
                    + int(le(p_eff, s.climax_eff * ST_MAX_VOL_RATIO))
                    + int(le(p_spr, s.climax_spr * ST_MAX_SPREAD_RATIO))
                    + int(h_holds)
                    + int(h_close)
                    + 1
                )
                h_is_prov = (
                    s.prov_edge == DIR_DIST
                    and s.prov_bar is not None
                    and abs(piv_bar - s.prov_bar) <= p1
                )
                if h_near:
                    s.last_act_bar = bi
                if h_tc == TEST_FAILED and not h_is_prov:
                    s.last_bad_bar = piv_bar
                elif h_tc == TEST_GOOD and h_sc >= ST_MIN_SCORE:
                    self._register_st(s, ph, p_time, piv_bar, p_eff, p_spr, h_sc, m)
                    t.sig |= BIT_ST
            else:
                if gt(ph, s.range_high) and le(
                    ph, nz(s.orig_high, s.range_high) + orig_ht1 * PHASE_B_EDGE_EXPANSION_CAP
                ):
                    s.range_high = ph
                o_ht_h = pmax(s.range_high - s.range_low, mintick)
                o_near_h = ge(ph, s.range_high - p_a * BOUNDARY_TOL_ATR) or ge(
                    ph, s.range_high - o_ht_h * PHASE_B_ZONE_FRAC
                )
                o_inside_h = le(
                    ph, nz(s.orig_high, s.range_high) + orig_ht1 * PHASE_B_EDGE_EXPANSION_CAP
                )
                o_ctrl_h = le(p_eff, s.climax_eff * 1.20) and le(p_spr, s.climax_spr * 1.20)
                if (
                    o_near_h
                    and o_inside_h
                    and o_ctrl_h
                    and (s.op_last_bar is None or piv_bar > s.op_last_bar)
                ):
                    self._register_opp(s, ph, p_time, piv_bar, p_eff, p_spr, bi)

        if s.phase == PHASE_B and not na(s.range_high) and not na(s.range_low):  # L1465-1475
            tv_ht = pmax(s.range_high - s.range_low, mintick)
            lo_zone_p = new_pl and le(pl, s.range_low + tv_ht * PHASE_B_ZONE_FRAC)
            hi_zone_p = new_ph and ge(ph, s.range_high - tv_ht * PHASE_B_ZONE_FRAC)
            zone_now = (-1 if lo_zone_p else 1) if lo_zone_p != hi_zone_p else 0
            if zone_now != 0 and (s.last_zone_bar is None or piv_bar > s.last_zone_bar):
                if s.last_zone != 0 and zone_now != s.last_zone:
                    s.trav_count = s.trav_count + 1
                    s.last_act_bar = bi
                s.last_zone = zone_now
                s.last_zone_bar = piv_bar
        t.new_pl, t.new_ph = new_pl, new_ph

    # ── L1477-1529: Phase C tests of the Spring/UTAD, LPS/LPSY ────────────────────────────
    def _tests_and_lps(self, m: Measures, t: _Turn) -> None:
        s = self.s
        pl, ph, piv_bar, p_a = m.pl, m.ph, m.piv_bar, m.p_a
        p_eff, p_spr, p_c_pos, p_time = m.p_eff, m.p_spr, m.p_c_pos, m.p_time
        new_pl, new_ph = t.new_pl, t.new_ph
        after_exc = s.exc_bar is not None and piv_bar > s.exc_bar
        if (  # L1477-1489
            new_pl
            and s.phase == PHASE_C
            and s.outcome == DIR_ACCUM
            and s.exc
            and not s.exc_tested
            and after_exc
            and not na(s.range_low)
        ):
            x_near_l = le(pl, s.range_low + p_a * TEST_TOL_ATR)
            x_keep_l = ge(pl, s.exc_price - p_a * TEST_EXTREME_TOLERANCE_ATR)
            x_sc_l = (
                int(le(p_eff, s.exc_eff * TEST_MAX_VOL_RATIO))
                + int(le(p_spr, s.exc_spr * TEST_MAX_SPREAD_RATIO))
                + int(ge(p_c_pos, 0.50))
            )
            if x_near_l and x_keep_l and x_sc_l >= TEST_MIN_SCORE:
                self._spring_test(s, p_time, pl, x_sc_l, m)
                t.sig |= BIT_TEST
        after_exc = s.exc_bar is not None and piv_bar > s.exc_bar
        if (  # L1490-1502
            new_ph
            and s.phase == PHASE_C
            and s.outcome == DIR_DIST
            and s.exc
            and not s.exc_tested
            and after_exc
            and not na(s.range_high)
        ):
            x_near_h = ge(ph, s.range_high - p_a * TEST_TOL_ATR)
            x_keep_h = le(ph, s.exc_price + p_a * TEST_EXTREME_TOLERANCE_ATR)
            x_sc_h = (
                int(le(p_eff, s.exc_eff * TEST_MAX_VOL_RATIO))
                + int(le(p_spr, s.exc_spr * TEST_MAX_SPREAD_RATIO))
                + int(le(p_c_pos, 0.50))
            )
            if x_near_h and x_keep_h and x_sc_h >= TEST_MIN_SCORE:
                self._spring_test(s, p_time, ph, x_sc_h, m)
                t.sig |= BIT_TEST

        after_str = s.str_bar is not None and piv_bar > s.str_bar
        if (  # L1504-1516: LPS
            new_pl
            and s.phase == PHASE_D
            and s.outcome == DIR_ACCUM
            and after_str
            and not na(s.range_high)
        ):
            l_hard = hard_level(s, DIR_ACCUM)
            l_side = not na(l_hard) and gt(pl, l_hard - p_a * TEST_EXTREME_TOLERANCE_ATR)
            l_creek = ge(pl, s.range_high - p_a * LPS_BOUNDARY_ATR)
            l_sc = (
                int(le(p_eff, m.p_avg_eff * LPS_VOL_MULT))
                + int(le(p_spr, p_a * LPS_SPREAD_ATR))
                + int(ge(p_c_pos, 0.45))
            )
            if l_side and l_creek and l_sc >= LPS_MIN_SCORE:
                self._lps(s, p_time, pl, l_sc, EV_LPS, m)
                t.sig |= BIT_LPS
        after_str = s.str_bar is not None and piv_bar > s.str_bar
        if (  # L1517-1529: LPSY
            new_ph
            and s.phase == PHASE_D
            and s.outcome == DIR_DIST
            and after_str
            and not na(s.range_low)
        ):
            y_hard = hard_level(s, DIR_DIST)
            y_side = not na(y_hard) and lt(ph, y_hard + p_a * TEST_EXTREME_TOLERANCE_ATR)
            y_ice = le(ph, s.range_low + p_a * LPS_BOUNDARY_ATR)
            y_sc = (
                int(le(p_eff, m.p_avg_eff * LPS_VOL_MULT))
                + int(le(p_spr, p_a * LPS_SPREAD_ATR))
                + int(le(p_c_pos, 0.55))
            )
            if y_side and y_ice and y_sc >= LPS_MIN_SCORE:
                self._lps(s, p_time, ph, y_sc, EV_LPSY, m)
                t.sig |= BIT_LPSY

    def _spring_test(self, s: WS, time: float, price: float, score: int, m: Measures) -> None:
        """L1482-1488 / L1495-1501: the Test of the Spring/UTAD."""
        s.exc_tested = True
        s.c_ready_bar = m.bar_index
        s.test_time = time
        s.test_price = price
        s.test_score = score
        s.cf_test = True
        self._set_event(s, EV_TEST, m)

    def _lps(self, s: WS, time: float, price: float, score: int, ev: int, m: Measures) -> None:
        """L1510-1515 / L1523-1528."""
        s.lps_time = time
        s.lps_price = price
        s.lps_bar = m.bar_index
        s.lps_score = score
        s.cf_lps = True
        self._set_event(s, ev, m)

    # ── L1531-1610: Spring/UTAD probes ────────────────────────────────────────────────────
    def _probes(self, m: Measures, t: _Turn) -> tuple[int, float, float, bool]:
        s = self.s
        bi = m.bar_index
        a = m.a
        p2 = _nz_int(s.piv_len, m.live_len)
        rk2 = not na(s.range_high) and not na(s.range_low)
        r_h2 = s.range_high
        r_l2 = s.range_low
        rec_limit2 = excursion_recovery_limit(p2)
        mature2 = self.mature(s, p2, a, bi)
        b_age2 = bi - s.b_start_bar if s.b_start_bar is not None else 0
        probe_b = s.phase == PHASE_B and s.st_count >= 1 and b_age2 >= max(3, p2 * 2)
        probe_c_lo = s.phase == PHASE_C and s.outcome == DIR_ACCUM and not s.exc
        probe_c_hi = s.phase == PHASE_C and s.outcome == DIR_DIST and not s.exc
        if rk2 and not s.pend and (s.pend_cool_bar is None or bi > s.pend_cool_bar):  # L1542
            pen_lo = r_l2 - m.low
            pen_hi = m.high - r_h2
            ok_lo = (
                (probe_b or probe_c_lo)
                and ge(pen_lo, a * SPRING_MIN_PEN_ATR)
                and le(pen_lo, a * SPRING_MAX_PEN_ATR)
            )
            ok_hi = (
                (probe_b or probe_c_hi)
                and ge(pen_hi, a * SPRING_MIN_PEN_ATR)
                and le(pen_hi, a * SPRING_MAX_PEN_ATR)
            )
            if ok_lo != ok_hi:
                s.pend = True
                s.pend_edge = DIR_ACCUM if ok_lo else DIR_DIST
                s.pend_start_bar = bi
                s.pend_ext_bar = bi
                s.pend_ext = m.low if ok_lo else m.high
                s.pend_ext_time = m.time
                s.pend_eff = m.eff
                s.pend_spr = m.spr
        if s.pend and rk2 and (s.phase == PHASE_B or s.phase == PHASE_C):  # L1556-1596
            if s.pend_edge == DIR_ACCUM and lt(m.low, s.pend_ext):
                self._deepen_pend(s, m.low, m)
            elif s.pend_edge == DIR_DIST and gt(m.high, s.pend_ext):
                self._deepen_pend(s, m.high, m)
            rec_age = bi - s.pend_start_bar if s.pend_start_bar is not None else 0
            if s.pend_edge == DIR_ACCUM:
                recovered = gt(m.close, r_l2)
                depth = r_l2 - s.pend_ext
                rec_sc = (
                    int(ge(m.c_pos, SPRING_CLOSE_MIN))
                    + int(le(m.eff, m.avg_eff * SPRING_EFFORT_MAX_MULT))
                    + int(gt(m.close, m.open))
                    + int(ge(m.spr, a * 0.50))
                )
            else:
                recovered = lt(m.close, r_h2)
                depth = s.pend_ext - r_h2
                rec_sc = (
                    int(le(m.c_pos, UTAD_CLOSE_MAX))
                    + int(le(m.eff, m.avg_eff * SPRING_EFFORT_MAX_MULT))
                    + int(lt(m.close, m.open))
                    + int(ge(m.spr, a * 0.50))
                )
            depth_ok = ge(depth, a * SPRING_MIN_PEN_ATR) and le(depth, a * SPRING_MAX_PEN_ATR)
            if recovered and depth_ok and rec_age <= rec_limit2 and rec_sc >= EXCURSION_MIN_SCORE:
                probe_edge = s.pend_edge
                if s.phase == PHASE_B and not mature2:  # L1576-1586: provisional
                    s.prov_edge = probe_edge
                    s.prov_bar = s.pend_ext_bar
                    s.prov_price = s.pend_ext
                    s.prov_time = s.pend_ext_time
                    s.prov_eff = s.pend_eff
                    s.prov_spr = s.pend_spr
                    s.prov_score = rec_sc
                    s.last_act_bar = bi
                    s.pend = False
                else:  # L1587-1591: the Spring/UTAD, Phase C
                    if s.phase == PHASE_C:
                        self._clear_terminal(s)
                    self._exc_from_pend(s, rec_sc, m)
                    t.sig |= BIT_SPRING if probe_edge == DIR_ACCUM else BIT_UTAD
            elif rec_age > rec_limit2 or (not depth_ok and gt(depth, a * SPRING_MAX_PEN_ATR)):
                if s.phase == PHASE_B:  # L1592-1596: a failed probe
                    s.last_bad_bar = bi
                s.pend = False
                s.pend_cool_bar = bi + p2

        if s.phase == PHASE_C and s.exc and not s.exc_tested and rk2:  # L1598-1610
            if (
                s.outcome == DIR_ACCUM
                and lt(m.low, s.exc_price)
                and ge(m.low, r_l2 - a * SPRING_MAX_PEN_ATR)
            ):
                self._deepen_exc(s, m.low, m)
            elif (
                s.outcome == DIR_DIST
                and gt(m.high, s.exc_price)
                and le(m.high, r_h2 + a * SPRING_MAX_PEN_ATR)
            ):
                self._deepen_exc(s, m.high, m)
        return p2, r_h2, r_l2, mature2

    @staticmethod
    def _deepen_pend(s: WS, price: float, m: Measures) -> None:
        s.pend_ext = price
        s.pend_ext_bar = m.bar_index
        s.pend_ext_time = m.time
        s.pend_eff = pmax(nz(s.pend_eff), m.eff)
        s.pend_spr = pmax(nz(s.pend_spr), m.spr)

    @staticmethod
    def _deepen_exc(s: WS, price: float, m: Measures) -> None:
        s.exc_price = price
        s.exc_bar = m.bar_index
        s.exc_time = m.time
        s.exc_eff = pmax(nz(s.exc_eff), m.eff)
        s.exc_spr = pmax(nz(s.exc_spr), m.spr)

    # ── L1612-1641: SOS/SOW and Phase D ───────────────────────────────────────────────────
    def _promote(self, m: Measures, t: _Turn, p2: int, r_h2: float, r_l2: float) -> None:
        s = self.s
        rk2 = not na(s.range_high) and not na(s.range_low)
        if not (s.phase == PHASE_C and rk2 and not s.pend):
            return
        bi = m.bar_index
        a = m.a
        c_min_d = phase_c_to_d_min_bars(p2)
        c_formal = not s.exc or s.exc_tested
        c_anchor = s.c_ready_bar if s.c_ready_bar is not None else s.exc_bar
        c_age_ready = c_anchor is not None and bi - c_anchor >= c_min_d
        c_val = self.validation(s, p2, m.trend_score, a, bi)
        c_val_d = c_val if c_formal else min(100, c_val + 13)
        c_conf = confidence(s)
        c_conf_d = c_conf if c_formal else min(100, c_conf + 30)
        c_ht = pmax(r_h2 - r_l2, self.mintick)
        if not (
            c_age_ready and c_val_d >= PHASE_D_VALIDATION_MIN and c_conf_d >= MIN_CONFIDENCE_PHASE_C
        ):
            return
        req = STRENGTH_MIN_SCORE if c_formal else max(2, STRENGTH_MIN_SCORE - 1)
        if s.outcome == DIR_ACCUM and t.age_ok_bull:
            dom_up = r_l2 + c_ht * PHASE_D_DOMINANCE_FRAC
            brk_up = gt(m.close, r_h2 + a * BREAK_ATR)
            held = ge(m.close, dom_up) and ge(m.close1, dom_up)
            dom_ok_up = brk_up or (held if c_formal else held and ge(m.close2, dom_up))
            q_up = m.sos_score >= req or m.mb_sos or (not c_formal and ge(m.res3_up, 1.0))
            if dom_ok_up and q_up:
                self._promote_d(s, DIR_ACCUM, m.sos_score, m.high, m)
                t.sig |= BIT_SOS
        elif s.outcome == DIR_DIST and t.age_ok_bear:
            dom_dn = r_h2 - c_ht * PHASE_D_DOMINANCE_FRAC
            brk_dn = lt(m.close, r_l2 - a * BREAK_ATR)
            held = le(m.close, dom_dn) and le(m.close1, dom_dn)
            dom_ok_dn = brk_dn or (held if c_formal else held and le(m.close2, dom_dn))
            q_dn = m.sow_score >= req or m.mb_sow or (not c_formal and ge(m.res3_dn, 1.0))
            if dom_ok_dn and q_dn:
                self._promote_d(s, DIR_DIST, m.sow_score, m.low, m)
                t.sig |= BIT_SOW

    # ── L1643-1676: Phase B departures, provisional Spring/UTAD adoption ──────────────────
    def _depart(
        self, m: Measures, t: _Turn, p2: int, r_h2: float, r_l2: float, mature2: bool
    ) -> None:
        s = self.s
        rk2 = not na(s.range_high) and not na(s.range_low)
        if not (s.phase == PHASE_B and rk2 and not s.pend):
            return
        bi = m.bar_index
        a = m.a
        reset_late = -1
        d_ht = pmax(r_h2 - r_l2, self.mintick)
        d_buf = pmax(d_ht * PHASE_B_DEPARTURE_TR_FRAC, a * PHASE_B_DEPARTURE_ATR)
        up_acc = gt(m.close, r_h2 + a * BREAK_ATR) and gt(m.close1, r_h2 + a * BREAK_ATR)
        dn_acc = lt(m.close, r_l2 - a * BREAK_ATR) and lt(m.close1, r_l2 - a * BREAK_ATR)
        up_sus = gt(m.lo_c3, r_h2 + d_buf)
        dn_sus = lt(m.hi_c3, r_l2 - d_buf)
        up_go = (up_acc and (m.sos_score >= STRENGTH_MIN_SCORE or m.mb_sos)) or up_sus
        dn_go = (dn_acc and (m.sow_score >= STRENGTH_MIN_SCORE or m.mb_sow)) or dn_sus
        prov_limit = max(PHASE_C_IDLE_MAX_BARS, max(p2, 1) * 8)  # f_phaseIdleLimit(C, true, p2)
        detail: Detail = {}
        if up_go and not dn_go:
            up_prov = (
                s.prov_edge == DIR_ACCUM
                and s.prov_bar is not None
                and bi - s.prov_bar <= prov_limit
            )
            if t.age_ok_bull and up_prov and mature2:
                self._adopt_prov(s)
                self._promote_d(s, DIR_ACCUM, m.sos_score, m.high, m)
                t.sig |= BIT_SPRING | BIT_SOS
            elif up_sus and not up_prov:
                reset_late = RS_DEPART
                detail = {"side": "up", "closes_3": m.lo_c3, "level": r_h2 + d_buf}
        elif dn_go and not up_go:
            dn_prov = (
                s.prov_edge == DIR_DIST and s.prov_bar is not None and bi - s.prov_bar <= prov_limit
            )
            if t.age_ok_bear and dn_prov and mature2:
                self._adopt_prov(s)
                self._promote_d(s, DIR_DIST, m.sow_score, m.low, m)
                t.sig |= BIT_UTAD | BIT_SOW
            elif dn_sus and not dn_prov:
                reset_late = RS_DEPART
                detail = {"side": "down", "closes_3": m.hi_c3, "level": r_l2 - d_buf}
        if reset_late >= 0:  # L1672-1676
            self._reset(s, reset_late, t, detail)

    # ── L1678-1693: a renewed SOS/SOW after the LPS/LPSY ──────────────────────────────────
    def _re_sos(self, m: Measures, t: _Turn) -> None:
        s = self.s
        a = m.a
        if (
            s.phase == PHASE_D
            and s.outcome == DIR_ACCUM
            and s.ev == EV_LPS
            and not na(s.range_high)
            and gt(m.close, s.range_high + a * BREAK_ATR)
            and ge(m.rel_e, STRENGTH_VOL_MULT)
            and ge(m.c_pos, SOS_CLOSE_MIN)
        ):
            self._strength(s, m.high, m.sos_score, EV_SOS, m)
            t.sig |= BIT_SOS
        if (
            s.phase == PHASE_D
            and s.outcome == DIR_DIST
            and s.ev == EV_LPSY
            and not na(s.range_low)
            and lt(m.close, s.range_low - a * BREAK_ATR)
            and ge(m.rel_e, STRENGTH_VOL_MULT)
            and le(m.c_pos, SOW_CLOSE_MAX)
        ):
            self._strength(s, m.low, m.sow_score, EV_SOW, m)
            t.sig |= BIT_SOW

    def _strength(self, s: WS, price: float, score: int, ev: int, m: Measures) -> None:
        s.str_bar = m.bar_index
        s.str_time = m.time
        s.str_price = price
        s.str_score = score
        self._set_event(s, ev, m)

    # ── L1695-1727: acceptance into Phase E ───────────────────────────────────────────────
    def _accept(self, m: Measures, t: _Turn) -> None:
        s = self.s
        if not (s.phase == PHASE_D and not na(s.range_high) and not na(s.range_low)):
            return
        bi = m.bar_index
        e_conf = confidence(s)
        d_age = bi - s.d_start_bar if s.d_start_bar is not None else 0
        d_min = phase_d_min_bars(_nz_int(s.piv_len, m.live_len))
        lps_aged = s.lps_bar is not None and bi - s.lps_bar >= CONFIRM_BARS
        if s.outcome == DIR_ACCUM:
            s.out_count = s.out_count + 1 if gt(m.close, s.range_high) else 0
            e_opp_ok = self.regime != REGIME_MARKDOWN or s.cf_lps
            e_std = (
                s.cf_lps
                and lps_aged
                and d_age >= d_min
                and gt(m.lo_c3, s.range_high)
                and e_conf >= MIN_CONFIDENCE_PHASE_D
            )
            e_dir = (
                not s.cf_lps
                and d_age >= max(d_min, DIRECT_ACCEPTANCE_BARS)
                and gt(m.lo_c_dir, s.range_high)
                and e_conf >= DIRECT_ACCEPTANCE_CONFIDENCE
            )
            if (e_std or e_dir) and e_opp_ok:
                self._enter_e(s, REGIME_MARKUP, EV_MARKUP, m)
                t.sig |= BIT_E
        elif s.outcome == DIR_DIST:
            s.out_count = s.out_count + 1 if lt(m.close, s.range_low) else 0
            e_opp_ok = self.regime != REGIME_MARKUP or s.cf_lps
            e_std = (
                s.cf_lps
                and lps_aged
                and d_age >= d_min
                and lt(m.hi_c3, s.range_low)
                and e_conf >= MIN_CONFIDENCE_PHASE_D
            )
            e_dir = (
                not s.cf_lps
                and d_age >= max(d_min, DIRECT_ACCEPTANCE_BARS)
                and lt(m.hi_c_dir, s.range_low)
                and e_conf >= DIRECT_ACCEPTANCE_CONFIDENCE
            )
            if (e_std or e_dir) and e_opp_ok:
                self._enter_e(s, REGIME_MARKDOWN, EV_MARKDOWN, m)
                t.sig |= BIT_E

    def _enter_e(self, s: WS, regime: int, ev: int, m: Measures) -> None:
        s.cf_accept = True
        s.phase = PHASE_E
        s.e_start_bar = m.bar_index
        s.e_start_time = m.time
        self.regime = regime
        self.regime_bar = m.bar_index
        self._set_event(s, ev, m)

    # ── L1729-1747: the Auto entry ────────────────────────────────────────────────────────
    def _entry(self, m: Measures, t: _Turn) -> EntryCheck | None:
        s = self.s
        if not (na(s.entry_time) and s.outcome != DIR_NONE):
            return None
        test_bit = bool(t.sig & (BIT_TEST | BIT_CTEST))
        strength_bit = bool(t.sig & (BIT_SOS | BIT_SOW))
        lps_bit = bool(t.sig & (BIT_LPS | BIT_LPSY))
        if not (test_bit or strength_bit or lps_bit):
            return None  # no trigger can be true: nothing to evaluate
        strict = self.strictness
        e_min_conf = _MIN_CONFIDENCE[strict]
        e_min_tests = _MIN_READINESS[strict]
        e_val_floor = (
            PHASE_D_VALIDATION_MIN
            if strict == "Conservative"
            else max(45, PHASE_D_VALIDATION_MIN - 10)
        )
        p = _nz_int(s.piv_len, m.live_len)
        e_val = self.validation(s, p, m.trend_score, m.a, m.bar_index)
        e_ready = self.readiness(s, e_min_conf, e_val_floor, m.a, m)
        conf = confidence(s)
        e_quality = conf >= e_min_conf and e_val >= e_val_floor and e_ready >= e_min_tests
        triggers = {
            "aggressiveTestTrig": strict == "Aggressive" and test_bit and e_quality,
            "aggressiveStrengthFallback": (
                strict == "Aggressive" and strength_bit and e_quality and na(s.test_time)
            ),
            "standardTestTrig": (
                strict == "Standard" and test_bit and e_quality and s.test_score >= TEST_MIN_SCORE
            ),
            "standardLpsFallback": strict == "Standard" and lps_bit and e_quality,
            "conservativeLpsTrig": strict == "Conservative" and lps_bit and e_quality,
        }
        fired = [name for name, on in triggers.items() if on]
        kind = ENTRY_NONE
        if fired:  # L1744-1747
            s.entry_time = m.time
            s.entry_price = m.close
            if triggers["standardLpsFallback"] or triggers["conservativeLpsTrig"]:
                kind = ENTRY_LPS
            elif triggers["aggressiveStrengthFallback"]:
                kind = ENTRY_STRENGTH
            else:
                kind = ENTRY_TEST
            s.entry_kind = kind
        return EntryCheck(
            strictness=strict,
            direction=s.outcome,
            confidence=conf,
            min_confidence=e_min_conf,
            validation=e_val,
            validation_floor=e_val_floor,
            readiness=e_ready,
            min_readiness=e_min_tests,
            quality=e_quality,
            test_bit=test_bit,
            strength_bit=strength_bit,
            lps_bit=lps_bit,
            triggers=fired,
            kind=kind,
        )


def _push_triplet(hist: PivotTriplet, pb: int, t: float, price: float) -> None:
    """The first three pivots of a side, each later than the one before (L786-797)."""
    if na(hist.t1):
        hist.b1, hist.t1, hist.p1 = pb, t, price
    elif na(hist.t2) and pb > (hist.b1 if hist.b1 is not None else -1):
        hist.b2, hist.t2, hist.p2 = pb, t, price
    elif na(hist.t3) and pb > _first_int(hist.b2, hist.b1, -1):
        hist.b3, hist.t3, hist.p3 = pb, t, price


def _first_int(a: int | None, b: int | None, default: int) -> int:
    """``nz(a, nz(b, default))`` for ints."""
    if a is not None:
        return a
    return b if b is not None else default


_RESET_KINDS = {
    RS_INVALID: "RS_INVALID",
    RS_ABSORB: "RS_ABSORB",
    RS_NORANGE: "RS_NORANGE",
    RS_DEPART: "RS_DEPART",
    RS_STALE: "RS_STALE",
    RS_DEMOTE: "RS_DEMOTE",
    RS_EEND: "RS_EEND",
}
_MIN_CONFIDENCE: dict[str, int] = {
    "Conservative": ENTRY_MIN_CONFIDENCE_CONSERVATIVE,
    "Standard": ENTRY_MIN_CONFIDENCE_STANDARD,
    "Aggressive": ENTRY_MIN_CONFIDENCE_AGGRESSIVE,
}
_MIN_READINESS: dict[str, int] = {
    "Conservative": ENTRY_MIN_TESTS_CONSERVATIVE,
    "Standard": ENTRY_MIN_TESTS_STANDARD,
    "Aggressive": ENTRY_MIN_TESTS_AGGRESSIVE,
}
