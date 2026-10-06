import decimal
from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
import yaml
from hypothesis import assume, given
from hypothesis import strategies as st

from kterminal.core.enums import Direction, OrderSide
from kterminal.core.errors import ClockError
from kterminal.domain.costs import (
    MONEY_QUANTUM,
    AnnualRateSwap,
    CommissionModel,
    ConstantFunding,
    CostCalculator,
    CostConfigError,
    CostEvent,
    CostEventKind,
    CostProfile,
    FixedSpread,
    FixedTicksSlippage,
    FixedTicksSpread,
    FundingModel,
    Liquidity,
    NoCommission,
    NoFunding,
    NoSlippage,
    NoSpread,
    NoSwap,
    NotionalBpsSlippage,
    NotionalCommission,
    PerQuantityCommission,
    PointsSwap,
    QuoteSpread,
    SessionSpread,
    SlippageModel,
    SpreadModel,
    SwapModel,
    cost_profiles_document,
    parse_cost_profiles,
    profile_listing_problems,
)
from kterminal.domain.instruments import ContractType, Listing, QuantityUnit
from kterminal.domain.market import Quote

COSTS_YAML = Path(__file__).resolve().parents[4] / "config" / "catalog" / "costs.yaml"
NEW_YORK = ZoneInfo("America/New_York")
T0 = datetime(2026, 10, 5, 14, 30, tzinfo=UTC)  # Monday
D = Decimal
BUY, SELL = OrderSide.BUY, OrderSide.SELL
LONG, SHORT = Direction.LONG, Direction.SHORT


def make_listing(
    instrument: str,
    tick: str,
    contract_size: str,
    *,
    quote_currency: str = "USD",
    contract_type: ContractType = ContractType.CFD,
    unit: QuantityUnit = QuantityUnit.LOTS,
    step: str = "0.01",
) -> Listing:
    return Listing(
        venue="test_venue",
        instrument=instrument,
        venue_symbol=instrument,
        contract_type=contract_type,
        tick_size=D(tick),
        contract_size=D(contract_size),
        quantity_unit=unit,
        min_qty=D(step),
        qty_step=D(step),
        quote_currency=quote_currency,
    )


GOLD = make_listing("XAUUSD", "0.01", "100")
EURUSD = make_listing("EURUSD", "0.00001", "100000")
NAS100 = make_listing("NAS100", "0.01", "1")
MNQ = make_listing(
    "MNQ", "0.25", "2", contract_type=ContractType.FUTURE, unit=QuantityUnit.CONTRACTS, step="1"
)
NEAR = make_listing(
    "NEARUSD",
    "0.001",
    "1",
    quote_currency="USDT",
    contract_type=ContractType.PERPETUAL,
    unit=QuantityUnit.BASE_UNITS,
    step="1",
)


def make_profile(
    *,
    spread: SpreadModel | None = None,
    commission: CommissionModel | None = None,
    slippage: SlippageModel | None = None,
    funding: FundingModel | None = None,
    swap: SwapModel | None = None,
) -> CostProfile:
    return CostProfile(
        id="test_profile",
        description="test",
        spread=spread or NoSpread(),
        commission=commission or NoCommission(),
        slippage=slippage or NoSlippage(),
        funding=funding or NoFunding(),
        swap=swap or NoSwap(),
    )


def calc(listing: Listing = GOLD, **components: Any) -> CostCalculator:
    return CostCalculator(make_profile(**components), listing)


def ny(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=NEW_YORK)


def utc(year: int, month: int, day: int, hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=UTC)


def gold_points_swap(triple: int = 2) -> PointsSwap:
    return PointsSwap(D("-0.65"), D("0.10"), time(17), "America/New_York", triple)


def fx_points_swap(triple: int = 2) -> PointsSwap:
    return PointsSwap(D("-0.00008"), D("0.00002"), time(17), "America/New_York", triple)


# ── market fills ─────────────────────────────────────────────────────────────
def test_market_fill_crosses_half_spread_and_pays_slippage() -> None:
    c = calc(spread=FixedSpread(D("0.20")), slippage=FixedTicksSlippage(2))
    assert c.market_fill_price(BUY, D("2650.00"), T0) == D("2650.12")
    assert c.market_fill_price(SELL, D("2650.00"), T0) == D("2649.88")
    fill = c.market_fill(BUY, D("2650.00"), T0)
    assert (fill.reference, fill.half_spread, fill.slippage, fill.rounding) == (
        D("2650.00"),
        D("0.10"),
        D("0.02"),
        D(0),
    )
    assert fill.adverse == D("0.12")


@pytest.mark.parametrize(
    "components",
    [
        {},
        {"spread": FixedSpread(D("0.20"))},
        {"spread": FixedSpread(D("0.37")), "slippage": FixedTicksSlippage(3)},
        {"spread": FixedTicksSpread(5), "slippage": NotionalBpsSlippage(D("1.5"))},
        {"spread": QuoteSpread(D("0.30"))},
    ],
)
@pytest.mark.parametrize("mid", ["2650.00", "2650.005", "1999.999", "0.75"])
def test_buys_always_fill_at_or_above_sells_for_the_same_mid(
    components: dict[str, Any], mid: str
) -> None:
    c = calc(**components)
    buy = c.market_fill_price(BUY, D(mid), T0)
    sell = c.market_fill_price(SELL, D(mid), T0)
    assert buy >= D(mid) >= sell
    assert buy - sell >= c.spread(T0)


def test_fills_round_adversely_to_the_listing_tick() -> None:
    c = calc(spread=FixedSpread(D("0.20")))
    buy = c.market_fill(BUY, D("2650.005"), T0)  # raw 2650.105
    sell = c.market_fill(SELL, D("2650.005"), T0)  # raw 2649.905
    assert buy.price == D("2650.11")
    assert sell.price == D("2649.90")
    assert buy.rounding == sell.rounding == D("0.005")
    assert str(buy.price) == "2650.11"  # carries the tick's exponent


def test_zero_cost_fills_at_the_mid_when_on_the_grid() -> None:
    c = CostCalculator(CostProfile.zero(), GOLD)
    assert c.market_fill_price(BUY, D("2650.00"), T0) == D("2650.00")
    assert c.market_fill_price(SELL, D("2650.00"), T0) == D("2650.00")
    assert c.commission(D(1), D("2650")) == D(0)


