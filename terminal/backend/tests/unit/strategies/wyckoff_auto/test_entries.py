"""The Auto entry (L1729-1747) for each Entry Strictness: which bar qualifies, which Pine
trigger fires, the entry kind, and the quality gates (confidence, validation, readiness).
"""

import copy
import math

import pytest

from kterminal.strategies.wyckoff_auto.state import (
    DIR_ACCUM,
    DIR_DIST,
    ENTRY_LPS,
    ENTRY_STRENGTH,
    ENTRY_TEST,
)
from kterminal.strategies.wyckoff_auto.wyckoff_engine import EntryCheck, Strictness
from tests.unit.strategies.wyckoff_auto.scenario import (
    ADOPTED,
    C_TEST_CONFIRMED,
    LPS,
    SOS,
    TEST,
    Tape,
    accumulation,
    distribution,
    provisional_spring,
    run_engine,
    terminal_test,
)

PIVOT = 4
TEST_BAR = TEST + PIVOT  # 318: the Spring's Test is confirmed
LPS_BAR = LPS + PIVOT  # 333: the LPS is confirmed

# (tape, strictness) → (entry bar, Pine trigger, entry kind) or None
EXPECTED: list[tuple[str, Strictness, tuple[int, str, int] | None]] = [
    ("canonical", "Standard", (TEST_BAR, "standardTestTrig", ENTRY_TEST)),
    ("canonical", "Aggressive", (TEST_BAR, "aggressiveTestTrig", ENTRY_TEST)),
    ("canonical", "Conservative", (LPS_BAR, "conservativeLpsTrig", ENTRY_LPS)),
    ("c_test", "Standard", (C_TEST_CONFIRMED, "standardTestTrig", ENTRY_TEST)),
    ("c_test", "Aggressive", (C_TEST_CONFIRMED, "aggressiveTestTrig", ENTRY_TEST)),
    ("c_test", "Conservative", None),  # no LPS on that tape
    ("provisional", "Aggressive", (ADOPTED, "aggressiveStrengthFallback", ENTRY_STRENGTH)),
    ("provisional", "Standard", None),  # SOS is no Standard trigger
    ("provisional", "Conservative", None),
]
TAPES = {"canonical": accumulation, "c_test": terminal_test, "provisional": provisional_spring}


@pytest.mark.parametrize(("tape", "strictness", "expected"), EXPECTED)
def test_entry_bar_trigger_and_kind(
    tape: str, strictness: Strictness, expected: tuple[int, str, int] | None
) -> None:
    rows = TAPES[tape]()
    trace = run_engine(rows, strictness=strictness)
    if expected is None:
        assert trace.entries() == [], trace.describe(300)
        return
    bar, trigger, kind = expected
    assert trace.entries() == [bar], trace.describe(300)
    check = trace.steps[bar].entry_check
    assert check is not None
    assert check.triggers == [trigger] and check.kind == kind
    assert check.direction == DIR_ACCUM and check.quality
    engine = trace.engine
    assert engine is not None
    s = engine.s
    # L1745-1747: stamped once with the bar's time and close
    assert s.entry_time == trace.steps[bar].m.time
    assert s.entry_price == rows.rows[bar][3]
    assert s.entry_kind == kind


def test_a_distribution_enters_short() -> None:
    trace = run_engine(distribution())
    assert trace.entries() == [TEST_BAR]
    check = trace.steps[TEST_BAR].entry_check
    assert check is not None and check.direction == DIR_DIST


def test_one_entry_per_campaign() -> None:
    """After the Standard Test entry, the LPS (a Standard trigger too) is not evaluated:
    na(s.entryTime) is false (L1729)."""
    trace = run_engine(accumulation())
    assert trace.entries() == [TEST_BAR]
    assert trace.steps[LPS_BAR].entry_check is None
    assert trace.steps[SOS].entry_check is None


def test_conservative_skips_the_test_and_the_sos_on_their_gates() -> None:
    trace = run_engine(accumulation(), strictness="Conservative")
    test = trace.steps[TEST_BAR].entry_check
    sos = trace.steps[SOS].entry_check
    assert test is not None and sos is not None
    # the Test fails readiness (6 < 7) and is no Conservative trigger anyway
    assert (test.readiness, test.min_readiness, test.quality, test.triggers) == (6, 7, False, [])
    # the SOS passes every gate but only an LPS triggers a Conservative entry (L1743)
    assert sos.quality and sos.strength_bit and sos.triggers == []
    lps = trace.steps[LPS_BAR].entry_check
    assert lps is not None
    assert (lps.confidence, lps.validation, lps.readiness) == (90, 100, 9)
    assert (lps.min_confidence, lps.validation_floor, lps.min_readiness) == (75, 60, 7)


def _entry_with(tape: Tape, bar: int, strictness: Strictness, **changes: object) -> EntryCheck:
    """The entry check of ``bar`` after changing the campaign right before it."""
    engine = copy.deepcopy(run_engine(tape.rows[:bar], strictness=strictness).engine)
    assert engine is not None
    for name, value in changes.items():
        setattr(engine.s, name, value)
    o, h, low, c, v = tape.rows[bar]
    check = engine.update(bar, 0.0, o, h, low, c, v).entry_check
    assert check is not None
    return check


def test_the_confidence_floor_differs_per_strictness() -> None:
    """Without the AR flag the structure confidence at the Test is 55 (L615-616): under
    Standard's 60, enough for Aggressive's 55 (L1730, L1735)."""
    tape = accumulation()
    standard = _entry_with(tape, TEST_BAR, "Standard", cf_ar=False)
    assert (standard.confidence, standard.quality, standard.triggers) == (55, False, [])
    aggressive = _entry_with(tape, TEST_BAR, "Aggressive", cf_ar=False)
    assert aggressive.quality and aggressive.triggers == ["aggressiveTestTrig"]


def test_the_validation_floor_is_50_for_standard() -> None:
    """f_validationWS (L936-943) at the Test is 95; without absorption (15), prior trend
    (10, birth trend 0), opposite test and traversals (15), a clean history (10) and
    cause (10) it falls to 35, under the floor of max(45, 60 - 10) = 50 (L1732)."""
    tape = accumulation()
    check = _entry_with(
        tape,
        TEST_BAR,
        "Standard",
        absorbed=False,
        birth_trend=0.0,
        opp_count=0,
        trav_count=0,
        last_bad_bar=TEST_BAR - 1,
        b_start_bar=TEST_BAR - 1,
    )
    assert check.validation < 50 and check.validation_floor == 50
    assert not check.quality and check.triggers == []


def test_readiness_counts_the_distance_from_the_range() -> None:
    """f_entryReadinessWS (L958-974): with a range high far under the close the
    'within 2 ATR' point is lost (and so is the entry at readiness 6)."""
    tape = accumulation()
    check = _entry_with(tape, TEST_BAR, "Standard", range_high=100.0)
    assert check.readiness == 6 and check.quality is True  # 7 - 1: still enough
    check = _entry_with(tape, TEST_BAR, "Standard", range_high=100.0, cf_ar=False)
    assert check.readiness < 6 and not check.quality


def test_no_entry_without_an_outcome() -> None:
    trace = run_engine(accumulation("phase_b"))
    assert all(step.entry_check is None for step in trace.steps)
    engine = trace.engine
    assert engine is not None and math.isnan(engine.s.entry_time)
