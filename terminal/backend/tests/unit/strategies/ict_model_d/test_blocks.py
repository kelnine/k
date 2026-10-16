"""Model D's building blocks on hand vectors: the value area (``f_valueArea``, L307-339),
the overnight session store (L835-854), the candle-estimate order flow and aggressive
flags (L627-643), the script's own trade (``manage``, L452-464) and the 15m zones
(``f_htfFvg``, ``f_addZone``, the kill rule of ``f_updateZones``, ``f_zoneTouch``)."""

import math
from datetime import UTC, datetime, timedelta

import pytest

from kterminal.domain.timeframes import M15
from kterminal.strategies.ict_model_d import (
    CandleFlow,
    HtfFvgFeed,
    OvernightProfile,
    ScriptTrade,
    Zone,
    ZoneBook,
    value_area,
)
from kterminal.strategy_engine import BarSeries
from tests.unit.strategies.pine_port_support import make_bars

T = datetime(2026, 1, 6, 15, 0, tzinfo=UTC)


# ── f_valueArea ──────────────────────────────────────────────────────────────────
def test_value_area_spreads_volume_evenly_and_grows_towards_the_larger_row() -> None:
    """Rows of 1.0 over 0-10. Bar A (0-10, volume 10) puts 1 in every row — its high on
    the top edge is clamped into row 9 — bar B (4.5-5.5, volume 4) 2 in rows 4 and 5:
    [1,1,1,1,3,3,1,1,1,1]. POC = row 4 (the first maximum); the area takes row 5, then
    the tied neighbours one at a time going up, until 70 % of 14 (9.8) is reached."""
    area = value_area([10.0, 5.5], [0.0, 4.5], [10.0, 4.0], 0.0, 10.0, 10, 70.0)
    assert (area.poc, area.val, area.vah) == (4.5, 4.0, 10.0)


def test_value_area_takes_the_lower_row_when_it_holds_more() -> None:
    # bins [1,1,1,3,3,1,…]: from row 3 the lower neighbour (1) never beats the upper (3)
    # then rows above win every tie: the area walks up until it has enough
    area = value_area([10.0, 4.5], [0.0, 3.5], [10.0, 4.0], 0.0, 10.0, 10, 50.0)
    assert (area.poc, area.val, area.vah) == (3.5, 3.0, 6.0)
    # a heavier row below the POC is taken before a lighter one above
    area = value_area([10.0, 3.5, 4.5], [0.0, 2.5, 4.5], [10.0, 2.0, 3.0], 0.0, 10.0, 10, 40.0)
    # bins: row 2 +1, row 3 +1, row 4 +3 → [1,1,2,2,4,1,1,1,1,1]; POC 4, then 3 (2 > 1)
    assert (area.poc, area.val, area.vah) == (4.5, 3.0, 5.0)


def test_value_area_stops_at_the_edges_and_exactly_at_the_percentage() -> None:
    top_heavy = value_area([10.0, 10.0], [0.0, 9.5], [10.0, 10.0], 0.0, 10.0, 10, 70.0)
    # POC is the top row: up is exhausted (−1), the area grows downwards only
    assert (top_heavy.poc, top_heavy.vah, top_heavy.val) == (9.5, 10.0, 6.0)
    # 50 % of [5,5] is reached by the POC row alone: no expansion
    two = value_area([0.5, 1.5], [0.0, 1.0], [5.0, 5.0], 0.0, 2.0, 2, 50.0)
    assert (two.poc, two.val, two.vah) == (0.5, 0.0, 1.0)


def test_value_area_is_na_without_range_or_volume() -> None:
    for area in (
        value_area([], [], [], 0.0, 1.0, 10, 70.0),
        value_area([1.0], [1.0], [10.0], 1.0, 1.0, 10, 70.0),
        value_area([1.0], [0.0], [0.0], 0.0, 1.0, 10, 70.0),
        value_area([1.0], [0.0], [1.0], math.nan, 1.0, 10, 70.0),
    ):
        assert math.isnan(area.vah) and math.isnan(area.val) and math.isnan(area.poc)


# ── the overnight store ──────────────────────────────────────────────────────────
def test_the_overnight_store_restarts_extends_and_computes_after_the_session() -> None:
    profile = OvernightProfile(rows=10, va_pct=70.0)
    flags = {"inside": True, "started": True, "ended": False}
    assert not profile.update(10.0, 0.0, 10.0, **flags)
    assert not profile.update(5.5, 4.5, 4.0, inside=True, started=False, ended=False)
    assert (profile.high, profile.low, profile.bars) == (10.0, 0.0, 2)
    assert math.isnan(profile.vah)  # not computed while the session runs
    assert profile.update(99.0, 98.0, 1e6, inside=False, started=False, ended=True)
    assert (profile.poc, profile.val, profile.vah) == (4.5, 4.0, 10.0)
    assert (profile.levels_high, profile.levels_low, profile.session_bars) == (10.0, 0.0, 2)
    # outside, nothing changes; the next session clears the stored bars
    assert not profile.update(50.0, 49.0, 1.0, inside=False, started=False, ended=False)
    profile.update(20.0, 19.0, 1.0, **flags)
    assert (profile.high, profile.low, profile.bars, profile.vah) == (20.0, 19.0, 1, 10.0)


def test_a_session_joined_midway_has_no_levels() -> None:
    """``onHi`` starts na and ``math.max(na, high)`` is na: a session whose first bar was
    not a start yields no levels. (The strategy's first bar inside the session is a
    start, as Pine's ``inON[1]`` is false on the first bar.)"""
    profile = OvernightProfile(rows=10, va_pct=70.0)
    profile.update(10.0, 0.0, 10.0, inside=True, started=False, ended=False)
    profile.update(0.0, 0.0, 0.0, inside=False, started=False, ended=True)
    assert math.isnan(profile.vah) and math.isnan(profile.levels_high)


