"""Model C's building blocks on hand vectors: ``f_pdBias`` (``PdBias``), the zones
(``f_htfFvg`` through the lagged view, ``f_addZone``, ``f_updateZones``), the 1m gaps,
the CISD run opens and the IFVG list (L163-168, L228-304, L358-401, L740-773)."""

import math
from datetime import UTC, datetime, timedelta

from kterminal.domain.timeframes import M5
from kterminal.strategies.ict_model_c import (
    ChartGaps,
    GapState,
    HtfFvgFeed,
    InversionGaps,
    PdBias,
    RunOpens,
    Zone,
    ZoneBook,
)
from kterminal.strategy_engine import BarSeries
from tests.unit.strategies.pine_port_support import make_bars

T = datetime(2026, 1, 6, 5, 0, tzinfo=UTC)
HOUR = timedelta(hours=1)


def feed(bias: PdBias, rows: list[tuple[float, float, float]]) -> None:
    """``(high, low, close)`` rows as consecutive 1h bars."""
    for i, (h, low, c) in enumerate(rows):
        bias.update(h, low, c, T + i * HOUR)


# ── f_pdBias ─────────────────────────────────────────────────────────────────────
def test_a_bullish_fvg_tapped_and_held_sets_a_bullish_bias() -> None:
    bias = PdBias(3)
    feed(bias, [(101, 99, 100), (104, 100, 103.5), (105, 102, 104)])  # FVG 101-102
    assert bias.bull_gaps == [(102, 101)] and bias.bias == 0
    feed(bias, [(104, 101.8, 103)])  # wick 101.8 <= 102, close 103 >= 101.5
    assert bias.bias == 1 and bias.bias_events == (1, 0)
    # a close below the bottom is a bearish event and removes the gap
    bias.update(102, 100, 100.5, T + 10 * HOUR)
    assert bias.bias == -1 and bias.bull_gaps == [] and bias.bias_events == (0, 1)


def test_holding_needs_the_close_at_or_above_the_midpoint() -> None:
    bias = PdBias(3)
    feed(bias, [(101, 99, 100), (104, 100, 103.5), (105, 102, 104)])
    bias.update(104, 101.8, 101.4, T + 3 * HOUR)  # below the 101.5 midpoint: no event
    assert bias.bias == 0
    bias.update(104, 101.8, 101.5, T + 4 * HOUR)  # exactly the midpoint: >= holds
    assert bias.bias == 1


def test_a_bearish_fvg_closed_through_is_bullish_and_mixed_bars_keep_the_bias() -> None:
    bias = PdBias(3)
    feed(bias, [(105, 103, 104), (104, 99, 100), (102, 98, 99)])  # bear FVG top 103, bot 102
    assert bias.bear_gaps == [(103, 102)]
    feed(bias, [(102.5, 99, 100)])  # wick 102.5 >= 102, close 100 <= 102.5: bearish
    assert bias.bias == -1
    bias.update(104, 99, 103.5, T + 4 * HOUR)  # close > 103: bullish event, removed
    assert bias.bias == 1 and bias.bear_gaps == []
    # one bullish and one bearish event on the same bar: the bias is unchanged
    mixed = PdBias(3)
    mixed.bull_gaps = [(102.0, 101.0)]
    mixed.bear_gaps = [(110.0, 108.0)]
    mixed.bias = -1
    mixed.update(108.5, 101.5, 103.0, T)  # taps both: bull held, bear rejected
    assert mixed.bias == -1 and mixed.bias_events == (0, 0)


def test_a_new_fvg_is_not_tested_on_its_own_bar_and_at_most_ten_are_kept() -> None:
    bias = PdBias(3)
    feed(bias, [(101, 99, 100), (104, 100, 103.5)])
    bias.update(105, 101.2, 101.3, T + 2 * HOUR)  # completes FVG 101-101.2, closes under mid
    assert bias.bull_gaps == [(101.2, 101)] and bias.bias == 0
    rows = [(10.0 * k + 1, 10.0 * k, 10.0 * k + 0.5) for k in range(30)]  # a staircase
    many = PdBias(3)
    feed(many, rows)
    assert len(many.bull_gaps) == 10 and many.bull_gaps[-1] == (290.0, 271.0)


def test_untaken_pivots_are_the_draw_on_liquidity() -> None:
    bias = PdBias(2)
    highs = [100, 101, 105, 101, 100, 103, 101, 100]
    for i, h in enumerate(highs):
        bias.update(h, h - 5, h - 2, T + i * HOUR)
    # pivots 105 (bar 2, confirmed at bar 4) and 103 (bar 5, confirmed at bar 7)
    assert [p for p, _ in bias.liq_highs] == [105, 103]
    assert bias.bsl == 103 and bias.bsl_time == T + 5 * HOUR
    bias.update(104, 99, 102, T + 8 * HOUR)  # high 104 > 103: taken
    assert bias.bsl == 105
    bias.update(105, 99, 102, T + 9 * HOUR)  # equal is not a take (strictly greater)
    assert bias.bsl == 105
    assert math.isnan(PdBias(2).bsl) and math.isnan(PdBias(2).ssl)


def test_untaken_lows_are_the_sell_side_liquidity() -> None:
    bias = PdBias(2)
    lows = [100, 99, 95, 99, 100, 97, 99, 100]
    for i, low in enumerate(lows):
        bias.update(low + 5, low, low + 2, T + i * HOUR)
    assert bias.ssl == 97 and bias.ssl_time == T + 5 * HOUR
    bias.update(101, 96, 99, T + 8 * HOUR)
    assert bias.ssl == 95


