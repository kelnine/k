from datetime import date
from decimal import Decimal

import pytest

from kterminal.core.enums import Direction
from kterminal.domain.instruments import (
    AssetClass,
    ContractType,
    CurrencyConversionError,
    CurrencyRates,
    FuturesSpec,
    Instrument,
    Listing,
    PnlModel,
    QuantityUnit,
    Venue,
    VenueKind,
    quantize_to_step,
    round_price,
)


def gold_cfd(**overrides: object) -> Listing:
    fields: dict[str, object] = {
        "venue": "generic_mt5_cfd",
        "instrument": "XAUUSD",
        "venue_symbol": "XAUUSD",
        "contract_type": ContractType.CFD,
        "tick_size": Decimal("0.01"),
        "contract_size": Decimal(100),
        "quantity_unit": QuantityUnit.LOTS,
        "min_qty": Decimal("0.01"),
        "qty_step": Decimal("0.01"),
        "quote_currency": "USD",
    }
    fields.update(overrides)
    return Listing(**fields)  # type: ignore[arg-type]


def test_quantize_keeps_step_exponent() -> None:
    assert str(quantize_to_step(Decimal("2678.4"), Decimal("0.01"))) == "2678.40"
    assert quantize_to_step(Decimal("2678.437"), Decimal("0.25")) == Decimal("2678.50")
    with pytest.raises(ValueError, match="positive"):
        quantize_to_step(Decimal(1), Decimal(0))


def test_adverse_price_rounding() -> None:
    tick = Decimal("0.25")
    assert round_price(Decimal("100.10"), tick, is_buy=True) == Decimal("100.25")
    assert round_price(Decimal("100.10"), tick, is_buy=False) == Decimal("100.00")
    assert round_price(Decimal("100.10"), tick) == Decimal("100.00")


def test_listing_money_math_gold_cfd() -> None:
    listing = gold_cfd()
    assert listing.point_value == Decimal(100)
    assert listing.tick_value == Decimal("1.00")
    # 0.48 lots, long 2678.40 → 2673.20 (stop) = -5.20 × 0.48 × 100 = -249.60
    assert listing.pnl(
        Direction.LONG, Decimal("0.48"), Decimal("2678.40"), Decimal("2673.20")
    ) == Decimal("-249.6000")
    assert listing.pnl(Direction.SHORT, Decimal(1), Decimal(10), Decimal(9)) == Decimal(100)
    assert listing.round_qty_down(Decimal("0.4807")) == Decimal("0.48")
    assert listing.notional(Decimal("0.5"), Decimal(2000)) == Decimal("100000.0")


def test_listing_money_math_micro_futures() -> None:
    mnq = Listing(
        venue="cme",
        instrument="MNQ",
        venue_symbol="MNQ",
        contract_type=ContractType.FUTURE,
        tick_size=Decimal("0.25"),
        contract_size=Decimal(2),
        quantity_unit=QuantityUnit.CONTRACTS,
        min_qty=Decimal(1),
        qty_step=Decimal(1),
        quote_currency="USD",
        symbol_format="{root}{code}{y1}",
    )
    assert mnq.tick_value == Decimal("0.50")
    assert mnq.round_qty_down(Decimal("3.99")) == Decimal(3)


def test_listing_validation_and_inverse_contracts() -> None:
    with pytest.raises(ValueError, match="tick_size must be positive"):
        gold_cfd(tick_size=Decimal(0))
    with pytest.raises(ValueError, match="max_qty below min_qty"):
        gold_cfd(max_qty=Decimal("0.001"))
    inverse = gold_cfd(pnl_model=PnlModel.INVERSE)
    with pytest.raises(NotImplementedError, match="INVERSE"):
        _ = inverse.point_value
    data_only = gold_cfd(contract_type=ContractType.INDEX_DATA)
    assert data_only.tradable is False


def test_futures_front_contract_and_symbols() -> None:
    spec = FuturesSpec(root="MNQ")
    dec = spec.contract(2026, 12)
    assert dec.expiry == date(2026, 12, 18)  # third Friday
    assert dec.roll_date == date(2026, 12, 10)
    assert spec.front_contract(date(2026, 10, 6)) == dec
    assert spec.front_contract(date(2026, 12, 9)).month == 12
    rolled = spec.front_contract(date(2026, 12, 10))
    assert (rolled.year, rolled.month) == (2027, 3)
    assert dec.symbol("{root}{code}{y1}") == "MNQZ6"
    assert dec.symbol("{root}{code}{yyyy}") == "MNQZ2026"
    assert dec.symbol("{root} {yyyy}{mm}") == "MNQ 202612"
    with pytest.raises(ValueError, match="no contract in month"):
        spec.contract(2026, 1)
    with pytest.raises(ValueError, match="unsupported expiry rule"):
        FuturesSpec(root="MNQ", expiry_rule="last_business_day")


def test_venue_symbol_for_dated_futures() -> None:
    instrument = Instrument(
        symbol="MNQ",
        name="Micro E-mini Nasdaq-100",
        asset_class=AssetClass.INDEX,
        base="NDX",
        quote_currency="USD",
        tick_size=Decimal("0.25"),
        trading_hours="cme_globex_equity",
        trading_day="ny_1700",
        futures=FuturesSpec(root="MNQ"),
    )
    listing = Listing(
        venue="tradovate",
        instrument="MNQ",
        venue_symbol="MNQ",
        contract_type=ContractType.FUTURE,
        tick_size=Decimal("0.25"),
        contract_size=Decimal(2),
        quantity_unit=QuantityUnit.CONTRACTS,
        min_qty=Decimal(1),
        qty_step=Decimal(1),
        quote_currency="USD",
        symbol_format="{root}{code}{y1}",
    )
    assert listing.venue_symbol_for(instrument, date(2026, 10, 6)) == "MNQZ6"
    assert listing.venue_symbol_for(instrument, date(2027, 1, 4)) == "MNQH7"


def test_instrument_and_venue_validation() -> None:
    with pytest.raises(ValueError, match="invalid canonical symbol"):
        Instrument(
            symbol="xau usd",
            name="x",
            asset_class=AssetClass.METAL,
            base="XAU",
            quote_currency="USD",
            tick_size=Decimal("0.01"),
            trading_hours="h",
            trading_day="d",
        )
    with pytest.raises(ValueError, match="invalid venue id"):
        Venue(id="Bad Venue", name="x", kind=VenueKind.BROKER)


def test_currency_rates() -> None:
    rates = CurrencyRates()
    assert rates.convert(Decimal(10), "USDT", "USD") == Decimal(10)
    assert rates.rate("USD", "USDT") == Decimal(1)
    custom = CurrencyRates(rates=(("EUR", "USD", Decimal("1.10")),))
    assert custom.convert(Decimal(100), "USD", "EUR").quantize(Decimal("0.01")) == Decimal("90.91")
    with pytest.raises(CurrencyConversionError):
        rates.rate("JPY", "USD")
