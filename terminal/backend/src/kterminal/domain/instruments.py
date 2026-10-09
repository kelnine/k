"""Canonical instruments, venues and venue-specific listings.

Three layers, so nothing assumes that every market works the same way:

``Instrument``
    The canonical thing a strategy trades, e.g. ``XAUUSD``, ``NAS100``, ``MNQ``
    or ``NEARUSD``. It carries only venue-independent facts (asset class,
    quote currency, a canonical tick for rounding strategy prices, default
    trading hours and trading-day rule, and — for futures — the contract cycle).

``Venue``
    Where data, signals or orders go: an exchange (CME, Binance USD-M), a
    broker (OANDA), a prop-firm platform server (an MT5 or TradeLocker server),
    a data feed or signal source (TradingView), or the internal simulator.

``Listing``
    One instrument *as offered by one venue*: its symbol there and its own
    contract specification — tick size, contract size / multiplier, quantity
    unit and step, P&L currency, trading hours and cost profile. ``XAUUSD`` on
    a CFD server (100 oz per lot) and gold on another venue are different
    listings of the same canonical instrument.

All of this is configuration (``terminal/config/*.yaml``), never code.
"""

import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, ROUND_UP, Decimal
from enum import StrEnum

from kterminal.core.enums import Direction

SYMBOL_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,31}$")
ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
CURRENCY_PATTERN = re.compile(r"^[A-Z0-9]{2,10}$")


class AssetClass(StrEnum):
    FX = "FX"
    METAL = "METAL"
    INDEX = "INDEX"
    EQUITY = "EQUITY"
    COMMODITY = "COMMODITY"
    CRYPTO = "CRYPTO"
    RATES = "RATES"


class ContractType(StrEnum):
    SPOT = "SPOT"
    CFD = "CFD"
    FUTURE = "FUTURE"
    PERPETUAL = "PERPETUAL"
    INDEX_DATA = "INDEX_DATA"  # a data-only symbol (e.g. a cash index on TradingView); not tradable


class PnlModel(StrEnum):
    LINEAR = "LINEAR"  # P&L = Δprice × qty × contract_size, in the quote currency
    INVERSE = "INVERSE"  # coin-margined contracts; not supported for sizing yet


class QuantityUnit(StrEnum):
    LOTS = "LOTS"
    CONTRACTS = "CONTRACTS"
    BASE_UNITS = "BASE_UNITS"


class VenueKind(StrEnum):
    EXCHANGE = "EXCHANGE"
    BROKER = "BROKER"
    PROP_FIRM = "PROP_FIRM"
    DATA_FEED = "DATA_FEED"
    SIGNAL_SOURCE = "SIGNAL_SOURCE"
    SIMULATOR = "SIMULATOR"


class Platform(StrEnum):
    """Trading/connectivity platform behind a venue (one adapter per platform)."""

    MT5 = "MT5"
    MT4 = "MT4"
    TRADELOCKER = "TRADELOCKER"
    CTRADER = "CTRADER"
    DXTRADE = "DXTRADE"
    MATCH_TRADER = "MATCH_TRADER"
    TRADOVATE = "TRADOVATE"
    RITHMIC = "RITHMIC"
    PROJECTX = "PROJECTX"
    NINJATRADER = "NINJATRADER"
    INTERACTIVE_BROKERS = "INTERACTIVE_BROKERS"
    OANDA_V20 = "OANDA_V20"
    CME_GLOBEX = "CME_GLOBEX"
    BINANCE = "BINANCE"
    BYBIT = "BYBIT"
    OKX = "OKX"
    HYPERLIQUID = "HYPERLIQUID"
    COINBASE = "COINBASE"
    TRADINGVIEW = "TRADINGVIEW"
    INTERNAL = "INTERNAL"


# ── numeric helpers ──────────────────────────────────────────────────────────
def quantize_to_step(value: Decimal, step: Decimal, rounding: str = ROUND_HALF_EVEN) -> Decimal:
    """Round ``value`` to a multiple of ``step`` (a tick size or quantity step).

    The result carries the step's exponent, so 2678.4 on a 0.01 tick prints as
    ``2678.40`` and quantities never accumulate binary noise.
    """
    if step <= 0:
        raise ValueError(f"step must be positive, got {step}")
    units = (value / step).to_integral_value(rounding=rounding)
    return (units * step).quantize(step)