def test_fixed_ticks_spread_and_slippage_use_the_listing_tick() -> None:
    c = calc(MNQ, spread=FixedTicksSpread(1), slippage=FixedTicksSlippage(1))
    assert c.spread(T0) == D("0.25")
    assert c.slippage(D("20000"), T0) == D("0.25")
    # 20000 + 0.125 + 0.25 = 20000.375 → up to 20000.50; sells mirror it.
    assert c.market_fill_price(BUY, D("20000.00"), T0) == D("20000.50")
    assert c.market_fill_price(SELL, D("20000.00"), T0) == D("19999.50")


def test_notional_bps_slippage_scales_with_price() -> None:
    c = calc(NEAR, spread=FixedTicksSpread(1), slippage=NotionalBpsSlippage(D("2")))
    assert c.slippage(D("2.500"), T0) == D("0.0005")
    assert c.market_fill_price(BUY, D("2.500"), T0) == D("2.501")
    assert c.market_fill_price(SELL, D("2.500"), T0) == D("2.499")


def test_quote_spread_fills_at_ask_and_bid_plus_slippage() -> None:
    c = calc(spread=QuoteSpread(D("0.20")), slippage=FixedTicksSlippage(1))
    quote = Quote("XAUUSD", T0, bid=D("2650.00"), ask=D("2650.40"))
    assert c.spread(T0, quote) == D("0.40")
    # The quote decides; the mid argument is not used.
    assert c.market_fill_price(BUY, D("9999"), T0, quote) == D("2650.41")
    assert c.market_fill_price(SELL, D("9999"), T0, quote) == D("2649.99")
    # Without a quote the fallback spread applies around the given mid.
    assert c.spread(T0) == D("0.20")
    assert c.market_fill_price(BUY, D("2650.00"), T0) == D("2650.11")
    assert c.market_fill_price(SELL, D("2650.00"), T0) == D("2649.89")


def test_a_modelled_spread_ignores_quotes() -> None:
    c = calc(spread=FixedSpread(D("0.20")))
    quote = Quote("XAUUSD", T0, bid=D("2649.50"), ask=D("2650.50"))
    assert c.spread(T0, quote) == D("0.20")
    assert c.market_fill_price(BUY, D("2650.00"), T0, quote) == D("2650.10")


def test_quote_for_another_instrument_is_rejected() -> None:
    c = calc(spread=QuoteSpread(D("0.20")))
    with pytest.raises(ValueError, match="EURUSD"):
        c.market_fill_price(BUY, D("2650"), T0, Quote("EURUSD", T0, D("1.1"), D("1.1")))


def test_session_spread_uses_first_matching_window_in_order() -> None:
    spread = SessionSpread(D("0.20"), (("rollover", D("1.00")), ("asia", D("0.50"))))
    windows = {
        utc(2026, 10, 5, 1): frozenset({"asia"}),
        utc(2026, 10, 5, 21): frozenset({"asia", "rollover"}),
        utc(2026, 10, 5, 14): frozenset({"new_york"}),
    }
    c = CostCalculator(make_profile(spread=spread), GOLD, windows.__getitem__)
    assert c.spread(utc(2026, 10, 5, 1)) == D("0.50")
    assert c.spread(utc(2026, 10, 5, 21)) == D("1.00")
    assert c.spread(utc(2026, 10, 5, 14)) == D("0.20")
    assert c.market_fill_price(BUY, D("2650.00"), utc(2026, 10, 5, 21)) == D("2650.50")
    assert make_profile(spread=spread).session_windows == {"rollover", "asia"}


def test_session_spread_requires_a_window_lookup() -> None:
    profile = make_profile(spread=SessionSpread(D("0.2"), (("asia", D("0.5")),)))
    with pytest.raises(CostConfigError, match="window_lookup"):
        CostCalculator(profile, GOLD)


def test_non_positive_fill_and_bad_inputs_are_rejected() -> None:
    c = calc(spread=FixedSpread(D("0.30")))
    with pytest.raises(ValueError, match="non-positive"):
        c.market_fill_price(SELL, D("0.10"), T0)
    with pytest.raises(ValueError, match="positive"):
        c.market_fill_price(BUY, D("-1"), T0)
    with pytest.raises(TypeError, match="Decimal"):
        c.market_fill_price(BUY, 2650.0, T0)  # type: ignore[arg-type]
    with pytest.raises(ClockError, match="naive"):
        c.market_fill_price(BUY, D("2650"), datetime(2026, 10, 5, 14))  # noqa: DTZ001


# ── stops and limits ─────────────────────────────────────────────────────────
def test_stop_fills_cross_half_the_spread_and_slip_adversely() -> None:
    c = calc(spread=FixedSpread(D("0.20")), slippage=FixedTicksSlippage(2))
    assert c.stop_fill_price(SELL, D("2640.00"), T0) == D("2639.88")  # long stop-loss
    assert c.stop_fill_price(BUY, D("2660.00"), T0) == D("2660.12")  # short stop-loss
    assert c.stop_fill_price(SELL, D("2640.005"), T0) == D("2639.88")  # raw 2639.885 → down
    assert c.stop_fill_price(BUY, D("2660.005"), T0) == D("2660.13")  # raw 2660.125 → up


def test_limit_fills_exactly_at_the_limit_without_slippage() -> None:
    c = calc(spread=FixedSpread(D("0.20")), slippage=FixedTicksSlippage(5))
    assert c.limit_fill_price(SELL, D("2651.00")) == D("2651.00")
    assert c.limit_fill_price(BUY, D("2640.00")) == D("2640.00")
    with pytest.raises(ValueError, match="positive"):
        c.limit_fill_price(BUY, D(0))


def test_long_take_profit_needs_the_bid_not_the_mid() -> None:
    c = calc(spread=FixedSpread(D("0.20")))
    # Mid touches 2651.05 > target, but the bid only reaches 2650.95: no fill.
    assert not c.limit_triggered(SELL, D("2651.00"), D("2651.05"), D("2649.00"), T0)
    # Bid reaches exactly the target (2651.10 − 0.10): fills.
    assert c.limit_triggered(SELL, D("2651.00"), D("2651.10"), D("2649.00"), T0)


def test_short_take_profit_needs_the_ask_not_the_mid() -> None:
    c = calc(spread=FixedSpread(D("0.20")))
    assert not c.limit_triggered(BUY, D("2640.00"), D("2645.00"), D("2639.95"), T0)
    assert c.limit_triggered(BUY, D("2640.00"), D("2645.00"), D("2639.90"), T0)


