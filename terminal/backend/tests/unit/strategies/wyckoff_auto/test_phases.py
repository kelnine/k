"""The campaign through Phases A-E on the canonical accumulation (and its mirror image, a
distribution): each transition on the bar the script makes it, for the reason it makes it.

Bar numbers are row indexes of :func:`scenario.accumulation`; a swing pivot is confirmed
``pLen`` (here 4) bars after its bar, so a Test or LPS written on bar ``k`` acts on
``k + 4``.
"""

import math

import pytest

from kterminal.strategies.wyckoff_auto.state import (
    DIR_ACCUM,
    DIR_DIST,
    DIR_NONE,
    EV_LPS,
    EV_LPSY,
    EV_MARKDOWN,
    EV_MARKUP,
    EV_SOS,
    EV_SOW,
    EV_TEST,
    PHASE_C,
    REGIME_MARKDOWN,
    REGIME_MARKUP,
    REGIME_NONE,
    bit_names,
)
from tests.unit.strategies.wyckoff_auto.scenario import (
    AR_PEAK,
    LPS,
    OPP,
    PHASE_E,
    RANGE_HIGH,
    SC,
    SOS,
    SPRING,
    SPRING_LOW,
    ST1,
    ST2,
    TEST,
    Trace,
    accumulation,
    distribution,
    run_engine,
)

PIVOT = 4  # pLen of the canonical tape: 4 * ATR / SMA(ATR, 50), frozen at the seed
# (bar, the campaign's phase after it, the event bits it sets)
TRANSITIONS = [
    (SC, "A", []),  # L1263-1271: the climax seeds Phase A on its own bar
    (SC + 3, "A", ["SC"]),  # L1280-1288: absorption 3 bars later confirms it
    (ST1 + PIVOT, "B", ["AR", "ST"]),  # L1371-1390: the first ST fixes the AR
    (ST2 + PIVOT, "B", ["ST"]),  # L1426-1428: a second, quieter ST
    (SPRING, "C", ["Spring"]),  # L1587-1591: a probe that recovers on its own bar
    (TEST + PIVOT, "C", ["Test"]),  # L1477-1489: the Spring's Test
    (SOS, "D", ["SOS"]),  # L1623-1632: sign of strength
    (LPS + PIVOT, "D", ["LPS"]),  # L1504-1516: last point of support
    (PHASE_E, "E", ["Phase E"]),  # L1700-1713: acceptance above the range
]


def changes(trace: Trace, start: int = SC - 5) -> list[tuple[int, str, list[str]]]:
    """Every bar from ``start`` on that changes the phase or sets an event bit."""
    out = []
    previous = trace.after[start - 1].phase
    for i in range(start, len(trace.steps)):
        phase = trace.after[i].phase
        names = bit_names(trace.steps[i].sig)
        if names or phase != previous:
            out.append((i, phase, names))
        previous = phase
    return out


@pytest.fixture(scope="module")
def acc() -> Trace:
    return run_engine(accumulation())


@pytest.fixture(scope="module")
def dist() -> Trace:
    return run_engine(distribution())


def test_the_accumulation_walks_through_every_phase_on_the_scripted_bars(acc: Trace) -> None:
    assert changes(acc) == TRANSITIONS, acc.describe(SC - 5)
    assert acc.phases()[: SC] == ["-"] * SC  # nothing before the climax
    assert acc.ends("RS_INVALID") == acc.ends("RS_STALE") == []


def test_the_distribution_is_the_mirror_image(dist: Trace) -> None:
    mirrored = {
        "SC": "BC",
        "Spring": "UTAD",
        "SOS": "SOW",
        "LPS": "LPSY",
    }
    expected = [(i, phase, [mirrored.get(n, n) for n in names]) for i, phase, names in TRANSITIONS]
    assert changes(dist) == expected, dist.describe(SC - 5)


