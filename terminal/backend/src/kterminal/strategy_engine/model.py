"""Small value types shared by the strategy SDK, the runner and hosts."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from kterminal.core.enums import Direction
from kterminal.domain.signals import Signal


class PositionEventKind(StrEnum):
    OPENED = "OPENED"
    CLOSED = "CLOSED"
    STOP_MOVED = "STOP_MOVED"
    TARGET_MOVED = "TARGET_MOVED"
    ORDER_EXPIRED = "ORDER_EXPIRED"


class CloseReason(StrEnum):
    TAKE_PROFIT = "TAKE_PROFIT"
    STOP_LOSS = "STOP_LOSS"
    SIGNAL_EXIT = "SIGNAL_EXIT"
    REVERSAL = "REVERSAL"


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
class PositionEvent:
    kind: PositionEventKind
    instrument: str
    direction: Direction
    time: datetime
    price: Decimal | None = None
    reason: CloseReason | None = None
    signal: Signal | None = None  # the signal that caused it, if any


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
    """Everything one instance produced for one closed primary bar."""

    instance_id: str
    instrument: str
    time: datetime
    signals: tuple[Signal, ...] = ()
    rejected: tuple[RejectedSignal, ...] = ()
    events: tuple[PositionEvent, ...] = ()
    fault: Fault | None = None
    elapsed_ms: float = 0.0