def test_long_stop_loss_triggers_when_the_bid_reaches_it() -> None:
    c = calc(spread=FixedSpread(D("0.20")))
    # Mid low 2640.08 never touches 2640.00, but the bid (2639.98) does.
    assert c.stop_triggered(SELL, D("2640.00"), D("2650.00"), D("2640.08"), T0)
    assert not c.stop_triggered(SELL, D("2640.00"), D("2650.00"), D("2640.11"), T0)


def test_short_stop_loss_triggers_when_the_ask_reaches_it() -> None:
    c = calc(spread=FixedSpread(D("0.20")))
    assert c.stop_triggered(BUY, D("2660.00"), D("2659.92"), D("2650.00"), T0)
    assert not c.stop_triggered(BUY, D("2660.00"), D("2659.89"), D("2650.00"), T0)


def test_without_a_spread_the_mid_decides_triggers() -> None:
    c = calc()
    assert c.limit_triggered(SELL, D("2651.00"), D("2651.00"), D("2649.00"), T0)
    assert not c.limit_triggered(SELL, D("2651.00"), D("2650.99"), D("2649.00"), T0)
    assert c.stop_triggered(SELL, D("2640.00"), D("2650.00"), D("2640.00"), T0)


def test_inconsistent_bar_is_rejected() -> None:
    with pytest.raises(ValueError, match="below bar low"):
        calc().stop_triggered(SELL, D("2640"), D("2600"), D("2650"), T0)


# ── commission ───────────────────────────────────────────────────────────────
def test_per_quantity_commission_per_side_with_minimum() -> None:
    c = calc(commission=PerQuantityCommission(D("3.50")))
    assert c.commission(D(2), D("2650")) == D("7.0000")
    assert c.commission(D("0.01"), D("2650")) == D("0.0350")
    with_min = calc(commission=PerQuantityCommission(D("3.50"), minimum=D("5.00")))
    assert with_min.commission(D("0.5"), D("2650")) == D("5.0000")
    assert with_min.commission(D(2), D("2650")) == D("7.0000")


def test_per_contract_commission_does_not_depend_on_price() -> None:
    c = calc(MNQ, commission=PerQuantityCommission(D("0.95")))
    assert c.commission(D(3), D("20000")) == c.commission(D(3), D("1")) == D("2.8500")


def test_notional_commission_uses_maker_or_taker_rate() -> None:
    c = calc(NEAR, commission=NotionalCommission(D("0.0002"), D("0.0005")))
    assert c.commission(D(1000), D("2.500")) == D("1.2500")  # taker by default
    assert c.commission(D(1000), D("2.500"), Liquidity.MAKER) == D("0.5000")
    assert c.commission(D(1000), D("2.500"), "MAKER") == D("0.5000")  # type: ignore[arg-type]


def test_notional_commission_minimum_and_upward_rounding() -> None:
    c = calc(NEAR, commission=NotionalCommission(D("0.0002"), D("0.0005"), minimum=D("0.10")))
    assert c.commission(D(1), D("2.500")) == D("0.1000")  # 0.00125 < minimum
    rounding = calc(NEAR, commission=NotionalCommission(D("0.0002"), D("0.0005")))
    assert rounding.commission(D(1), D("3.333")) == D("0.0017")  # 0.0016665 rounds UP


@pytest.mark.parametrize("qty", [D(0), D(-1)])
def test_commission_rejects_non_positive_quantity(qty: Decimal) -> None:
    with pytest.raises(ValueError, match="qty"):
        calc(commission=PerQuantityCommission(D("3.50"))).commission(qty, D("2650"))


# ── funding ──────────────────────────────────────────────────────────────────
BINANCE_FUNDING = ConstantFunding(D("0.0001"), 8, (0, 8, 16))


def test_funding_at_anchors_start_exclusive_end_inclusive() -> None:
    c = calc(NEAR, funding=BINANCE_FUNDING)
    events = c.funding_events(LONG, D(1000), D("2.5"), utc(2026, 10, 5, 0), utc(2026, 10, 5, 16))
    assert [e.ts for e in events] == [utc(2026, 10, 5, 8), utc(2026, 10, 5, 16)]
    assert [e.amount for e in events] == [D("-0.2500"), D("-0.2500")]  # longs pay
    assert {e.kind for e in events} == {CostEventKind.FUNDING}
    assert {e.currency for e in events} == {"USDT"}
    assert events[0].kind == "FUNDING"


def test_shorts_receive_positive_rate_funding() -> None:
    c = calc(NEAR, funding=BINANCE_FUNDING)
    events = c.funding_events(SHORT, D(1000), D("2.5"), utc(2026, 10, 5, 0), utc(2026, 10, 5, 16))
    assert [e.amount for e in events] == [D("0.2500"), D("0.2500")]


def test_negative_funding_rate_pays_longs() -> None:
    c = calc(NEAR, funding=ConstantFunding(D("-0.0001"), 8, (0, 8, 16)))
    events = c.funding_events(LONG, D(1000), D("2.5"), utc(2026, 10, 5, 7), utc(2026, 10, 5, 9))
    assert [e.amount for e in events] == [D("0.2500")]


def test_funding_boundaries() -> None:
    c = calc(NEAR, funding=BINANCE_FUNDING)
    anchor = utc(2026, 10, 5, 8)
    assert c.funding_events(LONG, D(1), D(2), anchor, anchor) == []
    just_before = anchor - timedelta(seconds=1)
    assert [e.ts for e in c.funding_events(LONG, D(1), D(2), just_before, anchor)] == [anchor]
    assert c.funding_events(LONG, D(1), D(2), anchor, anchor + timedelta(hours=7, minutes=59)) == []
    # Across midnight: the 00:00 anchor of the next day belongs to the window.
    events = c.funding_events(LONG, D(1), D(2), utc(2026, 10, 5, 23), utc(2026, 10, 6, 1))
    assert [e.ts for e in events] == [utc(2026, 10, 6, 0)]


def test_funding_uses_the_mark_price_at_each_instant() -> None:
    c = calc(NEAR, funding=BINANCE_FUNDING)
    marks = {utc(2026, 10, 5, 8): D("2.0"), utc(2026, 10, 5, 16): D("3.0")}
    events = c.funding_events(
        LONG, D(1000), marks.__getitem__, utc(2026, 10, 5, 1), utc(2026, 10, 5, 23)
    )
    assert [e.amount for e in events] == [D("-0.2000"), D("-0.3000")]


