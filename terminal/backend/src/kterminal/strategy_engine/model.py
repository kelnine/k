"""Small value types shared by the strategy SDK, the runner and hosts."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from kterminal.core.enums import Direction, OrderType
from kterminal.domain.signals import Signal

OppositeSignalPolicy = Literal["reverse", "ignore"]

OPEN_BEYOND_STOP = "OPEN_BEYOND_STOP"
OPEN_BEYOND_TARGET = "OPEN_BEYOND_TARGET"
"""Codes of a market entry skipped because the bar it would fill at opened at or beyond
its stop / target (:attr:`PositionRules.skip_entry_beyond_levels`)."""

NOTHING_TO_FLATTEN = "NOTHING_TO_FLATTEN"
"""Why a ``FLATTEN`` changed nothing: no position and no resting entry on the symbol."""


class PositionEventKind(StrEnum):
    OPENED = "OPENED"
    CLOSED = "CLOSED"
    STOP_MOVED = "STOP_MOVED"
    TARGET_MOVED = "TARGET_MOVED"
    ORDER_EXPIRED = "ORDER_EXPIRED"
    ORDER_CANCELLED = "ORDER_CANCELLED"  # e.g. a market entry skipped by the level guard


class CloseReason(StrEnum):
    TAKE_PROFIT = "TAKE_PROFIT"
    STOP_LOSS = "STOP_LOSS"
    SIGNAL_EXIT = "SIGNAL_EXIT"
    REVERSAL = "REVERSAL"
    SESSION_CLOSE = "SESSION_CLOSE"  # a time-based exit (EXIT signal with reason SESSION_CLOSE)


def exit_reason(signal: Signal) -> CloseReason:
    """The close reason an ``EXIT_*`` signal records: ``SESSION_CLOSE`` when its ``reason``
    is exactly that code (``ctx.exit_long(session_close=True)``), else ``SIGNAL_EXIT``.
    The theoretical book and every paper account use this one rule."""
    if signal.reason == CloseReason.SESSION_CLOSE:
        return CloseReason.SESSION_CLOSE
    return CloseReason.SIGNAL_EXIT


@dataclass(frozen=True, slots=True)
class PositionRules:
    """How an instance's signals become positions. The theoretical book and the
    instance's paper accounts apply the same rules, so they cannot drift apart.

    ``on_opposite_signal``
        ``reverse`` (default): an opposite entry closes the open position and enters;
        ``ignore``: it is refused while a position is open.
    ``skip_entry_beyond_levels``
        Skip a MARKET entry when the bar it would fill on *opens* at or beyond its stop
        or its target (``OPEN_BEYOND_STOP`` / ``OPEN_BEYOND_TARGET``): a signal priced
        at the signal bar's close keeps its levels, but is not filled once the market has
        already passed them (doc 13, D3).
    """

    on_opposite_signal: OppositeSignalPolicy = "reverse"
    skip_entry_beyond_levels: bool = False


def open_beyond_levels(
    direction: Direction, open_price: Decimal, stop: Decimal, target: Decimal | None
) -> str | None:
    """Why a market entry filling at ``open_price`` must be skipped, or None.

    At or beyond counts: a long whose bar opens at or below its stop, or at or above its
    target, is skipped (a short mirrors this)."""
    if direction is Direction.LONG:
        if open_price <= stop:
            return OPEN_BEYOND_STOP
        if target is not None and open_price >= target:
            return OPEN_BEYOND_TARGET
        return None
    if open_price >= stop:
        return OPEN_BEYOND_STOP
    if target is not None and open_price <= target:
        return OPEN_BEYOND_TARGET
    return None


@dataclass(frozen=True, slots=True)
class PositionView:
    """Read-only view of a strategy's *theoretical* position (as if every signal executed)."""

    instrument: str
    direction: Direction
    entry_price: Decimal
    entry_time: datetime
    stop_loss: Decimal
    take_profit: Decimal | None
    bars_held: int

    @property
    def is_long(self) -> bool:
        return self.direction is Direction.LONG

    @property
    def is_short(self) -> bool:
        return self.direction is Direction.SHORT

    def unrealized_r(self, price: Decimal) -> Decimal:
        """Open profit in R multiples at ``price`` (R = initial entry-to-stop distance)."""
        risk = abs(self.entry_price - self.stop_loss)
        if risk == 0:
            return Decimal(0)
        move = price - self.entry_price if self.is_long else self.entry_price - price
        return move / risk


@dataclass(frozen=True, slots=True)
class PendingEntryView:
    """Read-only view of the theoretical book's resting entry order (``ctx.pending_entry``).

    ``entry``, ``stop_loss`` and ``take_profit`` are the levels the order rests with (on
    the account's tick grid when the book resolves like the account). ``bars_waited``
    counts the primary bars it has rested through without filling."""

    instrument: str
    direction: Direction
    order_type: OrderType
    entry: Decimal | None
    stop_loss: Decimal
    take_profit: Decimal | None
    placed_at: datetime  # decision time of the signal that placed it
    bars_waited: int
    expires_after_bars: int | None
    signal: Signal

    @property
    def is_long(self) -> bool:
        return self.direction is Direction.LONG

    @property
    def is_short(self) -> bool:
        return self.direction is Direction.SHORT


@dataclass(frozen=True, slots=True)
class BookState:
    """The theoretical book of one instrument after a batch: what the lab compares with
    the instance's account (the per-run consistency report)."""

    instrument: str
    time: datetime  # close time of the batch
    position: PositionView | None
    pending_entry: PendingEntryView | None
    exiting: bool = False  # the position closes at the next open


@dataclass(frozen=True, slots=True)
class PositionEvent:
    kind: PositionEventKind
    instrument: str
    direction: Direction
    time: datetime
    price: Decimal | None = None
    reason: CloseReason | None = None
    signal: Signal | None = None  # the signal that caused it, if any
    detail: str | None = None  # machine-readable code, e.g. OPEN_BEYOND_STOP for ORDER_CANCELLED


@dataclass(frozen=True, slots=True)
class RejectedSignal:
    """A signal the framework refused (it violated the standard). Recorded, never routed."""

    instance_id: str
    instrument: str
    time: datetime
    code: str
    message: str
    payload: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Fault:
    """An exception raised by strategy code. The instance stops emitting signals."""

    instance_id: str
    instrument: str
    time: datetime | None
    stage: str  # on_start | on_bar | on_position_event | warmup | host
    error_type: str
    message: str
    traceback: str = ""


@dataclass(frozen=True, slots=True)
class RunnerOutput:
    """Everything one instance produced for one closed primary bar (or, when its book
    resolves on base bars, for a base bar that advanced the book: then only ``book``).

    ``book_reasons`` is aligned with ``signals``: why the theoretical book ignored each
    signal (``POSITION_EXISTS``, ``NO_MATCHING_POSITION``, ``NOTHING_TO_FLATTEN`` …) or
    None when it applied it. ``book`` is the book after the batch, when the runner
    resolves it like the account."""

    instance_id: str
    instrument: str
    time: datetime
    signals: tuple[Signal, ...] = ()
    rejected: tuple[RejectedSignal, ...] = ()
    events: tuple[PositionEvent, ...] = ()
    fault: Fault | None = None
    elapsed_ms: float = 0.0
    book_reasons: tuple[str | None, ...] = ()
    book: BookState | None = None

    def book_reason(self, index: int) -> str | None:
        """Why the book ignored ``signals[index]``, or None if it applied it."""
        return self.book_reasons[index] if index < len(self.book_reasons) else None
