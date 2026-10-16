"""The script's pure helpers (L561-729, L932-974) and its Pine rounding.

Hand-computed values; each case cites the Pine expression it checks. ``int(math.round(x))``
rounds ties up in Pine (``round(4.5) = 5``), where Python's ``round`` gives 4: the spec
lists the places where that changes a bar count.
"""

import math

import pytest

from kterminal.strategies.wyckoff_auto.measures import clamp, pine_int_round, pmax, pmin
from kterminal.strategies.wyckoff_auto.state import (
    DIR_ACCUM,
    DIR_DIST,
    DIR_NONE,
    PHASE_A,
    PHASE_B,
    PHASE_C,
    PHASE_D,
    PHASE_E,
    PHASE_NONE,
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
    add_bit,
    bit_names,
    has_bit,
)
from kterminal.strategies.wyckoff_auto.wyckoff_engine import (
    cause_units,
    confidence,
    excursion_recovery_limit,
    hard_level,
    phase_a_min_bars,
    phase_b_character_improving,
    phase_b_min_bars,
    phase_c_to_d_min_bars,
    phase_d_min_bars,
    phase_idle_limit,
    robust_edge,
    structure_confidence,
    type_from,
    validation_score,
)
from kterminal.strategies.wyckoff_auto.wyckoff_engine import (
    test_class as classify,
)

NAN = math.nan


def test_pine_round_ties_go_up_where_python_rounds_to_even() -> None:
    assert pine_int_round(4.5) == 5 and round(4.5) == 4
    assert pine_int_round(2.5) == 3 and pine_int_round(3.5) == 4
    assert pine_int_round(4.4999999) == 4
    # f_excursionRecoveryLimit(6) = max(3, round(6 * 0.75)) = round(4.5) = 5 (spec)
    assert excursion_recovery_limit(6) == 5
    assert [excursion_recovery_limit(p) for p in range(1, 11)] == [3, 3, 3, 3, 4, 5, 5, 6, 7, 8]
    # f_phaseBMinBars ties: max(p * 6, rATR * p) = 48.5 → 49 (Python: 48), floor 30, cap 60
    assert phase_b_min_bars(2, 24.25) == 49
    assert phase_b_min_bars(4, 2.0) == 30  # max(24, 8) = 24 → floor 30
    assert phase_b_min_bars(10, 9.0) == 60  # max(60, 90) = 90 → cap 60
    assert phase_b_min_bars(0, 0.0) == 30  # p = max(p, 1)


def test_bar_count_helpers() -> None:
    assert [phase_a_min_bars(p) for p in (1, 3, 4, 10)] == [6, 6, 8, 20]  # max(6, 2p)
    # int(max(p, 1) / 2) truncates (L661)
    assert [phase_c_to_d_min_bars(p) for p in (1, 6, 7, 9, 10)] == [3, 3, 3, 4, 5]
    assert [phase_d_min_bars(p) for p in (2, 4, 7)] == [4, 4, 7]
    assert phase_idle_limit(PHASE_A, False, 4) == 30  # max(maxARBars, 4p)
    assert phase_idle_limit(PHASE_A, True, 4) == 45  # max(45, 6p)
    assert phase_idle_limit(PHASE_A, True, 10) == 60
    assert phase_idle_limit(PHASE_B, True, 4) == 125  # max(125, 20p)
    assert phase_idle_limit(PHASE_B, True, 10) == 200
    assert phase_idle_limit(PHASE_C, True, 4) == 50  # max(50, 8p)
    assert phase_idle_limit(PHASE_D, True, 4) == 100  # max(100, 16p)
    assert phase_idle_limit(PHASE_D, True, 10) == 160
    assert phase_idle_limit(PHASE_E, True, 4) is None  # na: Phase E never goes stale
    assert phase_idle_limit(PHASE_NONE, True, 4) is None


def test_pine_max_min_are_na_with_na() -> None:
    assert math.isnan(pmax(NAN, 1.0)) and math.isnan(pmax(1.0, NAN))
    assert math.isnan(pmin(NAN, 1.0))
    assert pmax(1.0, 2.0) == 2.0 and pmin(1.0, 2.0) == 1.0
    assert clamp(5.0, -3.0, 3.0) == 3.0 and clamp(-5.0, -3.0, 3.0) == -3.0


def test_bits() -> None:
    mask = add_bit(add_bit(0, 128), 128)  # f_addBit adds once
    assert mask == 128 and has_bit(mask, 128) and not has_bit(mask, 256)
    assert bit_names(2 | 8 | 16 | 16384) == ["SC", "AR", "ST", "C-Test"]


def test_robust_edge_is_the_median_of_three_capped_at_the_original_edge() -> None:
    # one test: halfway to the original edge (L697)
    assert robust_edge(120.0, NAN, NAN, 119.0, True) == 119.5
    # two: the pair's mean, halfway to the original edge (L695)
    assert robust_edge(120.0, 121.0, NAN, 119.0, True) == pytest.approx(119.75)
    # three: the median (L693)
    assert robust_edge(120.0, 122.0, 121.0, 119.0, True) == 121.0
    # never beyond the original edge: a low edge is at least orig (L698)
    assert robust_edge(118.0, 118.5, 118.2, 119.0, True) == 119.0
    assert robust_edge(130.0, 129.0, 131.0, 128.0, False) == 128.0
    assert robust_edge(126.0, 127.0, 125.0, 128.0, False) == 126.0
    assert robust_edge(NAN, NAN, NAN, 119.0, True) == 119.0