def test_hourly_funding_over_24_hours() -> None:
    c = calc(NEAR, funding=ConstantFunding(D("0.0000125"), 1))
    events = c.funding_events(LONG, D(8000), D("2.5"), utc(2026, 10, 5, 0), utc(2026, 10, 6, 0))
    assert len(events) == 24
    assert events[0].ts == utc(2026, 10, 5, 1)
    assert events[-1].ts == utc(2026, 10, 6, 0)
    assert sum(e.amount for e in events) == D("-6.0000")  # 0.01 % per 8 h × 20,000 × 3


def test_interval_funding_without_anchors_starts_at_utc_midnight() -> None:
    funding = ConstantFunding(D("0.0001"), 4)
    assert funding.anchor_hours == (0, 4, 8, 12, 16, 20)
    events = calc(NEAR, funding=funding).funding_events(
        SHORT, D(1), D(2), utc(2026, 10, 5, 0), utc(2026, 10, 6, 0)
    )
    assert len(events) == 6


def test_funding_rounds_against_the_account_on_both_sides() -> None:
    c = calc(NEAR, funding=BINANCE_FUNDING)
    window = (utc(2026, 10, 5, 7), utc(2026, 10, 5, 9))
    # notional 1000 × 1.234567 = 1234.567 → 0.1234567 per interval
    assert c.funding_events(LONG, D(1000), D("1.234567"), *window)[0].amount == D("-0.1235")
    assert c.funding_events(SHORT, D(1000), D("1.234567"), *window)[0].amount == D("0.1234")


def test_funding_input_validation() -> None:
    c = calc(NEAR, funding=BINANCE_FUNDING)
    with pytest.raises(ValueError, match="before start"):
        c.funding_events(LONG, D(1), D(2), utc(2026, 10, 6, 0), utc(2026, 10, 5, 0))
    with pytest.raises(ValueError, match="qty"):
        c.funding_events(LONG, D(-1), D(2), utc(2026, 10, 5, 0), utc(2026, 10, 6, 0))
    with pytest.raises(ValueError, match="mark_price"):
        c.funding_events(LONG, D(1), D(0), utc(2026, 10, 5, 0), utc(2026, 10, 6, 0))
    with pytest.raises(ClockError):
        c.funding_events(LONG, D(1), D(2), datetime(2026, 10, 5), utc(2026, 10, 6, 0))  # noqa: DTZ001
    assert calc(NEAR).funding_events(LONG, D(1), D(2), utc(2026, 1, 1, 0), utc(2026, 2, 1, 0)) == []


# ── swap ─────────────────────────────────────────────────────────────────────
def test_swap_across_a_weekend_skips_saturday_and_sunday() -> None:
    c = calc(EURUSD, swap=fx_points_swap())
    events = c.swap_events(LONG, D(1), D("1.17"), ny(2026, 10, 2, 16), ny(2026, 10, 5, 18))
    assert [e.ts for e in events] == [ny(2026, 10, 2, 17), ny(2026, 10, 5, 17)]  # Fri, Mon
    assert [e.amount for e in events] == [D("-8.0000"), D("-8.0000")]
    assert {e.kind for e in events} == {CostEventKind.SWAP}


def test_swap_triple_day_counts_three_nights() -> None:
    c = calc(EURUSD, swap=fx_points_swap(triple=2))  # Wednesday
    events = c.swap_events(LONG, D(1), D("1.17"), ny(2026, 10, 6, 12), ny(2026, 10, 8, 12))
    assert [e.ts for e in events] == [ny(2026, 10, 6, 17), ny(2026, 10, 7, 17)]  # Tue, Wed
    assert [e.amount for e in events] == [D("-8.0000"), D("-24.0000")]
    friday_triple = calc(EURUSD, swap=fx_points_swap(triple=4))
    weekend = friday_triple.swap_events(
        LONG, D(1), D("1.17"), ny(2026, 10, 2, 16), ny(2026, 10, 5, 18)
    )
    assert [e.amount for e in weekend] == [D("-24.0000"), D("-8.0000")]


def test_a_full_week_charges_seven_nights_in_five_rollovers() -> None:
    c = calc(GOLD, swap=gold_points_swap())
    events = c.swap_events(LONG, D(1), D("4000"), ny(2026, 10, 5, 0), ny(2026, 10, 12, 0))
    assert len(events) == 5
    assert sum(e.amount for e in events) == D("-0.65") * 100 * 7


def test_short_swap_is_signed_as_configured() -> None:
    c = calc(GOLD, swap=gold_points_swap())
    events = c.swap_events(SHORT, D("0.5"), D("4000"), ny(2026, 10, 5, 12), ny(2026, 10, 5, 18))
    assert [e.amount for e in events] == [D("5.0000")]  # 0.10 × 100 oz × 0.5 lots


def test_swap_boundaries_start_exclusive_end_inclusive() -> None:
    c = calc(EURUSD, swap=fx_points_swap())
    rollover = ny(2026, 10, 5, 17)
    assert c.swap_events(LONG, D(1), D("1.17"), rollover, rollover + timedelta(hours=23)) == []
    events = c.swap_events(LONG, D(1), D("1.17"), rollover - timedelta(hours=1), rollover)
    assert [e.ts for e in events] == [rollover]


def test_swap_rollover_follows_new_york_dst_in_spring() -> None:
    c = calc(EURUSD, swap=fx_points_swap())
    # US clocks spring forward on Sunday 8 March 2026.
    events = c.swap_events(LONG, D(1), D("1.08"), ny(2026, 3, 6, 12), ny(2026, 3, 9, 18))
    assert [e.ts for e in events] == [utc(2026, 3, 6, 22), utc(2026, 3, 9, 21)]
    assert {e.ts.astimezone(NEW_YORK).time() for e in events} == {time(17)}


def test_swap_rollover_follows_new_york_dst_in_autumn() -> None:
    c = calc(EURUSD, swap=fx_points_swap())
    # US clocks fall back on Sunday 1 November 2026.
    events = c.swap_events(LONG, D(1), D("1.08"), ny(2026, 10, 30, 12), ny(2026, 11, 2, 18))
    assert [e.ts for e in events] == [utc(2026, 10, 30, 21), utc(2026, 11, 2, 22)]
    assert {e.ts.astimezone(NEW_YORK).time() for e in events} == {time(17)}


