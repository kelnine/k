"""Script 5's order-block and fair-value-gap rules (L283-370, L594-623), unit by unit."""

import math

import pytest

from kterminal.strategies.smc_sniper import Zone, ZoneList
from kterminal.strategies.smc_sniper.zones import fair_value_gap, order_block


def test_a_bullish_block_is_the_body_of_a_bearish_pivot_low_candle() -> None:
    assert order_block(109.0, 105.0, bullish=True, bar_index=7) == Zone("OB", 109.0, 105.0, 7)
    assert order_block(105.0, 109.0, bullish=True, bar_index=7) is None  # bullish candle
    assert order_block(105.0, 105.0, bullish=True, bar_index=7) is None  # doji: not open > close


def test_a_bearish_block_is_the_body_of_a_bullish_pivot_high_candle() -> None:
    assert order_block(105.0, 109.0, bullish=False, bar_index=3) == Zone("OB", 109.0, 105.0, 3)
    assert order_block(109.0, 105.0, bullish=False, bar_index=3) is None


def test_fair_value_gaps_are_strict_three_bar_gaps_without_a_minimum() -> None:
    bull, bear = fair_value_gap(100.0, 99.0, 102.0, 100.01, bar_index=10)
    assert bull == Zone("FVG", 100.01, 100.0, 8)  # top = low, bottom = high[2]
    assert bear is None
    assert fair_value_gap(100.0, 99.0, 102.0, 100.0, bar_index=10) == (None, None)  # touching
    bull, bear = fair_value_gap(103.0, 101.0, 100.5, 99.0, bar_index=4)
    assert bull is None
    assert bear == Zone("FVG", 101.0, 100.5, 2)  # top = low[2], bottom = high
    assert fair_value_gap(math.nan, math.nan, 102.0, 101.0, bar_index=1) == (None, None)


def test_lists_shift_out_the_oldest_at_the_cap() -> None:
    zones = ZoneList(3, bullish=True)
    for i in range(5):
        zones.push(Zone("FVG", 10.0 + i, 9.0 + i, i))
    assert [z.bar_index for z in zones.zones] == [2, 3, 4]
    with pytest.raises(ValueError, match="cap"):
        ZoneList(0, bullish=True)


def test_a_bullish_zone_dies_on_a_close_below_its_bottom_by_more_than_005_atr() -> None:
    zones = ZoneList(4, bullish=True)
    zones.push(Zone("OB", 109.0, 105.0, 1))
    assert zones.invalidate(104.95, 1.0) == []  # 105 − 0.05: on the line, kept
    assert zones.invalidate(104.0, math.nan) == []  # ATR na: nothing is deleted
    assert len(zones.zones) == 1
    assert zones.invalidate(104.94, 1.0) == [Zone("OB", 109.0, 105.0, 1)]
    assert zones.zones == []


def test_a_bearish_zone_dies_on_a_close_above_its_top_by_more_than_005_atr() -> None:
    zones = ZoneList(4, bullish=False)
    zones.push(Zone("FVG", 101.0, 100.0, 1))
    zones.push(Zone("FVG", 103.0, 102.0, 2))
    assert zones.invalidate(101.1, 2.0) == []  # 101 + 0.1: kept
    gone = zones.invalidate(101.2, 2.0)
    assert gone == [Zone("FVG", 101.0, 100.0, 1)]
    assert [z.bar_index for z in zones.zones] == [2]


def test_a_partial_fill_does_not_delete_a_gap() -> None:
    zones = ZoneList(4, bullish=True)
    zones.push(Zone("FVG", 102.0, 100.0, 1))
    assert zones.invalidate(100.5, 1.0) == []  # inside the gap
    assert zones.invalidate(100.0, 1.0) == []  # at its bottom


def test_containment_is_inclusive() -> None:
    zone = Zone("OB", 109.0, 105.0, 1)
    assert zone.contains(105.0) and zone.contains(109.0) and zone.contains(107.0)
    assert not zone.contains(104.99) and not zone.contains(109.01)
    assert zone.contains(109.0 + 5e-11)  # Pine's 1e-10 tolerance
    zones = ZoneList(3, bullish=True)
    zones.push(zone)
    zones.push(Zone("FVG", 108.0, 107.5, 2))
    assert [z.bar_index for z in zones.containing(107.8)] == [1, 2]
    assert zones.containing(110.0) == []