# ── f_htfFvg through the lagged view ─────────────────────────────────────────────
def test_the_htf_feed_is_fresh_once_per_new_bar_and_needs_three() -> None:
    series = BarSeries("XAUUSD", M5)
    rows = [(100, 101, 99, 100), (101, 104, 100, 103.5), (104, 105, 102, 104.5)]
    bars = make_bars(rows, start=T, timeframe="5m")
    feed_ = HtfFvgFeed()
    assert feed_.update(series.closed_by(T)) is None  # nothing visible
    series._append(bars[0])
    series._append(bars[1])
    assert feed_.update(series.closed_by(T + 10 * M5.duration)) is None  # two bars: cT na
    series._append(bars[2])
    fresh = feed_.update(series.closed_by(T + 15 * M5.duration))
    assert fresh is not None and fresh.bull and not fresh.bear
    assert (fresh.bull_top, fresh.bull_bot, fresh.start) == (102.0, 101.0, T)
    assert feed_.update(series.closed_by(T + 15 * M5.duration)) is None  # not fresh again


# ── zones ────────────────────────────────────────────────────────────────────────
def zone(direction: int, top: float, bot: float, k: int = 0) -> Zone:
    return Zone(direction, top, bot, T, T + k * HOUR, k)


def test_at_most_six_zones_bull_and_bear_together() -> None:
    book = ZoneBook()
    for k in range(8):
        book.add(zone(1 if k % 2 else -1, 100.0 + k, 99.0 + k, k))
    assert [z.added_index for z in book.zones] == [2, 3, 4, 5, 6, 7]


def test_zones_die_on_a_close_beyond_the_far_edge() -> None:
    book = ZoneBook()
    book.add(zone(1, 102, 101))
    book.add(zone(-1, 106, 105))
    book.update(1, 103, 100.5, 101.0, math.nan, math.nan)  # close == bottom: alive
    assert len(book.zones) == 2
    book.update(2, 103, 100.5, 100.99, math.nan, math.nan)  # close < bottom: dead
    assert [z.dir for z in book.zones] == [-1]
    book.update(3, 106.2, 104, 106.01, math.nan, math.nan)
    assert book.zones == []


def test_taps_extremes_and_the_cisd_snapshot() -> None:
    book = ZoneBook()
    book.add(zone(1, 102, 101))
    book.update(5, 104, 102.5, 103, 103.5, 99.0)  # not reached
    z = book.zones[0]
    assert not z.tapped and math.isnan(z.ext)
    book.update(6, 103, 102.0, 102.5, 103.4, 99.0)  # low == top: tapped
    assert (z.tapped, z.tap_bar, z.ext, z.ext_bar, z.cisd) == (True, 6, 102.0, 6, 103.4)
    book.update(7, 102.8, 101.5, 102.4, 102.9, 99.0)  # deeper: new extreme, new CISD level
    assert (z.tap_bar, z.ext, z.ext_bar, z.cisd) == (6, 101.5, 7, 102.9)
    book.update(8, 102.6, 101.5, 102.3, 102.2, 99.0)  # equal low: not a new extreme
    assert (z.ext_bar, z.cisd) == (7, 102.9)
    bear = ZoneBook()
    bear.add(zone(-1, 106, 105))
    bear.update(9, 105.2, 104, 104.5, 99.0, 104.1)
    b = bear.zones[0]
    assert (b.tapped, b.ext, b.cisd) == (True, 105.2, 104.1)


# ── 1m gaps, runs, inversions ────────────────────────────────────────────────────
def test_chart_gaps_with_a_minimum_size() -> None:
    gaps = ChartGaps(0.5)
    gaps.update(101, 100)
    gaps.update(103, 101)
    small = gaps.update(104, 101.4)  # 101.4 − 101 = 0.4 < 0.5
    assert not small.bull
    big = ChartGaps(0.0)
    big.update(101, 100)
    big.update(103, 101)
    state = big.update(104, 101.4)
    assert state.bull and state.bull_bot == 101 and not state.bear


def test_run_opens_follow_the_first_candle_of_each_run() -> None:
    runs = RunOpens()
    runs.update(0, 100, 99)  # down: first bar, no previous candle
    assert (runs.bear_run_open, runs.bear_run_bar) == (100, 0)
    runs.update(1, 99, 98)  # the run continues
    runs.update(2, 98, 99)  # up
    assert (runs.bear_run_open, runs.bull_run_open) == (100, 98)
    runs.update(3, 99, 99)  # doji: neither
    runs.update(4, 99, 98.5)  # a new down run
    assert (runs.bear_run_open, runs.bear_run_bar) == (99, 4)


def test_inversions_expire_after_c_look_and_skip_the_formation_bar() -> None:
    inv = InversionGaps(look=30)
    bear = GapState(bull=False, bull_bot=math.nan, bear=True, bear_top=105.0)
    none = GapState(bull=False, bull_bot=math.nan, bear=False, bear_top=math.nan)
    out = inv.update(10, 106.0, bear)  # formed on bar 10 (middle candle 9): not tested
    assert not out.bull and inv.bear_gaps == [(105.0, 9)]
    assert not inv.update(39, 104.0, none).bull  # 30 bars after the middle candle: alive
    out = inv.update(40, 104.0, none)  # 31 bars: expired
    assert inv.bear_gaps == [] and not out.bull
    inv.update(50, 104.0, GapState(bull=False, bull_bot=math.nan, bear=True, bear_top=103.0))
    inv.update(51, 102.0, GapState(bull=False, bull_bot=math.nan, bear=True, bear_top=102.5))
    out = inv.update(52, 103.5, none)  # closes above both tops
    assert out.bull and out.bull_bar == 50 and sorted(out.bull_levels) == [102.5, 103.0]
    assert inv.bear_gaps == []