def test_swap_rollover_in_a_dst_gap_or_overlap_is_resolved_deterministically() -> None:
    # Egypt changes clocks on weekdays: 00:00 → 01:00 on Fri 24 Apr 2026 and
    # 24:00 → 23:00 on Thu 29 Oct 2026, so these rollovers hit a gap / an overlap.
    gap = calc(EURUSD, swap=PointsSwap(D("-0.0001"), D(0), time(0, 30), "Africa/Cairo", 2))
    events = gap.swap_events(LONG, D(1), D(1), utc(2026, 4, 23, 12), utc(2026, 4, 24, 12))
    assert [e.ts for e in events] == [utc(2026, 4, 23, 22, 30)]  # 01:30 local: shifted by the gap
    overlap = calc(EURUSD, swap=PointsSwap(D("-0.0001"), D(0), time(23, 30), "Africa/Cairo", 2))
    events = overlap.swap_events(LONG, D(1), D(1), utc(2026, 10, 29, 12), utc(2026, 10, 30, 12))
    assert [e.ts for e in events] == [utc(2026, 10, 29, 20, 30)]  # first occurrence (UTC+3)


def test_annual_rate_swap_charges_positive_rates_and_credits_negative_ones() -> None:
    swap = AnnualRateSwap(D("0.0625"), D("-0.01"), time(17), "America/New_York", 4, 360)
    c = calc(NAS100, swap=swap)
    window = (ny(2026, 10, 5, 12), ny(2026, 10, 5, 18))
    # −0.0625 × (2 × 25,000) / 360 = −8.680555… → rounded towards −∞
    assert [e.amount for e in c.swap_events(LONG, D(2), D("25000"), *window)] == [D("-8.6806")]
    # +0.01 × 50,000 / 360 = 1.388888… → rounded down
    assert [e.amount for e in c.swap_events(SHORT, D(2), D("25000"), *window)] == [D("1.3888")]
    friday = (ny(2026, 10, 9, 12), ny(2026, 10, 9, 18))
    prices = {ny(2026, 10, 9, 17): D("36000")}
    events = c.swap_events(LONG, D(1), prices.__getitem__, *friday)
    assert [e.amount for e in events] == [D("-18.7500")]  # 3 nights × 0.0625 × 36,000 / 360


def test_no_swap_and_input_validation() -> None:
    assert calc(EURUSD).swap_events(LONG, D(1), D(1), ny(2026, 1, 1, 0), ny(2026, 2, 1, 0)) == []
    with pytest.raises(ValueError, match="qty"):
        calc(EURUSD, swap=fx_points_swap()).swap_events(
            LONG, D(0), D(1), ny(2026, 10, 5, 0), ny(2026, 10, 6, 0)
        )


# ── events ───────────────────────────────────────────────────────────────────
def test_cost_event_validation() -> None:
    event = CostEvent(ny(2026, 10, 5, 17), "SWAP", D("-1"), "detail")
    assert event.ts.tzinfo is UTC
    assert event.kind is CostEventKind.SWAP
    with pytest.raises(ClockError):
        CostEvent(datetime(2026, 10, 5), "SWAP", D(1), "")  # noqa: DTZ001
    with pytest.raises(ValueError, match="kind"):
        CostEvent(T0, "COMMISSION", D(1), "")
    assert D("0.0001") == MONEY_QUANTUM


# ── documents ────────────────────────────────────────────────────────────────
def load_yaml() -> dict[str, Any]:
    document = yaml.safe_load(COSTS_YAML.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def test_costs_yaml_round_trips_through_profiles() -> None:
    document = load_yaml()
    profiles = parse_cost_profiles(document)
    assert {
        "zero_cost",
        "cfd_metals",
        "cfd_silver",
        "cfd_fx_majors",
        "cme_micro_equity",
        "crypto_spot_taker",
        "crypto_perp_binance",
        "crypto_perp_bybit",
        "crypto_perp_hyperliquid",
    } <= set(profiles)
    assert [p.to_dict() for p in profiles.values()] == document["cost_profiles"]
    assert cost_profiles_document(profiles.values()) == {"cost_profiles": document["cost_profiles"]}
    for profile in profiles.values():
        assert CostProfile.from_dict(profile.to_dict()) == profile


def test_costs_yaml_profiles_have_the_documented_shapes() -> None:
    profiles = parse_cost_profiles(load_yaml())
    zero = profiles["zero_cost"]
    assert (zero.spread, zero.commission, zero.slippage, zero.funding, zero.swap) == (
        NoSpread(),
        NoCommission(),
        NoSlippage(),
        NoFunding(),
        NoSwap(),
    )
    metals = profiles["cfd_metals"]
    assert metals.spread == FixedSpread(D("0.20"))
    assert isinstance(metals.swap, PointsSwap)
    assert metals.swap.triple_day == 2
    binance = profiles["crypto_perp_binance"].funding
    assert binance == ConstantFunding(D("0.0001"), 8, (0, 8, 16))
    hyperliquid = profiles["crypto_perp_hyperliquid"].funding
    assert isinstance(hyperliquid, ConstantFunding)
    assert hyperliquid.anchor_hours == tuple(range(24))


def test_every_yaml_profile_costs_a_round_trip_against_the_trader() -> None:
    cases = {
        "cfd_metals": (GOLD, D("4000.00")),
        "cfd_fx_majors": (EURUSD, D("1.17000")),
        "cfd_us_indices_nas100": (NAS100, D("25000.00")),
        "cme_micro_equity": (MNQ, D("25000.00")),
        "crypto_perp_binance": (NEAR, D("2.500")),
    }
    profiles = parse_cost_profiles(load_yaml())
    for profile_id, (listing, mid) in cases.items():
        c = CostCalculator(profiles[profile_id], listing)
        buy = c.market_fill_price(BUY, mid, T0)
        sell = c.market_fill_price(SELL, mid, T0)
        assert buy > mid > sell, profile_id
        assert c.commission(D(1), mid) >= 0


def test_session_spread_document_round_trip_keeps_window_order() -> None:
    data = {
        "model": "session",
        "default_points": "0.30",
        "by_window": {"rollover": "0.9", "asia": "0.5"},
    }
    profile_doc = {
        "id": "with_sessions",
        "description": "",
        "spread": data,
        "commission": {"model": "none"},
        "slippage": {"model": "none"},
        "funding": {"model": "none"},
        "swap": {"model": "none"},
    }
    profile = CostProfile.from_dict(profile_doc)
    assert isinstance(profile.spread, SessionSpread)
    assert profile.spread.by_window == (("rollover", D("0.9")), ("asia", D("0.5")))
    assert profile.to_dict() == profile_doc


def test_weekday_spellings_and_unsorted_anchors_are_normalised() -> None:
    base = {"model": "points", "long_points": "-1", "short_points": "0"}
    rollover = {"rollover_time": "17:00", "timezone": "America/New_York"}
    for spelling in ("WED", "wed", "Wednesday", 2):
        assert PointsSwap.from_dict({**base, **rollover, "triple_day": spelling}).triple_day == 2
    funding = ConstantFunding.from_dict(
        {
            "model": "constant",
            "rate_per_interval": "0.0001",
            "interval_hours": 8,
            "anchor_hours_utc": [16, 0, 8],
        }
    )
    assert funding.anchor_hours_utc == (0, 8, 16)


def _profile_doc(**overrides: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "id": "bad_profile",
        "description": "",
        "spread": {"model": "fixed", "points": "0.20"},
        "commission": {"model": "per_quantity", "per_side": "3.50", "minimum": "0"},
        "slippage": {"model": "fixed_ticks", "ticks": 1},
        "funding": {"model": "none"},
        "swap": {
            "model": "points",
            "long_points": "-0.5",
            "short_points": "0.1",
            "rollover_time": "17:00",
            "timezone": "America/New_York",
            "triple_day": "WED",
        },
    }
    doc.update(overrides)
    return doc


SWAP = _profile_doc()["swap"]


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"spread": {"model": "fixed", "points": 0.2}}, "quoted strings"),
        ({"spread": {"model": "fixed", "points": "abc"}}, "not a decimal"),
        ({"spread": {"model": "fixed", "points": "-0.1"}}, "cannot be negative"),
        ({"spread": {"model": "wide"}}, "unknown model 'wide'"),
        ({"spread": {"model": "fixed", "points": "0.2", "pips": "2"}}, "unknown field"),
        ({"spread": {"model": "fixed"}}, "missing field"),
        ({"spread": "fixed"}, "expected a mapping"),
        ({"commission": {"model": "notional", "maker_rate": "0.02", "taker_rate": "0.05"}}, "0.05"),
        ({"slippage": {"model": "fixed_ticks", "ticks": "1"}}, "integer"),
        (
            {"funding": {"model": "constant", "rate_per_interval": "0.0001", "interval_hours": 5}},
            "divide 24",
        ),
        (
            {
                "funding": {
                    "model": "constant",
                    "rate_per_interval": "0.0001",
                    "interval_hours": 8,
                    "anchor_hours_utc": [0, 8],
                }
            },
            "not every 8 h",
        ),
        ({"swap": {**SWAP, "rollover_time": 1020}}, "quote local times"),
        ({"swap": {**SWAP, "rollover_time": "5pm"}}, "HH:MM"),
        ({"swap": {**SWAP, "timezone": "America/Gotham"}}, "unknown time zone"),
        ({"swap": {**SWAP, "triple_day": "SAT"}}, "triple_day"),
        ({"swap": {**SWAP, "triple_day": "someday"}}, "weekday"),
        (
            {
                "swap": {
                    **SWAP,
                    "model": "annual_rate",
                    "long_rate": "0.05",
                    "short_rate": "0",
                    "long_points": None,
                }
            },
            "unknown field",
        ),
        ({"id": "Bad-Id"}, "invalid cost profile id"),
        ({"colour": "red"}, "unknown field"),
    ],
)
def test_invalid_profiles_are_rejected_with_clear_errors(
    overrides: dict[str, Any], message: str
) -> None:
    with pytest.raises(CostConfigError, match=message) as excinfo:
        CostProfile.from_dict(_profile_doc(**overrides))
    assert isinstance(excinfo.value, ValueError)


