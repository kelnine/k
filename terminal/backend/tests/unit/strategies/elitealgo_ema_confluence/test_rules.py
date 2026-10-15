"""The confluence count, stars and params of the EliteAlgo port (script 9, L6-24, L53-71)."""

import math

import pytest
from pydantic import ValidationError

from kterminal.strategies.elitealgo_ema_confluence.strategy import (
    CHECK_NAMES,
    N_CHECKS,
    EliteAlgoEmaConfluence,
    EliteAlgoParams,
    bull_count,
    stars,
)
from kterminal.strategy_engine.registry import definition_from_class

BULLISH = {
    "close": 101.0,
    "open_": 100.0,
    "ema_trend": 99.0,
    "ema_fast": 100.5,
    "ema_slow": 100.2,
    "rsi": 60.0,
    "di_plus": 30.0,
    "di_minus": 20.0,
    "pulse_hist": 0.5,
    "vwap": 100.0,
}
# Each check and the input change that turns it into a tie (Pine: not ">", so bearish).
TIES = {
    "close_above_ema_trend": {"ema_trend": 101.0},
    "ema_fast_above_ema_slow": {"ema_slow": 100.5},
    "rsi_above_50": {"rsi": 50.0},
    "di_plus_above_di_minus": {"di_minus": 30.0},
    "pulse_hist_above_0": {"pulse_hist": 0.0},
    "close_above_open": {"open_": 101.0},
    "close_above_vwap": {"vwap": 101.0},
}


def test_all_seven_checks_bullish() -> None:
    count, checks = bull_count(**BULLISH)
    assert count == N_CHECKS == 7
    assert checks == (True,) * 7
    assert len(CHECK_NAMES) == 7


@pytest.mark.parametrize("name", CHECK_NAMES)
def test_a_tie_counts_bearish(name: str) -> None:
    """bearCnt = 7 - bullCnt (L54): an equality is not bullish, so it is a bearish point."""
    count, checks = bull_count(**{**BULLISH, **TIES[name]})
    assert count == 6
    assert not checks[CHECK_NAMES.index(name)]


@pytest.mark.parametrize("field", list(BULLISH))
def test_na_counts_bearish(field: str) -> None:
    """Any comparison with na is false: an indicator still warming up (or a VWAP without
    volume) adds a bearish point, never a bullish one."""
    count, _ = bull_count(**{**BULLISH, field: math.nan})
    # a na close fails its three comparisons (EMA trend, open, VWAP)
    assert count == (4 if field == "close" else 6)


def test_comparisons_use_pines_tolerance() -> None:
    """Pine's > is a - b > 1e-10: a difference inside the tolerance is a tie (bearish)."""
    count, checks = bull_count(**{**BULLISH, "open_": 101.0 - 5e-11})
    assert count == 6 and not checks[CHECK_NAMES.index("close_above_open")]
    count, _ = bull_count(**{**BULLISH, "open_": 101.0 - 2e-10})
    assert count == 7


@pytest.mark.parametrize(
    ("count", "minimum", "expected"),
    [(4, 4, 1), (5, 4, 2), (6, 4, 3), (7, 4, 3), (7, 7, 1), (2, 0, 3), (0, 0, 1)],
)
def test_stars(count: int, minimum: int, expected: int) -> None:
    assert stars(count, minimum) == expected


def test_params_default_to_the_scripts_inputs() -> None:
    p = EliteAlgoParams()
    assert (p.fast_len, p.slow_len, p.trend_len) == (8, 21, 200)
    assert (p.rsi_len, p.adx_len, p.adx_smoothing, p.atr_len) == (14, 14, 14, 14)
    assert (p.pulse_fast, p.pulse_slow, p.pulse_signal) == (5, 60, 20)
    assert (p.min_confluence, p.use_trend_filter, p.cooldown_bars) == (4, True, 5)
    assert (p.sl_mult, p.rr_ratio) == (1.5, 2.0)


@pytest.mark.parametrize(
    "bad",
    [
        {"min_confluence": 8},
        {"min_confluence": -1},
        {"cooldown_bars": -1},
        {"sl_mult": 0.05},
        {"rr_ratio": 0.0},
        {"sl_mult": math.inf},
        {"fast_len": 0},
        {"unknown": 1},
    ],
)
def test_params_reject_values_the_script_does_not_allow(bad: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        EliteAlgoParams.model_validate(bad)


def test_definition_applies_the_doc13_defaults() -> None:
    definition = definition_from_class(EliteAlgoEmaConfluence)
    meta = definition.meta
    assert meta.id == "elitealgo_ema_confluence"
    assert meta.on_opposite_signal == "ignore"  # D4: script 9 ignores until flat
    assert meta.skip_entry_beyond_levels is True  # D3: priced at the close
    assert meta.warmup_bars >= 1_000
    assert meta.timeframes == ()  # any intraday timeframe; instances use 5m and 15m