def round_price(value: Decimal, tick: Decimal, *, is_buy: bool | None = None) -> Decimal:
    """Round a price to the tick grid.

    With ``is_buy`` set, rounding is *adverse* (buys round up, sells round
    down) — used for simulated fills so rounding never flatters results.
    """
    if is_buy is None:
        return quantize_to_step(value, tick, ROUND_HALF_EVEN)
    return quantize_to_step(value, tick, ROUND_UP if is_buy else ROUND_DOWN)


# ── canonical instruments ────────────────────────────────────────────────────
MONTH_CODES = "FGHJKMNQUVXZ"  # Jan … Dec


@dataclass(frozen=True, slots=True)
class FuturesContract:
    root: str
    year: int
    month: int
    expiry: date
    roll_date: date

    @property
    def month_code(self) -> str:
        return MONTH_CODES[self.month - 1]

    def symbol(self, fmt: str) -> str:
        """Render a venue symbol. Tokens: {root} {code} {y1} {y2} {yyyy} {mm}.

        Examples for MNQ December 2026: ``{root}{code}{y1}`` → ``MNQZ6`` (CME
        Globex, Tradovate, Rithmic); ``{root}{code}{yyyy}`` → ``MNQZ2026``
        (TradingView).
        """
        return fmt.format(
            root=self.root,
            code=self.month_code,
            y1=str(self.year)[-1],
            y2=str(self.year)[-2:],
            yyyy=str(self.year),
            mm=f"{self.month:02d}",
        )


@dataclass(frozen=True, slots=True)
class FuturesSpec:
    """Contract cycle of an exchange-traded futures product."""

    root: str
    contract_months: str = "HMUZ"  # quarterly by default
    expiry_rule: str = "third_friday"
    roll_days_before_expiry: int = 8  # calendar days; equity-index convention

    def __post_init__(self) -> None:
        if not self.contract_months or any(c not in MONTH_CODES for c in self.contract_months):
            raise ValueError(f"invalid contract months {self.contract_months!r}")
        if self.expiry_rule != "third_friday":
            raise ValueError(f"unsupported expiry rule {self.expiry_rule!r}")
        if self.roll_days_before_expiry < 0:
            raise ValueError("roll_days_before_expiry must be >= 0")

    @property
    def months(self) -> tuple[int, ...]:
        return tuple(sorted(MONTH_CODES.index(c) + 1 for c in self.contract_months))

    def contract(self, year: int, month: int) -> FuturesContract:
        if month not in self.months:
            raise ValueError(f"{self.root} has no contract in month {month}")
        expiry = _third_friday(year, month)
        return FuturesContract(
            root=self.root,
            year=year,
            month=month,
            expiry=expiry,
            roll_date=expiry - timedelta(days=self.roll_days_before_expiry),
        )

    def front_contract(self, on: date) -> FuturesContract:
        """The contract to trade on ``on``: the nearest one whose roll date is still ahead."""
        year = on.year
        for _ in range(3):
            for month in self.months:
                candidate = self.contract(year, month)
                if on < candidate.roll_date:
                    return candidate
            year += 1
        raise ValueError(f"no {self.root} contract found after {on}")  # pragma: no cover


def _third_friday(year: int, month: int) -> date:
    first = date(year, month, 1)
    first_friday = first + timedelta(days=(4 - first.weekday()) % 7)
    return first_friday + timedelta(weeks=2)


@dataclass(frozen=True, slots=True)
class Instrument:
    symbol: str
    name: str
    asset_class: AssetClass
    base: str
    quote_currency: str
    tick_size: Decimal  # canonical rounding for strategy prices; venues may differ
    trading_hours: str  # default trading calendar id
    trading_day: str  # trading-day (rollover) rule id
    underlying: str = ""  # groups related instruments, e.g. NAS100 and MNQ → NASDAQ100
    futures: FuturesSpec | None = None
    description: str = ""
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not SYMBOL_PATTERN.fullmatch(self.symbol):
            raise ValueError(f"invalid canonical symbol {self.symbol!r}")
        if not CURRENCY_PATTERN.fullmatch(self.quote_currency):
            raise ValueError(f"invalid quote currency {self.quote_currency!r}")
        if self.tick_size <= 0:
            raise ValueError(f"{self.symbol}: tick_size must be positive")

    def round_price(self, price: Decimal) -> Decimal:
        return quantize_to_step(price, self.tick_size)