def test_missing_component_is_an_error_not_a_free_cost() -> None:
    doc = _profile_doc()
    del doc["commission"]
    with pytest.raises(CostConfigError, match=r"missing commission \(write \{model: none\}"):
        CostProfile.from_dict(doc)


def test_parse_cost_profiles_rejects_duplicates_and_bad_shapes() -> None:
    with pytest.raises(CostConfigError, match="duplicate cost profile id 'bad_profile'"):
        parse_cost_profiles({"cost_profiles": [_profile_doc(), _profile_doc()]})
    with pytest.raises(CostConfigError, match=r"cost_profiles\[0\]: cost profile 'bad_profile'"):
        parse_cost_profiles({"cost_profiles": [_profile_doc(spread={"model": "nope"})]})
    with pytest.raises(CostConfigError, match="expected a list"):
        parse_cost_profiles({"cost_profiles": {"a": 1}})
    assert parse_cost_profiles({"listings": []}) == {}


def test_annual_rate_day_count_is_validated() -> None:
    with pytest.raises(CostConfigError, match="day_count"):
        AnnualRateSwap(D("0.05"), D(0), time(17), "America/New_York", 4, 300)


# ── properties ───────────────────────────────────────────────────────────────
TICKS = ["0.01", "0.25", "0.1", "0.00001", "0.001"]


@given(
    mid=st.decimals(min_value=D("0.5"), max_value=D("200000"), places=5),
    spread=st.decimals(min_value=D(0), max_value=D("5"), places=3),
    slip_ticks=st.integers(min_value=0, max_value=20),
    bps=st.decimals(min_value=D(0), max_value=D("50"), places=1),
    use_bps=st.booleans(),
    tick=st.sampled_from(TICKS),
)
def test_property_market_buy_ge_mid_ge_market_sell(
    mid: Decimal,
    spread: Decimal,
    slip_ticks: int,
    bps: Decimal,
    use_bps: bool,
    tick: str,
) -> None:
    listing = make_listing("XAUUSD", tick, "100")
    slippage: SlippageModel = (
        NotionalBpsSlippage(bps) if use_bps else FixedTicksSlippage(slip_ticks)
    )
    c = CostCalculator(make_profile(spread=FixedSpread(spread), slippage=slippage), listing)
    assume(mid - spread / 2 - c.slippage(mid, T0) - D(tick) > 0)
    buy = c.market_fill(BUY, mid, T0)
    sell = c.market_fill(SELL, mid, T0)
    assert buy.price >= mid >= sell.price
    assert buy.price - sell.price >= spread
    for fill in (buy, sell):
        assert fill.rounding >= 0
        assert fill.price % D(tick) == 0  # on the tick grid
    stop_buy = c.stop_fill_price(BUY, mid, T0)
    stop_sell = c.stop_fill_price(SELL, mid, T0)
    assert stop_buy >= mid >= stop_sell


