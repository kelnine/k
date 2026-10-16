"""The building blocks of script 2's A/B engine: the shared 1m series (displacement FVGs,
MSS pivots), ``SweepModel.run``'s start/cancel rules, Model A's untaken 15m swings and
Model B's 08:00 range."""

import math
from datetime import UTC, datetime, timedelta

import pytest

from kterminal.strategies.ict_sweep_models import (
    ARMED,
    IDLE,
    WAIT_MSS,
    WAIT_SWEEP,
    BarState,
    EngineConfig,
    LiquiditySwings,
    RangeCandle,
    SharedSeries,
    SweepModel,
)
from kterminal.strategies.ict_sweep_models.engine import PIVOT_CAP
from kterminal.strategies.ict_sweep_models.levels import LIQUIDITY_CAP

T = datetime(2026, 1, 6, tzinfo=UTC)
CONFIG = EngineConfig(
    need_back=False,
    target_mode="Opposite level",
    rr=2.0,
    min_rr=1.0,
    entry_mode="FVG edge",
    sl_buf=0.0,
)


def feed(series: SharedSeries, rows: list[tuple[float, float, float, float]]) -> list[BarState]:
    return [series.update(i, *row) for i, row in enumerate(rows)]


# ── shared series ─────────────────────────────────────────────────────────────────
def test_displacement_fvg_needs_a_gap_a_same_colour_middle_candle_and_a_large_body() -> None:
    quiet = [(100.0, 100.2, 99.8, 100.1), (100.1, 100.2, 99.8, 100.0)] * 15  # bodies 0.1
    gap = [
        (100.0, 100.1, 99.9, 100.05),
        (100.05, 100.9, 100.0, 100.8),
        (100.8, 100.9, 100.3, 100.6),
    ]
    states = feed(SharedSeries(2, 1.5, 0.0), quiet + gap)
    last = states[-1]
    assert last.bull_disp and not last.bear_disp
    assert (last.bull_top, last.bull_bot) == (100.3, 100.1)  # low, high[2]
    # avgBody[1]: 18 quiet bodies of 0.1, then 0.05 and the middle candle's 0.75
    assert last.body_1 == pytest.approx(0.75) and last.avg_body_1 == pytest.approx(0.13)
    # a middle candle with a smaller body (0.12 < 1.5 × its 0.0985 average) is none;
    # the average includes the middle candle itself (avgBody[1])
    weak = [gap[0], (100.05, 100.35, 100.0, 100.17), (100.2, 100.4, 100.3, 100.35)]
    assert not feed(SharedSeries(2, 1.5, 0.0), quiet + weak)[-1].bull_disp
    # a bearish middle candle is no bullish displacement
    red = [gap[0], (100.8, 100.9, 100.0, 100.05), (100.8, 100.9, 100.3, 100.6)]
    assert not feed(SharedSeries(2, 1.5, 0.0), quiet + red)[-1].bull_disp


def test_min_fvg_size_in_ticks() -> None:
    quiet = [(100.0, 100.2, 99.8, 100.1), (100.1, 100.2, 99.8, 100.0)] * 15
    gap = [
        (100.0, 100.1, 99.9, 100.05),
        (100.05, 100.9, 100.0, 100.8),
        (100.8, 100.9, 100.3, 100.6),
    ]
    assert feed(SharedSeries(2, 1.5, 0.2), quiet + gap)[-1].bull_disp  # gap 0.2 >= 0.2
    assert not feed(SharedSeries(2, 1.5, 0.21), quiet + gap)[-1].bull_disp


def test_displacement_during_warm_up_compares_with_zero() -> None:
    """``nz(avgBody[1])`` is 0 until 20 bars have been seen (spec, parity risks)."""
    rows = [
        (100.0, 100.1, 99.9, 100.0),
        (100.0, 100.11, 99.99, 100.01),
        (100.2, 100.3, 100.15, 100.2),
    ]
    last = feed(SharedSeries(2, 1.5, 0.0), rows)[-1]
    assert last.bull_disp and last.avg_body_1 == 0.0


def test_mss_pivots_are_stored_at_their_pivot_bar_and_capped() -> None:
    series = SharedSeries(2, 1.5, 0.0)
    rows = [(100.0, 100.0 + (i % 5 == 2), 99.0 - (i % 5 == 4), 100.0) for i in range(600)]
    feed(series, rows)
    assert len(series.pivot_highs) == PIVOT_CAP and len(series.pivot_lows) == PIVOT_CAP
    assert series.pivot_highs[-1] == (101.0, 597)  # the newest, confirmed two bars later
    assert series.pivot_before(highs=True, before=597) == (101.0, 592)  # strictly before
    assert series.pivot_before(highs=False, before=10_000) == (98.0, 594)
    assert series.pivot_before(highs=True, before=0) == (math.nan, None) or math.isnan(
        series.pivot_before(highs=True, before=0)[0]
    )


