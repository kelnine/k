"""The shared fill rules (``kterminal.strategy_engine.fills``): mid prices and venue prices."""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from kterminal.core.enums import Direction, OrderSide, OrderType, SignalAction
from kterminal.domain.costs import Liquidity
from kterminal.domain.market import Bar
from kterminal.domain.signals import Signal
from kterminal.strategy_engine.fills import (
    BracketKind,
    Fill,
    MidPrices,
    PriceModel,
    VenuePrices,
    bracket_exit,
    levels_on_grid,
    levels_problem,
    resting_entry_fill,
)
from tests.fixtures.catalog import lab_catalog

T = datetime(2026, 1, 5, 14, 0, tzinfo=UTC)
MID = MidPrices()


def venue() -> VenuePrices:
    """XAUUSD on the lab profile: spread 0.20 (half 0.10), slippage 3 ticks, tick 0.01."""
    catalog = lab_catalog()
    listing = catalog.execution_listing("lab_default", "XAUUSD")
    return VenuePrices(catalog.cost_calculator(listing), listing)


def bar(o: str, h: str, low: str, c: str) -> Bar:
    return Bar.of("XAUUSD", "1m", T, o, h, low, c)


D = Decimal


def hit(
    prices: PriceModel,
    stop: str,
    target: str | None,
    b: Bar,
    *,
    direction: Direction = Direction.LONG,
    after_intrabar_fill: bool = False,
) -> tuple[BracketKind, Fill]:
    result = bracket_exit(
        prices,
        direction,
        D(stop),
        None if target is None else D(target),
        b,
        after_intrabar_fill=after_intrabar_fill,
    )
    assert result is not None
    return result


def test_mid_prices_trade_at_the_bar_without_costs() -> None:
    b = bar("100", "105", "95", "101")
    assert MID.market(OrderSide.BUY, D(100), T) == Fill(D(100))
    assert MID.opening(OrderSide.SELL, b) == D(100)
    assert MID.round_level(D("100.123"), is_buy=True) == D("100.123")
    assert MID.stop_triggered(OrderSide.SELL, D(95), b)
    assert not MID.stop_triggered(OrderSide.SELL, D("94.99"), b)
    assert MID.stop_fill(OrderSide.SELL, D(96), b) == Fill(D(96), intrabar=True)
    gap = bar("90", "92", "89", "91")
    assert MID.stop_fill(OrderSide.SELL, D(95), gap) == Fill(D(90))  # gapped: the open


def test_venue_market_fill_crosses_half_the_spread_plus_slippage_rounded_against() -> None:
    prices = venue()
    buy = prices.market(OrderSide.BUY, D("4000.00"), T)
    assert buy == Fill(D("4000.13"), D("0.10"), D("0.03"))
    sell = prices.market(OrderSide.SELL, D("4000.005"), T)
    assert sell.price == D("3999.87")  # 3999.875 rounded down: never a better price


def test_a_target_the_mid_touches_by_less_than_half_the_spread_does_not_fill() -> None:
    prices = venue()
    b = bar("4000.00", "4010.05", "3999.00", "4009.00")
    # mid touches the long's 4010.00 target, the bid (high - 0.10 = 4009.95) does not
    assert bracket_exit(MID, Direction.LONG, D(3990), D(4010), b) == (
        "TAKE_PROFIT",
        Fill(D(4010), liquidity=Liquidity.MAKER),
    )
    assert bracket_exit(prices, Direction.LONG, D(3990), D(4010), b) is None


def test_a_stop_triggers_when_the_bid_reaches_it_and_fills_there_minus_slippage() -> None:
    prices = venue()
    b = bar("4000.00", "4001.00", "3990.05", "3995.00")  # bid low 3989.95
    assert bracket_exit(MID, Direction.LONG, D(3990), None, b) is None
    kind, fill = hit(prices, "3990", None, b)
    assert kind == "STOP_LOSS"
    assert fill.price == D("3989.97") and fill.intrabar


