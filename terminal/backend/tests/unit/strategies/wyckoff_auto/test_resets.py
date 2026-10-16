"""The seven ways a campaign ends (``rsCounts``, L257-263: RS_INVALID, RS_ABSORB,
RS_NORANGE, RS_DEPART, RS_STALE, RS_DEMOTE, RS_EEND) and its replacement by a new climax,
each on a targeted tape, on the bar the script retires it."""

import copy
import math

import pytest

from kterminal.strategies.wyckoff_auto.state import (
    DIR_ACCUM,
    DIR_DIST,
    DIR_NONE,
    PHASE_A,
    PHASE_B,
    PHASE_C,
    PHASE_D,
    PHASE_E,
    RS_ABSORB,
    RS_DEMOTE,
    RS_DEPART,
    RS_EEND,
    RS_INVALID,
    RS_NORANGE,
    RS_STALE,
    bit_names,
)
from tests.unit.strategies.wyckoff_auto.scenario import (
    ADOPTED,
    DEMOTED,
    E_FAILED,
    E_TIMEOUT,
    NEW_SC,
    PROVISIONAL,
    RESEEDED,
    RETEST,
    SC,
    SOS,
    SPRING_LOW,
    STALE_C,
    TEST,
    Tape,
    absorption_fails,
    accumulation,
    demoted_then_tested_again,
    no_automatic_rally,
    phase_a_invalidated,
    phase_b_departs,
    phase_b_goes_stale,
    phase_c_goes_stale_then_new_climax,
    phase_c_invalidated,
    phase_d_demoted,
    phase_d_invalidated,
    phase_e_fails,
    phase_e_replaced,
    phase_e_times_out,
    provisional_spring,
    run_engine,
)
from tests.unit.strategies.wyckoff_auto.scenario import (
    PHASE_E as E_BAR,
)

PIVOT = 4

# (tape, the end's kind, the bar, the phase it ended in, the reset counter it bumps)
ENDS = [
    (absorption_fails, "RS_ABSORB", SC + 9, PHASE_A, RS_ABSORB),
    (no_automatic_rally, "RS_NORANGE", SC + 31, PHASE_A, RS_NORANGE),
    (phase_a_invalidated, "RS_INVALID", SC + 4, PHASE_A, RS_INVALID),
    (phase_b_goes_stale, "RS_STALE", 419, PHASE_B, RS_STALE),
    (phase_b_departs, "RS_DEPART", 310, PHASE_B, RS_DEPART),
    (phase_c_invalidated, "RS_INVALID", TEST + PIVOT + 5, PHASE_C, RS_INVALID),
    (phase_c_goes_stale_then_new_climax, "RS_STALE", STALE_C, PHASE_C, RS_STALE),
    (phase_d_invalidated, "RS_INVALID", SOS + 4, PHASE_D, RS_INVALID),
    (phase_e_fails, "RS_EEND", E_FAILED, PHASE_E, RS_EEND),
    (phase_e_times_out, "RS_EEND", E_TIMEOUT, PHASE_E, RS_EEND),
]


@pytest.mark.parametrize(
    ("build", "kind", "bar", "phase", "counter"),
    ENDS,
    ids=[f"{b.__name__}" for b, *_ in ENDS],
)
def test_each_reset_retires_the_campaign_on_its_bar(
    build: object, kind: str, bar: int, phase: int, counter: int
) -> None:
    assert callable(build)
    tape: Tape = build()
    trace = run_engine(tape)
    assert trace.ends(kind) == [bar], trace.describe(SC - 2)
    end = next(e for e in trace.steps[bar].ends if e.kind == kind)
    assert end.phase == phase
    assert end.serial == trace.steps[bar - 1].serial  # the campaign alive before the bar
    assert trace.steps[bar].serial != end.serial  # WS.new() (L1233, L1675)
    assert trace.after[bar].phase == "-"
    engine = trace.engine
    assert engine is not None
    assert engine.rs_counts[counter] == 1
    assert engine.last_reset_why == counter
    # nothing else ended any campaign on the way
    assert sum(len(s.ends) for s in trace.steps) == 1 + len(trace.ends("RESEED"))


def test_phase_a_invalidation_compares_two_closes_with_the_climax() -> None:
    trace = run_engine(phase_a_invalidated())
    end = trace.steps[SC + 4].ends[0]
    assert end.detail["climax_price"] == 119.5
    # the bar before had only one close under 119.5 - 0.5 ATR
    m = trace.steps[SC + 3].m
    assert m.hi_c_inv >= 119.5 - 0.5 * m.a


def test_phase_c_invalidation_uses_the_spring_as_the_hard_level() -> None:
    trace = run_engine(phase_c_invalidated())
    end = trace.steps[TEST + PIVOT + 5].ends[0]
    assert end.outcome == DIR_ACCUM
    assert end.detail["hard_level"] == SPRING_LOW
    atr = trace.steps[TEST + PIVOT + 5].m.a
    assert end.detail["invalidation_level"] == pytest.approx(SPRING_LOW - 0.5 * atr)
    assert end.detail["closes_2"] < end.detail["invalidation_level"]  # type: ignore[operator]