# ── candle-estimate order flow ───────────────────────────────────────────────────
def test_candle_estimate_splits_volume_by_the_close_location() -> None:
    flow = CandleFlow(vol_mult=1.5, delta_pct=30.0)
    first = flow.update(high=11.0, low=10.0, close=10.8, volume=100.0)
    assert (first.buy, first.sell) == pytest.approx((80.0, 20.0))
    assert first.delta == pytest.approx(60.0) and first.delta_pct == pytest.approx(60.0)
    assert math.isnan(first.avg_volume) and not first.aggr_buy  # avgVol na for 19 bars
    doji = CandleFlow(1.5, 30.0).update(high=10.0, low=10.0, close=10.0, volume=50.0)
    assert (doji.buy, doji.sell, doji.delta) == (25.0, 25.0, 0.0)
    no_volume = CandleFlow(1.5, 30.0).update(11.0, 10.0, 10.9, math.nan)
    assert (no_volume.volume, no_volume.delta) == (0.0, 0.0)
    assert math.isnan(no_volume.delta_pct)


def test_aggressive_bars_need_volume_against_the_average_including_themselves() -> None:
    flow = CandleFlow(vol_mult=1.5, delta_pct=30.0)
    for _ in range(19):
        flow.update(11.0, 10.0, 10.5, 100.0)
    # avg = (19 × 100 + v) / 20, so v >= 1.5 × avg ⇔ v >= 2850 / 18.5 = 154.05…
    loud = flow.update(11.0, 10.0, 10.9, 155.0)
    assert loud.aggr_buy and not loud.aggr_sell
    assert loud.avg_volume == pytest.approx((18 * 100 + 100 + 155) / 20)
    quiet = CandleFlow(1.5, 30.0)
    for _ in range(19):
        quiet.update(11.0, 10.0, 10.5, 100.0)
    assert not quiet.update(11.0, 10.0, 10.9, 154.0).aggr_buy
    # the delta threshold: 30 % of the volume, inclusive
    edge = CandleFlow(1.5, 30.0)
    for _ in range(19):
        edge.update(11.0, 10.0, 10.5, 100.0)
    at_edge = edge.update(11.0, 10.0, 10.35, 400.0)  # delta −0.3 × 400
    assert at_edge.aggr_sell and not at_edge.aggr_buy


# ── the script's trade ───────────────────────────────────────────────────────────
def test_the_script_trade_checks_the_stop_first_from_the_next_bar() -> None:
    trade = ScriptTrade()
    trade.open(1, 100.0, 99.0, 102.0, index=5)
    assert trade.manage(5, 103.0, 98.0) == 0 and trade.live  # the signal bar: no check
    assert trade.manage(6, 103.0, 98.5) == -1 and not trade.live  # both touched: stop
    assert trade.result == -1
    trade.open(-1, 100.0, 101.0, 98.0, index=10)
    assert trade.manage(11, 100.9, 98.0) == 1 and trade.result == 1
    trade.open(1, 100.0, 99.0, 102.0, index=20)
    trade.close(0)
    assert (trade.live, trade.result) == (False, 0)
    assert trade.manage(21, 103.0, 98.0) == 0


# ── 15m zones ────────────────────────────────────────────────────────────────────
def zone(direction: int, top: float, bot: float, k: int = 0) -> Zone:
    return Zone(direction, top, bot, T, T + timedelta(minutes=k))


def test_at_most_six_zones_and_a_close_through_kills_one() -> None:
    book = ZoneBook()
    for k in range(8):
        book.add(zone(1 if k % 2 else -1, 100.0 + k, 99.0 + k, k))
    assert [z.added for z in book.zones] == [T + timedelta(minutes=k) for k in range(2, 8)]
    book = ZoneBook()
    book.add(zone(1, 102, 101))
    book.add(zone(-1, 106, 105))
    book.update(101.0)  # close == bottom: alive
    assert len(book.zones) == 2
    book.update(100.99)
    assert [z.dir for z in book.zones] == [-1]
    book.update(106.01)
    assert book.zones == []


def test_support_is_a_bullish_zone_the_bar_overlaps_and_resistance_a_bearish_one() -> None:
    book = ZoneBook()
    bull, bear = zone(1, 102, 101), zone(-1, 106, 105)
    book.add(bull)
    book.add(bear)
    assert book.touch(103.0, 102.0) == ([bull], [])  # low == top: overlaps
    assert book.touch(103.0, 102.01) == ([], [])
    assert book.touch(105.0, 104.0) == ([], [bear])  # high == bottom
    assert book.touch(107.0, 100.0) == ([bull], [bear])


def test_the_15m_feed_is_fresh_once_per_new_bar() -> None:
    series = BarSeries("XAUUSD", M15)
    rows = [(100, 101, 99, 100), (101, 104, 100, 103.5), (104, 105, 102, 104.5)]
    bars = make_bars(rows, start=T, timeframe="15m")
    feed = HtfFvgFeed()
    for bar in bars[:2]:
        series._append(bar)
    assert feed.update(series.closed_by(T + 30 * timedelta(minutes=1))) is None
    series._append(bars[2])
    fresh = feed.update(series.closed_by(T + timedelta(minutes=45)))
    assert fresh is not None and fresh.bull and not fresh.bear
    assert (fresh.bull_top, fresh.bull_bot, fresh.start) == (102.0, 101.0, T)
    assert feed.update(series.closed_by(T + timedelta(minutes=46))) is None