def test_a_gap_through_the_stop_fills_at_the_opening_bid() -> None:
    prices = venue()
    gap = bar("3980.00", "3982.00", "3978.00", "3981.00")
    kind, fill = hit(prices, "3990", None, gap)
    assert kind == "STOP_LOSS"
    assert fill.price == D("3979.87") and not fill.intrabar  # 3980 - 0.10 - 0.03


def test_both_hit_assumes_the_stop_unless_the_bar_opens_beyond_the_target() -> None:
    prices = venue()
    both = bar("4000.00", "4020.00", "3980.00", "4000.00")
    assert hit(prices, "3990", "4010", both)[0] == "STOP_LOSS"
    short_kind, short_fill = hit(prices, "4010", "3990", both, direction=Direction.SHORT)
    assert short_kind == "STOP_LOSS" and short_fill.price == D("4010.03")  # ask hit the stop
    beyond = bar("4015.00", "4016.00", "3980.00", "3990.00")
    kind, fill = hit(prices, "3990", "4010", beyond)
    assert kind == "TAKE_PROFIT" and fill.price == D("4014.90")  # the opening bid


def test_after_an_intrabar_fill_the_target_needs_the_close() -> None:
    prices = venue()
    b = bar("4000.00", "4020.00", "3999.00", "4005.00")
    assert hit(prices, "3990", "4010", b)[0] == "TAKE_PROFIT"
    assert (
        bracket_exit(prices, Direction.LONG, D(3990), D(4010), b, after_intrabar_fill=True) is None
    )
    closed_beyond = bar("4000.00", "4020.00", "3999.00", "4015.00")
    assert hit(prices, "3990", "4010", closed_beyond, after_intrabar_fill=True)[0] == "TAKE_PROFIT"


def test_resting_entries_fill_on_the_far_side_of_the_spread() -> None:
    prices = venue()
    b = bar("4000.00", "4001.00", "3995.05", "3999.00")  # ask low 3995.15
    assert resting_entry_fill(MID, OrderType.LIMIT, OrderSide.BUY, D("3995.10"), b) == Fill(
        D("3995.10"), liquidity=Liquidity.MAKER, intrabar=True
    )
    assert resting_entry_fill(prices, OrderType.LIMIT, OrderSide.BUY, D("3995.10"), b) is None
    assert resting_entry_fill(prices, OrderType.LIMIT, OrderSide.BUY, D("3995.20"), b) == Fill(
        D("3995.20"), liquidity=Liquidity.MAKER, intrabar=True
    )
    through = bar("3990.00", "3991.00", "3989.00", "3990.00")  # opens through: the open ask
    assert resting_entry_fill(prices, OrderType.LIMIT, OrderSide.BUY, D(3995), through) == Fill(
        D("3990.10")
    )
    stop = resting_entry_fill(prices, OrderType.STOP, OrderSide.BUY, D("4000.95"), b)
    assert stop is not None and stop.price == D("4000.98") and stop.intrabar  # ask hit it
    with pytest.raises(ValueError, match="resting"):
        resting_entry_fill(prices, OrderType.MARKET, OrderSide.BUY, D(1), b)


def test_levels_go_on_the_grid_against_the_trader() -> None:
    catalog = lab_catalog()
    listing = catalog.execution_listing("lab_default", "XAUUSD")
    coarse = VenuePrices(catalog.cost_calculator(listing), replace(listing, tick_size=D("0.10")))
    signal = Signal(
        strategy_id="s",
        strategy_version="v",
        symbol="XAUUSD",
        timeframe="1m",
        timestamp=T,
        signal=SignalAction.LONG,
        entry=D("3990.05"),
        stop_loss=D("3985.05"),
        take_profit=D("4010.05"),
        order_type=OrderType.LIMIT,
    )
    grid = levels_on_grid(coarse, signal)
    assert (grid.entry, grid.stop_loss, grid.take_profit) == (D("3990.1"), D("3985.0"), D("4010.0"))
    assert levels_on_grid(MID, signal) is signal
    assert levels_problem(Direction.LONG, D(100), D(100), None) is not None
    assert levels_problem(Direction.SHORT, D(100), D(101), D(100)) is not None
    assert levels_problem(Direction.SHORT, D(100), D(101), D(99)) is None