@dataclass(frozen=True, slots=True)
class Venue:
    id: str
    name: str
    kind: VenueKind
    platform: Platform | None = None
    timezone: str = "UTC"  # server / statement time zone (MT5 servers are often UTC+2/+3)
    symbol_suffixes: tuple[str, ...] = ()  # broker suffixes stripped when resolving (".r", "m")
    description: str = ""

    def __post_init__(self) -> None:
        if not ID_PATTERN.fullmatch(self.id):
            raise ValueError(f"invalid venue id {self.id!r}")


@dataclass(frozen=True, slots=True)
class Listing:
    """An instrument as specified by one venue. All money is in ``quote_currency``."""

    venue: str
    instrument: str
    venue_symbol: str
    contract_type: ContractType
    tick_size: Decimal
    contract_size: Decimal  # quote-ccy value of a 1.0 price move for 1.0 quantity
    quantity_unit: QuantityUnit
    min_qty: Decimal
    qty_step: Decimal
    quote_currency: str
    max_qty: Decimal | None = None
    min_notional: Decimal | None = None
    pnl_model: PnlModel = PnlModel.LINEAR
    trading_hours: str | None = None  # overrides the instrument's calendar
    cost_profile: str | None = None
    symbol_format: str | None = None  # futures: dated symbol template, see FuturesContract
    tradable: bool = True
    verified_on: date | None = None
    source: str = ""
    notes: str = ""
    aliases: tuple[str, ...] = ()  # other spellings of venue_symbol at this venue

    def __post_init__(self) -> None:
        for name in ("tick_size", "contract_size", "qty_step"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{self.key}: {name} must be positive")
        if self.min_qty <= 0:
            raise ValueError(f"{self.key}: min_qty must be positive")
        if self.max_qty is not None and self.max_qty < self.min_qty:
            raise ValueError(f"{self.key}: max_qty below min_qty")
        if self.contract_type is ContractType.INDEX_DATA and self.tradable:
            object.__setattr__(self, "tradable", False)

    @property
    def key(self) -> str:
        return f"{self.venue}:{self.instrument}"

    # ── rounding ────────────────────────────────────────────────────────────
    def round_price(self, price: Decimal, *, is_buy: bool | None = None) -> Decimal:
        return round_price(price, self.tick_size, is_buy=is_buy)

    def round_qty_down(self, qty: Decimal) -> Decimal:
        """Quantities are always rounded *down*, so sizing never exceeds the risk budget."""
        return quantize_to_step(qty, self.qty_step, ROUND_DOWN)

    # ── money ───────────────────────────────────────────────────────────────
    def _require_linear(self) -> None:
        if self.pnl_model is not PnlModel.LINEAR:
            raise NotImplementedError(f"{self.key}: {self.pnl_model} P&L is not supported yet")

    @property
    def point_value(self) -> Decimal:
        """Quote-currency P&L of a 1.0 price move on 1.0 quantity."""
        self._require_linear()
        return self.contract_size

    @property
    def tick_value(self) -> Decimal:
        return self.tick_size * self.point_value

    def pnl(self, direction: Direction, qty: Decimal, entry: Decimal, exit_: Decimal) -> Decimal:
        sign = 1 if direction is Direction.LONG else -1
        return (exit_ - entry) * sign * qty * self.point_value

    def notional(self, qty: Decimal, price: Decimal) -> Decimal:
        return qty * price * self.point_value

    def venue_symbol_for(self, instrument: Instrument, on: date) -> str:
        """Symbol to use at this venue on ``on`` (resolves dated futures contracts)."""
        if instrument.futures is None or self.symbol_format is None:
            return self.venue_symbol
        return instrument.futures.front_contract(on).symbol(self.symbol_format)


class CurrencyConversionError(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class CurrencyRates:
    """Static conversion rates (``(from, to) → rate``). Stablecoins default to 1 USD.

    Treating USDT/USDC as exactly 1 USD is a configurable assumption, not a
    fact; it is recorded with every account configuration.
    """

    rates: tuple[tuple[str, str, Decimal], ...] = (
        ("USDT", "USD", Decimal(1)),
        ("USDC", "USD", Decimal(1)),
    )

    def rate(self, from_ccy: str, to_ccy: str) -> Decimal:
        if from_ccy == to_ccy:
            return Decimal(1)
        for src, dst, value in self.rates:
            if (src, dst) == (from_ccy, to_ccy):
                return value
            if (src, dst) == (to_ccy, from_ccy):
                return Decimal(1) / value
        raise CurrencyConversionError(f"no conversion rate {from_ccy} → {to_ccy}")

    def convert(self, amount: Decimal, from_ccy: str, to_ccy: str) -> Decimal:
        return amount * self.rate(from_ccy, to_ccy)