def test_phase_a_seeds_on_the_climax_bar_with_its_extreme_and_effort(acc: Trace) -> None:
    step = acc.steps[SC]
    assert step.seeded == DIR_ACCUM
    engine = run_engine(accumulation("sc")).engine
    assert engine is not None
    s = engine.s
    assert (s.stop_side, s.outcome, s.climax_bar, s.climax_price) == (DIR_ACCUM, DIR_NONE, SC, 119.5)
    assert s.orig_low == s.range_low == 119.5  # f_seed (L746-748)
    assert s.climax_eff == 400.0 and s.climax_spr == pytest.approx(2.7)
    assert s.climax_score == 6  # every one of the six points (L1258)
    assert s.piv_len == PIVOT  # liveLen[3], frozen for the campaign (L1089, L1271)
    assert s.cf_prior and s.absorbed and s.cf_climax  # absorbed at SC + 3 (L1285-1286)
    # the AR runs on the highs after the climax and becomes the range high once both
    # the absorption and a 2-ATR rally are in (L1292-1311)
    assert s.ar_run_bar == AR_PEAK and s.ar_run_price == pytest.approx(RANGE_HIGH)
    assert s.range_high == s.orig_high == s.ar_run_price
    assert s.ar_bar is None  # fixed only when the ST arrives


def test_phase_b_starts_at_the_st_pivot_and_the_range_low_is_the_robust_median(
    acc: Trace,
) -> None:
    after = acc.after
    assert after[ST1 + PIVOT].st_count == 1
    # f_robustEdge with one test: (ST1 low + SC low) / 2, never below the SC low (L697)
    assert after[ST1 + PIVOT].range_low == pytest.approx((120.1 + 119.5) / 2)
    # L1454-1462: the opposite test at the AR high has no event bit
    assert (after[OPP + PIVOT - 1].opp_count, after[OPP + PIVOT].opp_count) == (0, 1)
    assert after[ST2 + PIVOT].st_count == 2
    # two tests: ((ST2 + ST1) / 2 + SC low) / 2 (L695)
    assert after[ST2 + PIVOT].range_low == pytest.approx(((120.2 + 120.1) / 2 + 119.5) / 2)
    assert after[ST2 + PIVOT].trav_count == 2  # low zone → high zone → low zone (L1465-1475)
    engine = run_engine(accumulation("phase_b")).engine
    assert engine is not None
    s = engine.s
    assert (s.b_start_bar, s.ar_bar, s.st_bar) == (ST1, AR_PEAK, ST2)  # back-dated pivots
    assert s.cf_ar and s.cf_st and s.st_hist is not None
    assert (s.st_hist.b1, s.st_hist.b2, s.st_hist.b3) == (ST1, ST2, None)
    assert s.op_hist is not None and s.op_hist.b1 == OPP
    assert engine.mature(s, PIVOT, 0.8, SPRING - 1)  # 30 bars, 2 tests, support ≥ 2


def test_the_spring_sets_the_outcome_and_its_test_marks_phase_c_ready(acc: Trace) -> None:
    engine = run_engine(accumulation("test")).engine
    assert engine is not None
    s = engine.s
    assert s.phase == PHASE_C and s.outcome == DIR_ACCUM
    assert s.exc and s.exc_tested and s.cf_exc and s.cf_test
    assert (s.exc_bar, s.exc_price) == (SPRING, SPRING_LOW)
    assert (s.test_price, s.test_score, s.c_ready_bar) == (119.7, 3, TEST + PIVOT)
    assert s.ev == EV_TEST
    assert acc.after[SPRING].outcome == DIR_ACCUM  # f_excFromPend (L860)


def test_sos_lps_and_acceptance(acc: Trace) -> None:
    sos = run_engine(accumulation("sos")).engine
    assert sos is not None
    assert (sos.s.ev, sos.s.str_bar, sos.s.d_start_bar) == (EV_SOS, SOS, SOS)
    assert sos.s.str_price == pytest.approx(125.3)  # the SOS bar's HIGH (L1631)
    assert sos.s.cf_strength
    lps = run_engine(accumulation("lps")).engine
    assert lps is not None
    assert (lps.s.ev, lps.s.lps_bar, lps.s.lps_price) == (EV_LPS, LPS + PIVOT, 123.7)
    engine = acc.engine
    assert engine is not None
    s = engine.s
    assert (s.ev, s.e_start_bar, s.cf_accept) == (EV_MARKUP, PHASE_E, True)
    assert (engine.regime, engine.regime_bar) == (REGIME_MARKUP, PHASE_E)  # L1710-1711


