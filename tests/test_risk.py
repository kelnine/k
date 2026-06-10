from tradingbot.config import INSTRUMENTS, RiskConfig
from tradingbot.risk import correlation_filter_allows, plan_position
from tradingbot.strategies.base import LONG, SHORT


def test_stop_loss_is_exactly_one_percent_of_equity():
    cfg = RiskConfig()
    plan = plan_position(equity=100_000, price=500, atr_value=4.0, direction=LONG, cfg=cfg)
    assert plan is not None
    loss_at_stop = (500 - plan.stop_price) * plan.quantity
    assert abs(loss_at_stop - 1_000) < 1e-6  # 1% of 100k, no exceptions


def test_quiet_instrument_gets_bigger_size_than_volatile_one():
    cfg = RiskConfig()
    quiet_gold = plan_position(100_000, 2000, atr_value=5.0, direction=LONG, cfg=cfg)
    wild_btc = plan_position(100_000, 2000, atr_value=50.0, direction=LONG, cfg=cfg)
    assert quiet_gold.quantity > wild_btc.quantity
    # ...but the money at risk is identical
    assert abs(quiet_gold.risk_amount - wild_btc.risk_amount) < 1e-9


def test_short_stop_sits_above_entry():
    cfg = RiskConfig()
    plan = plan_position(100_000, 500, atr_value=4.0, direction=SHORT, cfg=cfg)
    assert plan.stop_price > 500


def test_correlation_filter_blocks_third_risk_on_long():
    cfg = RiskConfig()
    open_positions = {"SPX": LONG, "NDX": LONG}
    allowed, why = correlation_filter_allows(
        INSTRUMENTS["BTC"], LONG, open_positions, INSTRUMENTS, cfg
    )
    assert not allowed
    assert "correlation" in why


def test_correlation_filter_allows_uncorrelated_entry():
    cfg = RiskConfig()
    open_positions = {"SPX": LONG, "NDX": LONG}
    # gold is in a different risk group: fine
    allowed, _ = correlation_filter_allows(
        INSTRUMENTS["GOLD"], LONG, open_positions, INSTRUMENTS, cfg
    )
    assert allowed
    # and a bitcoin SHORT is the opposite side of risk-on: also fine
    allowed, _ = correlation_filter_allows(
        INSTRUMENTS["BTC"], SHORT, open_positions, INSTRUMENTS, cfg
    )
    assert allowed


def test_max_open_positions_cap():
    cfg = RiskConfig(max_open_positions=2)
    open_positions = {"GOLD": LONG, "OIL": SHORT}
    allowed, why = correlation_filter_allows(
        INSTRUMENTS["BTC"], LONG, open_positions, INSTRUMENTS, cfg
    )
    assert not allowed
    assert "max open positions" in why