# ── adversarial-review regressions ───────────────────────────────────────────
def test_daily_funding_with_a_single_anchor_is_valid() -> None:
    # One settlement a day at 08:00 UTC: one anchor, a 24 h interval.
    funding = ConstantFunding(D("0.0003"), 24, (8,))
    assert funding.anchor_hours == (8,)
    parsed = ConstantFunding.from_dict(
        {
            "model": "constant",
            "rate_per_interval": "0.0003",
            "interval_hours": 24,
            "anchor_hours_utc": [8],
        }
    )
    assert parsed == funding
    events = calc(NEAR, funding=funding).funding_events(
        LONG, D(1000), D("2.5"), utc(2026, 10, 5, 0), utc(2026, 10, 8, 0)
    )
    assert [e.ts for e in events] == [utc(2026, 10, d, 8) for d in (5, 6, 7)]
    assert [e.amount for e in events] == [D("-0.7500")] * 3


@pytest.mark.parametrize("spelling", ["17.30", "17,30", "T1730", "17:30:00.5", "7:30"])
def test_rollover_time_rejects_ambiguous_spellings(spelling: str) -> None:
    # time.fromisoformat("17.30") is 17:00:00.300000 — never what the author meant.
    with pytest.raises(CostConfigError, match="HH:MM"):
        CostProfile.from_dict(_profile_doc(swap={**SWAP, "rollover_time": spelling}))


def test_rollover_time_must_be_whole_seconds() -> None:
    # to_dict writes HH:MM[:SS]; a sub-second time could not round-trip.
    with pytest.raises(CostConfigError, match="whole seconds"):
        PointsSwap(D("-1"), D(0), time(17, 0, 0, 500), "America/New_York", 2)
    swap = PointsSwap(D("-1"), D(0), time(16, 59, 30), "America/New_York", 2)
    assert PointsSwap.from_dict(swap.to_dict()) == swap


def test_a_quote_from_after_the_fill_instant_is_look_ahead() -> None:
    c = calc(spread=QuoteSpread(D("0.20")))
    future = Quote("XAUUSD", T0 + timedelta(seconds=1), bid=D("2650.00"), ask=D("2650.40"))
    calls: list[Callable[[], object]] = [
        lambda: c.market_fill_price(BUY, D("2650"), T0, future),
        lambda: c.stop_fill_price(SELL, D("2650"), T0, future),
        lambda: c.spread(T0, future),
    ]
    for call in calls:
        with pytest.raises(ValueError, match="look-ahead"):
            call()
    same_instant = Quote("XAUUSD", T0, bid=D("2650.00"), ask=D("2650.40"))
    assert c.market_fill_price(BUY, D("2650"), T0, same_instant) == D("2650.40")


def test_profile_components_are_type_checked() -> None:
    with pytest.raises(CostConfigError, match="spread"):
        CostProfile(
            id="mixed_up",
            description="",
            spread=NoSlippage(),  # type: ignore[arg-type]
            commission=NoCommission(),
            slippage=NoSlippage(),
            funding=NoFunding(),
            swap=NoSwap(),
        )
    with pytest.raises(CostConfigError, match="swap"):
        make_profile(swap=NoFunding())  # type: ignore[arg-type]


@pytest.mark.parametrize("document", [None, [], "cost_profiles"])
def test_parse_cost_profiles_rejects_a_non_mapping_document(document: Any) -> None:
    with pytest.raises(CostConfigError, match="mapping"):
        parse_cost_profiles(document)


def test_session_spread_window_ids_must_be_session_window_ids() -> None:
    with pytest.raises(CostConfigError, match="window id"):
        SessionSpread(D("0.2"), (("Asia Session", D("0.5")),))
    with pytest.raises(CostConfigError, match="window id"):
        CostProfile.from_dict(
            _profile_doc(
                spread={"model": "session", "default_points": "0.2", "by_window": {None: "0.5"}}
            )
        )


@pytest.mark.parametrize(
    ("component", "field", "value"),
    [
        ("funding", "anchor_hours_utc", 0),
        ("funding", "anchor_hours_utc", ""),
        ("spread", "by_window", 0),
        ("spread", "by_window", ""),
    ],
)
def test_falsy_scalars_are_rejected_not_read_as_empty(
    component: str, field: str, value: object
) -> None:
    bases: dict[str, dict[str, Any]] = {
        "funding": {"model": "constant", "rate_per_interval": "0.0001", "interval_hours": 8},
        "spread": {"model": "session", "default_points": "0.2"},
    }
    base = bases[component]
    with pytest.raises(CostConfigError, match=field):
        CostProfile.from_dict(_profile_doc(**{component: {**base, field: value}}))
    # An explicitly empty value (YAML `field:` or `[]` / `{}`) is still "none".
    empties: tuple[object, ...] = (None, [] if field == "anchor_hours_utc" else {})
    for empty in empties:
        CostProfile.from_dict(_profile_doc(**{component: {**base, field: empty}}))


def test_results_do_not_depend_on_the_ambient_decimal_context() -> None:
    # A strategy (or library) in the same thread that changes the decimal
    # context must not change the costs every other lab account is charged.
    c = calc(
        NEAR,
        spread=FixedSpread(D("0.0020")),
        commission=NotionalCommission(D("0.0002"), D("0.0005")),
        slippage=NotionalBpsSlippage(D("1.5")),
        funding=BINANCE_FUNDING,
    )
    g = calc(spread=FixedSpread(D("0.20")))

    def results() -> tuple[object, ...]:
        return (
            c.market_fill(BUY, D("2.3455"), T0),
            c.stop_fill(SELL, D("2.3455"), T0),
            c.commission(D("1234"), D("2.345")),
            c.funding_events(LONG, D("1234"), D("2.345"), T0, utc(2026, 10, 6, 1)),
            g.market_fill_price(BUY, D("2650.005"), T0),
            g.limit_triggered(SELL, D("2651.00"), D("2651.05"), D("2649.00"), T0),
            g.stop_triggered(SELL, D("2640.00"), D("2650.00"), D("2640.11"), T0),
        )

    expected = results()
    assert expected[5] is False and expected[6] is False
    for prec, rounding in ((4, decimal.ROUND_HALF_EVEN), (6, decimal.ROUND_DOWN)):
        with decimal.localcontext(prec=prec, rounding=rounding):
            assert results() == expected


def test_sequence_fields_are_normalised_to_tuples() -> None:
    funding = ConstantFunding(D("0.0001"), 8, [0, 8, 16])  # type: ignore[arg-type]
    assert funding == BINANCE_FUNDING
    assert funding.anchor_hours_utc == (0, 8, 16)
    spread = SessionSpread(D("0.2"), [["asia_session", D("0.5")]])  # type: ignore[arg-type]
    assert spread.by_window == (("asia_session", D("0.5")),)
    profile = make_profile(spread=spread, funding=funding)
    assert hash(profile) == hash(make_profile(spread=spread, funding=BINANCE_FUNDING))


