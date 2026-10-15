"""The script's PSAR state machine (script 4, L607-638), value by value."""

import math

import pytest
from pydantic import ValidationError

from kterminal.strategies.psar_ema200 import PsarEma200, PsarEma200Params, PsarState
from kterminal.strategy_engine.registry import definition_from_class

NONE = (False, False, False, False)
GO_LONG = (True, False, False, False)
GO_SHORT = (False, True, False, False)
UP, DOWN = 99.0, 101.0  # SAR values below / above a close of 100
CLOSE = 100.0


def step(
    state: PsarState, sar: float, *, ema: float = 95.0, adx: float = 30.0, close: float = CLOSE
) -> tuple[bool, bool, bool, bool]:
    return state.update(sar, close, ema, adx, 20.0)


def test_a_flip_is_the_sar_crossing_the_close_on_this_bar() -> None:
    state = PsarState()
    assert step(state, UP) == GO_LONG  # psSarBull[1] is false before the first bar (v6)
    assert step(state, UP - 1) == NONE  # still below: no new flip
    assert step(state, DOWN, ema=105.0) == (False, True, True, False)  # exit long, go short


def test_the_trend_filter_needs_the_close_strictly_beyond_the_ema() -> None:
    for ema, expected in ((99.0, GO_LONG), (100.0, NONE), (100.0 - 5e-11, NONE), (101.0, NONE)):
        assert step(PsarState(), UP, ema=ema) == expected, ema
    for ema, expected in ((101.0, GO_SHORT), (100.0, NONE), (99.0, NONE)):
        assert step(PsarState(), DOWN, ema=ema) == expected, ema


def test_adx_must_be_strictly_above_the_threshold() -> None:
    assert step(PsarState(), UP, adx=20.0) == NONE
    assert step(PsarState(), UP, adx=20.0 + 5e-11) == NONE  # Pine's 1e-10 tolerance
    assert step(PsarState(), UP, adx=20.001) == GO_LONG


def test_entries_only_on_the_flip_bar() -> None:
    """A leg whose flip bar fails a filter is never entered, even when the filter passes on
    the next bar (L630-631)."""
    state = PsarState()
    assert step(state, UP, adx=10.0) == NONE
    assert step(state, UP - 1, adx=40.0) == NONE


def test_exits_ignore_the_filters_and_the_strategy_goes_flat() -> None:
    state = PsarState()
    assert step(state, UP) == GO_LONG
    # flip down, but the close is above the EMA and the ADX is weak: exit only (L621)
    assert step(state, DOWN, ema=95.0, adx=5.0) == (False, False, True, False)
    assert (state.in_long, state.in_short) == (False, False)
    assert step(state, UP) == GO_LONG  # the next up flip enters again


def test_short_side_mirrors() -> None:
    state = PsarState()
    assert step(state, DOWN, ema=105.0) == GO_SHORT
    assert step(state, UP, ema=95.0) == (True, False, False, True)  # exit short, go long
    assert (state.in_long, state.in_short) == (True, False)


def test_sar_equal_to_the_close_re_arms_the_flip_but_not_the_entry() -> None:
    """psSar == close is neither bull nor bear, so the next bar below the close is a new
    'flip up' without a SAR reversal; already long, the script does not enter again."""
    state = PsarState()
    assert step(state, UP) == GO_LONG
    assert step(state, CLOSE) == NONE  # equal: no state, no exit (not bear)
    assert step(state, UP) == NONE  # flip up again: blocked by `not psInLong`
    assert state.in_long


def test_na_values_never_signal() -> None:
    nan = math.nan
    assert step(PsarState(), nan) == NONE  # SAR na on the first bar
    assert step(PsarState(), UP, ema=nan) == NONE  # EMA200 warming up
    assert step(PsarState(), UP, adx=nan) == NONE  # ADX warming up


@pytest.mark.parametrize(
    "bad",
    [
        {"stop_mode": "projected"},
        {"psar_start": 0.0},
        {"maximum": 0.0},
        {"threshold": -1},
        {"ma_slow_length": 0},
        {"increment": -0.01},
    ],
)
def test_params_reject_invalid_values(bad: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        PsarEma200Params.model_validate(bad)


def test_params_and_definition_follow_the_script_and_doc13() -> None:
    p = PsarEma200Params()
    assert (p.ma_slow_length, p.psar_start, p.increment, p.maximum) == (200, 0.02, 0.02, 0.2)
    assert (p.adx_smoothing, p.di_length, p.threshold, p.stop_mode) == (14, 14, 20, "sar")
    meta = definition_from_class(PsarEma200).meta
    assert (meta.id, meta.on_opposite_signal, meta.skip_entry_beyond_levels) == (
        "psar_ema200",
        "reverse",
        True,
    )
    assert meta.warmup_bars >= 1_000
