"""How orders resolve on a bar: one set of rules for the theoretical book and the accounts.

Bars are mid prices. A :class:`PriceModel` says where the bid and the ask are and how a
price lands on the tick grid:

* :class:`VenuePrices` reads them from the instance's cost model — the spread, the
  slippage and the listing's tick its paper account trades with;
* :class:`MidPrices` trades at the mid without costs or rounding — the theoretical book
  of a strategy run without a venue (golden tests, ``run_strategy``).

The functions below decide entry fills, stops and targets from a model and a bar. The
theoretical book (:class:`~kterminal.strategy_engine.book.TheoreticalBook`) and the paper
accounts (``kterminal.paper.account``) both call them, so with the same model and the
same base bars a strategy's ``ctx.position`` resolves exactly like its account:

* a market order fills at the bar's open, half the spread plus slippage against the
  trader, rounded adversely to the tick;
* a long's stop triggers when the bid reaches it and its target when the bid reaches it
  (a short: the ask); a bar that gaps through a stop fills at the (worse) open;
* a bar that *opens* beyond the target fills it at the open; otherwise, when one bar
  reaches both, the stop is assumed first;
* a resting LIMIT entry fills at its price once the far side of the spread reaches it —
  at the open when the bar opens through it — and a STOP entry like a stop;
* on the bar a resting entry fills *inside* the bar, the target counts only if the bar
  closes beyond it (its high/low may have come before the fill);
* signal levels go on the listing's tick grid, rounded against the trader.

Every function runs in the private exact decimal context, whatever the caller's is.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol

from kterminal.core.decimals import exact
from kterminal.core.enums import Direction, OrderSide, OrderType
from kterminal.domain.costs import CostCalculator, Liquidity
from kterminal.domain.instruments import Listing
from kterminal.domain.market import Bar
from kterminal.domain.sessions import TradingCalendar
from kterminal.domain.signals import Signal
from kterminal.domain.timeframes import Timeframe

ZERO = Decimal(0)

BracketKind = Literal["TAKE_PROFIT", "STOP_LOSS"]


@dataclass(frozen=True, slots=True)
class Fill:
    """A simulated fill and how it was reached (price units, all >= 0)."""

    price: Decimal
    half_spread: Decimal = ZERO  # recorded as a spread cost
    slippage: Decimal = ZERO
    liquidity: Liquidity = Liquidity.TAKER
    intrabar: bool = False  # an entry that filled inside the bar rather than at its open


class PriceModel(Protocol):
    """Where the bid and the ask are on a mid-price bar, and the tick grid."""

    def market(self, side: OrderSide, mid: Decimal, at: datetime) -> Fill:
        """A market order at ``mid``: spread, slippage, adverse rounding."""
        ...

    def stop_triggered(self, side: OrderSide, level: Decimal, bar: Bar) -> bool:
        """Whether a stop (a SELL stop on the bid, a BUY stop on the ask) triggers."""
        ...

    def stop_fill(self, side: OrderSide, level: Decimal, bar: Bar) -> Fill:
        """The fill of a stop that triggered in ``bar`` (at the open after a gap)."""
        ...

    def limit_triggered(
        self, side: OrderSide, level: Decimal, high: Decimal, low: Decimal, at: datetime
    ) -> bool:
        """Whether a limit (a SELL on the bid, a BUY on the ask) trades within high/low."""
        ...

    def opening(self, side: OrderSide, bar: Bar) -> Decimal:
        """The price an order of ``side`` could trade at the bar's open, on the grid."""
        ...

    def round_level(self, price: Decimal, *, is_buy: bool) -> Decimal:
        """A signal level on the tick grid, rounded against the trader."""
        ...


@dataclass(frozen=True, slots=True)
class MidPrices:
    """No spread, no slippage, no rounding: orders trade at the mid-price bar's prices."""

    def market(self, side: OrderSide, mid: Decimal, at: datetime) -> Fill:
        return Fill(mid)

    def stop_triggered(self, side: OrderSide, level: Decimal, bar: Bar) -> bool:
        return bar.low <= level if side is OrderSide.SELL else bar.high >= level

    def stop_fill(self, side: OrderSide, level: Decimal, bar: Bar) -> Fill:
        price = min(bar.open, level) if side is OrderSide.SELL else max(bar.open, level)
        return Fill(price, intrabar=price != bar.open)

    def limit_triggered(
        self, side: OrderSide, level: Decimal, high: Decimal, low: Decimal, at: datetime
    ) -> bool:
        return high >= level if side is OrderSide.SELL else low <= level

    def opening(self, side: OrderSide, bar: Bar) -> Decimal:
        return bar.open

    def round_level(self, price: Decimal, *, is_buy: bool) -> Decimal:
        return price


@dataclass(frozen=True, slots=True)
class VenuePrices:
    """The bid/ask and slippage of one listing's cost model; levels and opening prices on
    the listing's tick grid (market and stop fills round on the cost model's listing,
    which is the same listing in every catalog-built setup)."""

    costs: CostCalculator
    listing: Listing

    def market(self, side: OrderSide, mid: Decimal, at: datetime) -> Fill:
        fill = self.costs.market_fill(side, mid, at)
        return Fill(fill.price, fill.half_spread, fill.slippage)

    def stop_triggered(self, side: OrderSide, level: Decimal, bar: Bar) -> bool:
        return self.costs.stop_triggered(side, level, bar.high, bar.low, bar.open_time)

    def stop_fill(self, side: OrderSide, level: Decimal, bar: Bar) -> Fill:
        fill = self.costs.triggered_stop_fill(side, level, bar.open, bar.open_time)
        return Fill(
            fill.price, fill.half_spread, fill.slippage, intrabar=fill.reference != bar.open
        )

    def limit_triggered(
        self, side: OrderSide, level: Decimal, high: Decimal, low: Decimal, at: datetime
    ) -> bool:
        return self.costs.limit_triggered(side, level, high, low, at)

    @exact
    def opening(self, side: OrderSide, bar: Bar) -> Decimal:
        half = self.costs.spread(bar.open_time) / 2
        listing = self.listing
        if side is OrderSide.BUY:
            return listing.round_price(bar.open + half, is_buy=True)
        return listing.round_price(bar.open - half, is_buy=False)

    def round_level(self, price: Decimal, *, is_buy: bool) -> Decimal:
        return self.listing.round_price(price, is_buy=is_buy)