def test_phase_e_ends_on_three_closes_under_the_middle_or_after_300_bars() -> None:
    failed = run_engine(phase_e_fails()).steps[E_FAILED].ends[0]
    assert failed.detail["e_fail"] is True and failed.detail["e_old"] is False
    assert failed.detail["range_mid"] == pytest.approx((124.6 + 119.825) / 2)
    old = run_engine(phase_e_times_out()).steps[E_TIMEOUT].ends[0]
    assert old.detail == {
        "e_fail": False,
        "e_old": True,
        "range_mid": pytest.approx((124.6 + 119.825) / 2),
        "closes_3": pytest.approx(127.1),
        "phase_e_bars": 301,  # bar_index - eStartBar > 300 (L1222)
    }
    assert E_TIMEOUT - E_BAR == 301


def test_d_to_b_demotion_keeps_the_campaign_and_clears_its_outcome() -> None:
    trace = run_engine(phase_d_demoted())
    assert trace.ends("RS_DEMOTE") == [DEMOTED]
    end = trace.steps[DEMOTED].ends[0]
    assert (end.phase, end.outcome) == (PHASE_D, DIR_ACCUM)
    assert trace.steps[DEMOTED].serial == end.serial  # the same WS: not a reset
    engine = trace.engine
    assert engine is not None
    s = engine.s
    assert (s.phase, s.outcome) == (PHASE_B, DIR_NONE)
    assert not (s.exc or s.cf_test or s.cf_strength or s.cf_lps)  # f_clearTerminal etc.
    assert s.last_bad_bar == DEMOTED
    assert engine.rs_counts[RS_DEMOTE] == 1 and engine.last_reset_why == -1
    # f_demoteToB does not touch the entry (L909-930)
    assert not math.isnan(s.entry_time) and s.entry_price == pytest.approx(121.9)


def test_a_demoted_campaign_never_enters_again() -> None:
    """The spec's 'no re-entry after demotion': entryTime survives f_demoteToB, so the
    new Spring's qualifying Test at 343 is not evaluated (L1729)."""
    tape = demoted_then_tested_again()
    trace = run_engine(tape)
    assert "Spring" in bit_names(trace.steps[333].sig)
    assert "Test" in bit_names(trace.steps[RETEST].sig)
    assert trace.entries() == [TEST + PIVOT]  # only the first one, before the demotion
    assert trace.steps[RETEST].entry_check is None
    # with entryTime cleared the same bar would have entered: it is the only gate
    replay = run_engine(tape.rows[:RETEST])
    engine = copy.deepcopy(replay.engine)
    assert engine is not None
    engine.s.entry_time = math.nan
    o, h, low, c, v = tape.rows[RETEST]
    step = engine.update(RETEST, 0.0, o, h, low, c, v)
    assert step.entry_check is not None and step.entry_check.triggers == ["standardTestTrig"]


def test_a_new_climax_in_phase_e_replaces_the_campaign() -> None:
    trace = run_engine(phase_e_replaced())
    assert trace.ends("RESEED") == [RESEEDED]
    step = trace.steps[RESEEDED]
    end = step.ends[0]
    assert (end.phase, end.outcome, end.stop_side) == (PHASE_E, DIR_ACCUM, DIR_ACCUM)
    assert end.detail["new_side"] == DIR_DIST
    assert step.seeded == DIR_DIST and step.serial != end.serial
    assert trace.after[RESEEDED].phase == "A"
    assert "BC" in bit_names(trace.steps[RESEEDED + 3].sig)  # absorbed
    engine = trace.engine
    assert engine is not None
    assert engine.s.stop_side == DIR_DIST and engine.s.ctx_bull  # recent markup (L1267)
    assert sum(engine.rs_counts) == 0  # a reseed is not a reset


def test_a_climax_after_a_stale_reset_seeds_into_an_empty_slot() -> None:
    trace = run_engine(phase_c_goes_stale_then_new_climax())
    assert trace.ends("RS_STALE") == [STALE_C]
    assert trace.ends("RESEED") == []  # nothing to replace: the slot was empty
    assert trace.steps[NEW_SC].seeded == DIR_ACCUM
    assert trace.after[NEW_SC - 1].phase == "-" and trace.after[NEW_SC].phase == "A"


def test_a_deeper_climax_replaces_a_phase_a_campaign() -> None:
    """canSC (L1261): in Phase A a lower low that is itself a climax reseeds."""
    t = accumulation("sc").cut(SC + 2)  # SC at 260, one bar after it
    c = t.close
    t.bar(c, c + 0.2, c - 3.0, c - 1.5, 600)  # 262: lower low, 6x effort, wide
    trace = run_engine(t)
    assert trace.ends("RESEED") == [SC + 2], trace.describe(SC - 2)
    assert trace.steps[SC + 2].ends[0].phase == PHASE_A
    engine = trace.engine
    assert engine is not None
    assert engine.s.climax_bar == SC + 2 and engine.s.climax_price == pytest.approx(c - 3.0)


def test_the_provisional_spring_is_adopted_on_the_breakout() -> None:
    trace = run_engine(provisional_spring())
    after = trace.engine
    assert after is not None
    replay = run_engine(provisional_spring().rows[: PROVISIONAL + 1]).engine
    assert replay is not None
    s = replay.s
    assert (s.phase, s.prov_edge, s.prov_bar, s.prov_price) == (PHASE_B, DIR_ACCUM, 297, 119.4)
    assert not s.pend and not s.exc
    assert bit_names(trace.steps[ADOPTED].sig) == ["Spring", "SOS"]
    assert trace.after[ADOPTED].phase == "D"
    assert (after.s.exc, after.s.exc_bar, after.s.exc_price) == (True, 297, 119.4)
    assert after.s.prov_edge == 0 and math.isnan(after.s.test_time)
    assert trace.ends("RS_DEPART") == []