def test_type_from_and_confidence() -> None:
    # f_typeFrom (L700-702): an accumulation after a BC, or in a bull context, is a
    # re-accumulation; mirrored for distributions
    assert type_from(DIR_ACCUM, DIR_ACCUM, False, False) == TYPE_ACCUM
    assert type_from(DIR_DIST, DIR_ACCUM, False, False) == TYPE_REACCUM
    assert type_from(DIR_ACCUM, DIR_ACCUM, True, False) == TYPE_REACCUM
    assert type_from(DIR_DIST, DIR_DIST, False, False) == TYPE_DIST
    assert type_from(DIR_ACCUM, DIR_DIST, False, False) == TYPE_REDIST
    assert type_from(DIR_DIST, DIR_DIST, False, True) == TYPE_REDIST
    assert type_from(DIR_ACCUM, DIR_NONE, True, True) == TYPE_NONE
    # f_structureConfidence (L615-616): 10/15/10/15/15/15/10/10
    assert structure_confidence(True, True, True, True, True, True, True, True) == 100
    assert structure_confidence(True, True, True, True, False, False, False, False) == 50
    s = WS(cf_prior=True, cf_climax=True, cf_ar=True, cf_st=True, cf_exc=True)
    assert confidence(s) == 50  # a Spring alone does not complete Phase C (L933)
    s.cf_strength = True
    assert confidence(s) == 80  # Spring + strength does
    s.cf_strength, s.cf_test = False, True
    assert confidence(s) == 65


def test_validation_score_points() -> None:
    full = validation_score(-40.0, True, 5.0, 2, 1, 2, True, 3.0, True, True, True, True)
    assert full == 100  # 10+15+10+15+15+10+10+10+3+2 = 100, capped at 100
    # each band of L620-629
    assert validation_score(-20.0, False, 0.0, 0, 0, 0, False, 0.0, False, False, False, False) == 5
    assert validation_score(10.0, False, 1.2, 0, 0, 0, False, 0.0, False, False, False, False) == 5
    assert validation_score(10.0, False, 12.0, 1, 0, 1, False, 1.5, False, False, False, False) == (
        5 + 8 + 8 + 5
    )
    assert validation_score(NAN, False, 13.0, 0, 0, 0, False, 0.0, False, False, False, False) == 0
    # cause units: B age / max(6p, 1) + 0.5 per traversal + 0.5 for a wide range (L635-638)
    assert cause_units(2, 48, 4, 1.5) == pytest.approx(2.0 + 1.0 + 0.5)
    assert cause_units(0, 10, 0, 1.0) == 10.0  # max(6p, 1) = 1 for p = 0


def test_phase_b_test_class() -> None:
    # f_testClass (L640-649): near and holding, with effort and spread at most 0.9 of the
    # climax's, and the close in place, is GOOD
    assert classify(False, True, True, 1.0, 1.0, 10.0, 10.0) == TEST_NONE
    assert classify(True, False, True, 1.0, 1.0, 10.0, 10.0) == TEST_FAILED
    assert classify(True, True, True, 9.0, 9.0, 10.0, 10.0) == TEST_GOOD
    assert classify(True, True, True, 9.1, 9.0, 10.0, 10.0) == TEST_POOR
    assert classify(True, True, False, 1.0, 1.0, 10.0, 10.0) == TEST_POOR


def test_character_improving_needs_two_tests_and_a_quieter_last_one() -> None:
    assert not phase_b_character_improving(1, 100.0, 1.0, 50.0, 0.5)
    assert phase_b_character_improving(2, 200.0, 2.0, 100.0, 1.05)  # spread <= avg * 1.05
    assert not phase_b_character_improving(2, 200.0, 2.0, 101.0, 1.0)
    assert not phase_b_character_improving(2, 200.0, 2.0, NAN, 1.0)


def test_hard_level() -> None:
    """f_hardLevel (L723-729): the Spring/UTAD extreme when the campaign has one for that
    outcome, else the more extreme of the original and the current edge."""
    s = WS(stop_side=DIR_ACCUM, orig_low=119.5, range_low=119.8, orig_high=124.6, range_high=124.6)
    assert hard_level(s, DIR_ACCUM) == 119.5
    assert hard_level(s, DIR_DIST) == 124.6
    s.range_low = 119.2  # a Phase B low under the original one
    assert hard_level(s, DIR_ACCUM) == 119.2
    s.exc, s.outcome, s.exc_price = True, DIR_ACCUM, 118.9
    assert hard_level(s, DIR_ACCUM) == 118.9
    assert hard_level(s, DIR_DIST) == 124.6  # the Spring is no UTAD
    s.outcome = DIR_DIST
    assert hard_level(s, DIR_ACCUM) == 119.2
    t = WS(stop_side=DIR_DIST, range_low=100.0)
    assert hard_level(t, DIR_ACCUM) == 100.0  # no original low: the range low
    assert math.isnan(hard_level(WS(), DIR_ACCUM))
    u = WS(orig_high=130.0)
    assert hard_level(u, DIR_DIST) == 130.0  # nz(rangeHigh, origHigh)