def test_funding_is_only_charged_on_perpetual_listings() -> None:
    profile = make_profile(funding=BINANCE_FUNDING)
    for listing in (
        GOLD,
        MNQ,
        make_listing("BTCUSD", "0.01", "1", contract_type=ContractType.SPOT),
    ):
        with pytest.raises(CostConfigError, match="PERPETUAL"):
            CostCalculator(profile, listing)
    assert CostCalculator(profile, NEAR).profile is profile


ZONES = ["America/New_York", "Europe/London", "Australia/Sydney", "Africa/Cairo", "Asia/Tokyo"]
YEAR_START = utc(2026, 1, 1, 0)


@given(
    offsets=st.lists(st.integers(min_value=0, max_value=730 * 24 * 60), min_size=3, max_size=3),
    zone=st.sampled_from(ZONES),
    rollover=st.sampled_from([time(17), time(0, 30), time(23, 30), time(2, 30), time(22)]),
    triple=st.integers(min_value=0, max_value=4),
    interval=st.sampled_from([1, 4, 8, 24]),
)
def test_property_split_intervals_charge_exactly_the_same_events(
    offsets: list[int], zone: str, rollover: time, triple: int, interval: int
) -> None:
    # The paper account accrues holding costs bar by bar: (a, b] + (b, c] must
    # equal (a, c] exactly — no event counted twice or lost at a boundary or DST change.
    a, b, c = sorted(YEAR_START + timedelta(minutes=m) for m in offsets)
    swap = calc(EURUSD, swap=PointsSwap(D("-0.00008"), D("0.00002"), rollover, zone, triple))
    funding = calc(NEAR, funding=ConstantFunding(D("0.0001"), interval))
    for events_of in (swap.swap_events, funding.funding_events):
        whole = events_of(LONG, D(1), D("2.5"), a, c)
        assert (
            events_of(LONG, D(1), D("2.5"), a, b) + events_of(LONG, D(1), D("2.5"), b, c) == whole
        )
        assert [e.ts for e in whole] == sorted({e.ts for e in whole})  # strictly increasing
        assert all(a < e.ts <= c for e in whole)


@given(
    week=st.integers(min_value=0, max_value=104),
    zone=st.sampled_from(ZONES),
    rollover=st.sampled_from([time(17), time(0, 30), time(23, 30), time(2, 30)]),
    triple=st.integers(min_value=0, max_value=4),
)
def test_property_every_local_week_charges_seven_nights(
    week: int, zone: str, rollover: time, triple: int
) -> None:
    tz = ZoneInfo(zone)
    monday = datetime(2025, 12, 29, tzinfo=tz) + timedelta(weeks=week)  # a local Monday 00:00
    start = datetime.combine(monday.date(), time(0), tzinfo=tz)
    end = datetime.combine((monday + timedelta(days=7)).date(), time(0), tzinfo=tz)
    c = calc(GOLD, swap=PointsSwap(D("-1"), D(0), rollover, zone, triple))
    events = c.swap_events(LONG, D(1), D("4000"), start, end)
    assert len(events) == 5
    assert sum(e.amount for e in events) == D(-1) * 100 * 7
    for event in events:
        local = event.ts.astimezone(tz)
        assert local.weekday() < 5
        if local.time() != rollover:  # only a spring-forward gap may move it, forward
            assert local.time() > rollover


@given(
    start=st.integers(min_value=0, max_value=365 * 24 * 3600),
    interval=st.sampled_from([1, 2, 3, 4, 6, 8, 12, 24]),
    rate=st.decimals(min_value=D("-0.003"), max_value=D("0.003"), places=6),
    mark=st.decimals(min_value=D("0.001"), max_value=D("100000"), places=3),
)
def test_property_funding_per_day_and_never_flattering(
    start: int, interval: int, rate: Decimal, mark: Decimal
) -> None:
    c = calc(NEAR, funding=ConstantFunding(rate, interval))
    a = YEAR_START + timedelta(seconds=start)
    longs = c.funding_events(LONG, D(7), mark, a, a + timedelta(days=1))
    shorts = c.funding_events(SHORT, D(7), mark, a, a + timedelta(days=1))
    assert len(longs) == len(shorts) == 24 // interval
    for long_event, short_event in zip(longs, shorts, strict=True):
        exact = rate * D(7) * mark
        assert long_event.amount <= -exact and short_event.amount <= exact
        assert long_event.amount + short_event.amount <= 0  # rounding never nets a gain
        assert long_event.amount % MONEY_QUANTUM == 0


def test_swap_is_never_charged_on_futures_or_perpetuals() -> None:
    swap = PointsSwap(D("-0.5"), D("0.1"), time(17), "America/New_York", 4)
    profile = make_profile(swap=swap)
    for listing in (MNQ, NEAR):
        assert profile_listing_problems(profile, listing)
        with pytest.raises(CostConfigError, match="swap"):
            CostCalculator(profile, listing)
    assert profile_listing_problems(profile, GOLD) == []


def test_every_yaml_profile_fits_the_listings_it_is_meant_for() -> None:
    profiles = parse_cost_profiles(load_yaml())
    meant_for = {
        "zero_cost": (GOLD, EURUSD, NAS100, MNQ, NEAR),
        "cfd_metals": (GOLD,),
        "cfd_silver": (make_listing("XAGUSD", "0.001", "5000"),),
        "cfd_fx_majors": (EURUSD,),
        "cfd_fx_gbpusd": (make_listing("GBPUSD", "0.00001", "100000"),),
        "cfd_us_indices_nas100": (NAS100,),
        "cfd_us_indices_us30": (make_listing("US30", "0.01", "1"),),
        "cfd_us_indices_us500": (make_listing("US500", "0.01", "1"),),
        "cme_micro_equity": (MNQ,),
        "crypto_spot_taker": (
            make_listing("BTCUSD", "0.01", "1", contract_type=ContractType.SPOT, step="0.00001"),
        ),
        "crypto_perp_binance": (NEAR,),
        "crypto_perp_bybit": (NEAR,),
        "crypto_perp_hyperliquid": (NEAR,),
    }
    assert set(meant_for) == set(profiles)
    for profile_id, listings in meant_for.items():
        for listing in listings:
            assert profile_listing_problems(profiles[profile_id], listing) == [], profile_id
            CostCalculator(profiles[profile_id], listing)