@dataclass(frozen=True, slots=True)
class BookExecution:
    """What a theoretical book needs to resolve orders like its instance's account: the
    account's prices for the instrument, the base timeframe its bars come in, and the
    venue conditions an order needs (the listing is tradable, the market is open).

    Plain, picklable data: the subprocess host sends it to the strategy's process.
    """

    prices: PriceModel
    base_timeframe: Timeframe
    calendar: TradingCalendar | None = None
    tradable: bool = True


# ── the rules ────────────────────────────────────────────────────────────────
@exact
def resting_entry_fill(
    prices: PriceModel, order_type: OrderType, side: OrderSide, level: Decimal, bar: Bar
) -> Fill | None:
    """The fill of a resting LIMIT/STOP entry at ``level`` in ``bar``, or None.

    A LIMIT fills at its price (maker) once the far side of the spread reaches it; a bar
    that opens through it fills at the opening bid/ask (taker). A STOP entry triggers
    and fills like a stop."""
    if order_type is OrderType.LIMIT:
        if not prices.limit_triggered(side, level, bar.high, bar.low, bar.open_time):
            return None
        opening = prices.opening(side, bar)
        if (opening <= level) if side is OrderSide.BUY else (opening >= level):
            return Fill(opening)  # opened through the limit: filled at the open
        return Fill(level, liquidity=Liquidity.MAKER, intrabar=True)
    if order_type is OrderType.STOP:
        if not prices.stop_triggered(side, level, bar):
            return None
        return prices.stop_fill(side, level, bar)
    raise ValueError(f"{order_type} is not a resting order type")


@exact
def bracket_exit(
    prices: PriceModel,
    direction: Direction,
    stop: Decimal,
    target: Decimal | None,
    bar: Bar,
    *,
    after_intrabar_fill: bool = False,
) -> tuple[BracketKind, Fill] | None:
    """Whether the position's stop or target closes it in ``bar``, and how.

    The open is the bar's first price: a bar that opens beyond the target fills it at
    the open. Otherwise the stop is checked first (when one bar reaches both, the stop is
    assumed). On the bar a resting entry filled inside, only the close is known to come
    after the fill: the target counts only if the bar closes beyond it."""
    side = direction.exit_side
    if target is not None and not after_intrabar_fill:
        opening = prices.opening(side, bar)
        if (opening >= target) if side is OrderSide.SELL else (opening <= target):
            return "TAKE_PROFIT", Fill(opening)
    if prices.stop_triggered(side, stop, bar):
        return "STOP_LOSS", prices.stop_fill(side, stop, bar)
    if target is None:
        return None
    if after_intrabar_fill:
        reached = prices.limit_triggered(side, target, bar.close, bar.close, bar.open_time)
    else:
        reached = prices.limit_triggered(side, target, bar.high, bar.low, bar.open_time)
    if reached:
        return "TAKE_PROFIT", Fill(target, liquidity=Liquidity.MAKER)
    return None


def levels_on_grid(prices: PriceModel, signal: Signal) -> Signal:
    """The entry signal's levels on the tick grid, rounded against the trader: a resting
    entry's price as the entry order's side, the stop and target as the exit order's."""
    direction = signal.signal.direction
    if direction is None:
        raise ValueError(f"{signal.signal} has no direction")
    entry_is_buy = direction.entry_side is OrderSide.BUY
    exit_is_buy = not entry_is_buy
    update: dict[str, Decimal | None] = {}
    if signal.order_type is not OrderType.MARKET and signal.entry is not None:
        update["entry"] = prices.round_level(signal.entry, is_buy=entry_is_buy)
    if signal.stop_loss is not None:
        update["stop_loss"] = prices.round_level(signal.stop_loss, is_buy=exit_is_buy)
    if signal.take_profit is not None:
        update["take_profit"] = prices.round_level(signal.take_profit, is_buy=exit_is_buy)
    changed = {k: v for k, v in update.items() if v != getattr(signal, k)}
    return signal.model_copy(update=changed) if changed else signal


def levels_problem(
    direction: Direction, reference: Decimal, stop: Decimal, target: Decimal | None
) -> tuple[str, str] | None:
    """Why stop and target are not on their sides of the price an entry is placed at
    (``STOP_WRONG_SIDE`` / ``TARGET_WRONG_SIDE`` and a message), or None."""
    long = direction is Direction.LONG
    if (stop >= reference) if long else (stop <= reference):
        return "STOP_WRONG_SIDE", f"stop {stop} is not beyond the entry price {reference}"
    if target is not None and ((target <= reference) if long else (target >= reference)):
        return "TARGET_WRONG_SIDE", f"target {target} is not beyond the entry price {reference}"
    return None


__all__ = [
    "BookExecution",
    "BracketKind",
    "Fill",
    "MidPrices",
    "PriceModel",
    "VenuePrices",
    "bracket_exit",
    "levels_on_grid",
    "levels_problem",
    "resting_entry_fill",
]