def test_the_distribution_leaves_a_markdown_regime(dist: Trace) -> None:
    engine = dist.engine
    assert engine is not None
    assert (engine.s.ev, engine.regime, engine.regime_bar) == (
        EV_MARKDOWN,
        REGIME_MARKDOWN,
        PHASE_E,
    )
    assert engine.s.outcome == DIR_DIST and engine.s.exc_price == pytest.approx(600 - SPRING_LOW)
    lpsy = run_engine(distribution("lps")).engine
    assert lpsy is not None and lpsy.s.ev == EV_LPSY
    sow = run_engine(distribution("sos")).engine
    assert sow is not None and sow.s.ev == EV_SOW
    assert sow.s.str_price == pytest.approx(600 - 125.3)  # the SOW bar's LOW (L1640)


def test_the_regime_holds_back_an_opposite_campaign_for_25_bars() -> None:
    """``ageOKBear`` (L1176): after a markup, a distribution may promote to Phase D only
    once its structure is 25 bars old. The mirrored tape's SOW at 323 is 63 bars after
    its BC; moving the campaign's start to 3 bars before the SOW blocks the promotion."""
    tape = distribution("sos")
    engine = run_engine(tape.rows[:SOS]).engine
    assert engine is not None and engine.s.phase == PHASE_C
    engine.regime, engine.regime_bar = REGIME_MARKUP, SOS - 10
    engine.s.start_bar = SOS - 3
    o, h, low, c, v = tape.rows[SOS]
    step = engine.update(SOS, 0.0, o, h, low, c, v)
    assert "SOW" not in bit_names(step.sig) and engine.s.phase == PHASE_C
    # the same bar with a 25-bar-old structure promotes
    fresh = run_engine(tape.rows[:SOS]).engine
    assert fresh is not None
    fresh.regime, fresh.regime_bar = REGIME_MARKUP, SOS - 10
    fresh.s.start_bar = SOS - 25
    assert "SOW" in bit_names(fresh.update(SOS, 0.0, o, h, low, c, v).sig)


def test_no_regime_before_the_first_phase_e(acc: Trace) -> None:
    engine = run_engine(accumulation("lps")).engine
    assert engine is not None
    assert (engine.regime, engine.regime_bar) == (REGIME_NONE, None)


def test_the_spring_deepens_until_its_test(acc: Trace) -> None:
    """L1598-1610: a lower low (within 2.5 ATR of the range low) before the Test moves the
    Spring — and with it the hard level, the D5 stop's basis."""
    tape = accumulation("spring")  # through 308
    tape.bar(120.95, 121.0, 118.9, 120.6)  # 309: 0.3 under the Spring, 0.9 under the range
    engine = run_engine(tape).engine
    assert engine is not None
    assert (engine.s.exc_bar, engine.s.exc_price) == (SPRING + 1, 118.9)
    assert engine.s.exc_eff == 140.0  # max(Spring effort, this bar's) (L1603)


def test_a_probe_that_goes_too_deep_is_dropped_and_cools_down() -> None:
    """L1592-1596: a pending probe beyond 2.5 ATR is dropped, marks a bad test in Phase B
    and blocks new probes for pLen bars."""
    tape = accumulation("spring").cut(SPRING)  # through 307, Phase B mature
    tape.bar(120.4, 120.5, 119.6, 119.7)  # 308: 0.2 under the range low → pending
    tape.bar(119.7, 119.8, 117.0, 117.2)  # 309: 2.8 under it, more than 2.5 ATR
    tape.path([118.0, 119.0])
    trace = run_engine(tape)
    engine = trace.engine
    assert engine is not None
    s = engine.s
    assert not s.pend and not s.exc
    assert s.last_bad_bar == SPRING + 1
    assert s.pend_cool_bar == SPRING + 1 + PIVOT
    assert all(not bit_names(step.sig) for step in trace.steps[SPRING:])


def test_the_swing_length_is_frozen_for_the_campaign(acc: Trace) -> None:
    """pLen = the campaign's pivLen while one is active (L1105); the live ATR-adaptive
    length keeps moving with the ATR (L1085-1088)."""
    for i in range(SC + 1, len(acc.steps)):
        assert acc.steps[i].m.p_len == PIVOT
    assert {acc.steps[i].m.live_len for i in range(SC, len(acc.steps))} >= {3, 4}


def test_every_campaign_value_is_finite_where_the_script_sets_it(acc: Trace) -> None:
    engine = acc.engine
    assert engine is not None
    s = engine.s
    for name in ("range_high", "range_low", "climax_price", "exc_price", "test_price"):
        assert math.isfinite(getattr(s, name)), name
