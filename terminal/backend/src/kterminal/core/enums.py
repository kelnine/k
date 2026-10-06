"""Shared vocabulary used by every module.

Values are upper-case strings so they serialize unchanged into JSON, the
database (``text`` + ``CHECK`` constraints) and TradingView payloads.
"""

from enum import StrEnum


class TradingMode(StrEnum):
    """How orders for an account are executed.

    ``LIVE`` is the only mode that risks real money. It is never a default and
    is gated by several independent interlocks (see ``kterminal.config``).
    """

    BACKTEST = "BACKTEST"
    PAPER = "PAPER"
    DEMO = "DEMO"
    LIVE = "LIVE"

    @property
    def uses_broker_api(self) -> bool:
        """True when orders go to an external broker (demo or live environment)."""
        return self in (TradingMode.DEMO, TradingMode.LIVE)

    @property
    def risks_real_money(self) -> bool:
        return self is TradingMode.LIVE


class Direction(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"

    @property
    def opposite(self) -> "Direction":
        return Direction.SHORT if self is Direction.LONG else Direction.LONG

    @property
    def entry_side(self) -> "OrderSide":
        """The order side that opens a position in this direction."""
        return OrderSide.BUY if self is Direction.LONG else OrderSide.SELL

    @property
    def exit_side(self) -> "OrderSide":
        """The order side that closes a position in this direction."""
        return self.entry_side.opposite


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"

    @property
    def opposite(self) -> "OrderSide":
        return OrderSide.SELL if self is OrderSide.BUY else OrderSide.BUY


class SignalAction(StrEnum):
    """The standardized set of signals a strategy may emit."""

    LONG = "LONG"
    SHORT = "SHORT"
    EXIT_LONG = "EXIT_LONG"
    EXIT_SHORT = "EXIT_SHORT"
    MOVE_SL = "MOVE_SL"
    NO_TRADE = "NO_TRADE"

    @property
    def is_entry(self) -> bool:
        """Opens (increases) risk — must pass the risk engine."""
        return self in (SignalAction.LONG, SignalAction.SHORT)

    @property
    def is_exit(self) -> bool:
        """Reduces risk — always permitted."""
        return self in (SignalAction.EXIT_LONG, SignalAction.EXIT_SHORT)

    @property
    def direction(self) -> Direction | None:
        """Direction of the position this signal opens or closes, if any."""
        if self in (SignalAction.LONG, SignalAction.EXIT_LONG):
            return Direction.LONG
        if self in (SignalAction.SHORT, SignalAction.EXIT_SHORT):
            return Direction.SHORT
        return None


class SignalSource(StrEnum):
    INTERNAL = "INTERNAL"  # a Python strategy plug-in run by the strategy engine
    TRADINGVIEW = "TRADINGVIEW"  # received through the webhook
    MANUAL = "MANUAL"  # entered by an operator
    REPLAY = "REPLAY"  # recorded signals replayed in a backtest


class StrategyKind(StrEnum):
    INTERNAL = "INTERNAL"  # logic runs inside the terminal
    EXTERNAL = "EXTERNAL"  # logic runs elsewhere (TradingView); signals arrive by webhook


class StrategyStatus(StrEnum):
    """Promotion pipeline; each step is gated by recorded evidence."""

    DRAFT = "DRAFT"
    BACKTESTED = "BACKTESTED"
    PAPER = "PAPER"
    DEMO = "DEMO"
    LIVE_APPROVED = "LIVE_APPROVED"
    RETIRED = "RETIRED"
