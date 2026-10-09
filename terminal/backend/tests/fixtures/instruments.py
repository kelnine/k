"""Instrument fixtures for tests (catalog-independent)."""

from datetime import UTC, datetime
from decimal import Decimal

from kterminal.domain.instruments import (
    AssetClass,
    ContractType,
    Instrument,
    Listing,
    QuantityUnit,
)
from kterminal.domain.market import Bar
from kterminal.domain.timeframes import Timeframe
from kterminal.marketdata.synthetic import synthetic_bars

XAUUSD = Instrument(
    symbol="XAUUSD",
    name="Gold / US Dollar",
    asset_class=AssetClass.METAL,
    base="XAU",
    quote_currency="USD",
    tick_size=Decimal("0.01"),
    trading_hours="metals_otc",
    trading_day="ny_1700",
    underlying="GOLD",
)
XAGUSD = Instrument(
    symbol="XAGUSD",
    name="Silver / US Dollar",
    asset_class=AssetClass.METAL,
    base="XAG",
    quote_currency="USD",
    tick_size=Decimal("0.001"),
    trading_hours="metals_otc",
    trading_day="ny_1700",
    underlying="SILVER",
)
INSTRUMENTS = {i.symbol: i for i in (XAUUSD, XAGUSD)}

XAU_CFD = Listing(
    venue="generic_mt5_cfd",
    instrument="XAUUSD",
    venue_symbol="XAUUSD",
    contract_type=ContractType.CFD,
    tick_size=Decimal("0.01"),
    contract_size=Decimal(100),
    quantity_unit=QuantityUnit.LOTS,
    min_qty=Decimal("0.01"),
    qty_step=Decimal("0.01"),
    quote_currency="USD",
)

T0 = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)  # a Monday


def bars(
    instrument: str,
    timeframe: str,
    rows: list[tuple[float, float, float, float]],
    start: datetime = T0,
) -> list[Bar]:
    """Build consecutive bars from (open, high, low, close) rows."""
    tf = Timeframe.parse(timeframe)
    return [
        Bar.of(instrument, tf, start + i * tf.duration, o, h, low, c)
        for i, (o, h, low, c) in enumerate(rows)
    ]


def gold_minutes(count: int, seed: int = 7) -> list[Bar]:
    return list(
        synthetic_bars(
            "XAUUSD",
            start=T0,
            count=count,
            start_price=Decimal("2650.00"),
            tick_size=Decimal("0.01"),
            seed=seed,
        )
    )