# ── SweepModel.run: start and window rules ────────────────────────────────────────
def bar_state(index: int, o: float, h: float, low: float, c: float) -> BarState:
    return BarState(index, o, h, low, c, False, False, low, math.nan, math.nan, h, 0.0, 0.0)


def test_window_start_with_missing_or_crossed_levels_idles() -> None:
    model, series = SweepModel("A"), SharedSeries(2, 1.5, 0.0)
    quiet = bar_state(0, 100.0, 100.1, 99.9, 100.0)
    for hi, lo in ((math.nan, 99.0), (101.0, math.nan), (99.0, 99.0), (99.0, 101.0)):
        step = model.run(quiet, series, CONFIG, active=True, start_now=True, new_hi=hi, new_lo=lo)
        assert step.started and model.state == IDLE
    model.run(quiet, series, CONFIG, active=True, start_now=True, new_hi=101.0, new_lo=99.0)
    assert model.state == WAIT_SWEEP


def test_leaving_the_window_drops_any_unfilled_stage() -> None:
    series = SharedSeries(2, 1.5, 0.0)
    for state in (WAIT_SWEEP, WAIT_MSS, ARMED):
        model = SweepModel("B")
        model.state = state
        step = model.run(
            bar_state(5, 100.0, 100.1, 99.9, 100.0),
            series,
            CONFIG,
            active=False,
            start_now=False,
            new_hi=math.nan,
            new_lo=math.nan,
        )
        assert step.window_cancelled == state and model.state == IDLE


def test_an_armed_limit_fills_before_the_missed_check_on_the_same_bar() -> None:
    model = SweepModel("A")
    model.state, model.dir, model.entry, model.sl, model.tp = ARMED, 1, 99.6, 98.5, 101.0
    both = bar_state(9, 100.0, 101.2, 99.5, 100.9)  # touches the limit and the target
    step = model.run(
        both, SharedSeries(2, 1.5, 0.0), CONFIG, active=True, start_now=False, new_hi=0, new_lo=0
    )
    assert step.filled and not step.missed and step.ev == 2 and step.fill_price == 99.6


# ── levels ────────────────────────────────────────────────────────────────────────
def swing_bars(highs: list[float]) -> LiquiditySwings:
    swings = LiquiditySwings(2)
    for i, high in enumerate(highs):
        swings.update(high, high - 1.0, T + i * timedelta(minutes=15))
    return swings


def test_liquidity_swings_keep_the_most_recent_untaken_level() -> None:
    swings = swing_bars([100, 100, 105, 100, 100, 103, 100, 100])
    assert swings.last_high == 103.0  # the newer of the two surviving swing highs
    assert swings.last_high_time == T + 5 * timedelta(minutes=15)
    swings.update(104.0, 103.0, T + 8 * timedelta(minutes=15))  # takes 103 (104 > 103)
    assert swings.last_high == 105.0
    swings.update(105.0, 104.0, T + 9 * timedelta(minutes=15))  # equal: not taken
    assert swings.last_high == 105.0
    swings.update(105.5, 104.0, T + 10 * timedelta(minutes=15))
    assert math.isnan(swings.last_high) and swings.last_high_time is None


def test_liquidity_swings_cap_at_50_levels() -> None:
    """A staircase of ever lower swing highs, none ever taken: the oldest are dropped."""
    highs = [h for k in range(200) for h in (995.0 - k, 1000.0 - k, 995.0 - k)]
    swings = swing_bars(highs)
    assert len(swings.highs) == LIQUIDITY_CAP
    assert [level for level, _ in swings.highs] == [1000.0 - k for k in range(149, 199)]


def test_range_candle_accumulates_and_ages_out_after_24_hours() -> None:
    candle = RangeCandle()
    assert not candle.fresh(T)
    candle.update(101.0, 99.5, T, first=True)
    candle.update(101.5, 99.0, T + timedelta(minutes=1), first=False)
    assert (candle.high, candle.low, candle.bars) == (101.5, 99.0, 2)
    assert candle.fresh(T + timedelta(hours=23, minutes=59))
    assert not candle.fresh(T + timedelta(hours=24))  # time - bT0 < 86400000
    candle.update(100.0, 99.9, T + timedelta(days=1), first=True)
    assert (candle.high, candle.low, candle.start) == (100.0, 99.9, T + timedelta(days=1))
