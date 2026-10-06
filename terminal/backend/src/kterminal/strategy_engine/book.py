"""The theoretical book: a strategy's own view of its position.

It tracks the position a strategy *would* hold if every one of its signals
executed without costs, exactly like a Pine strategy's tester position. This
lets a strategy ask "am I in a trade?" (``ctx.position``) without knowing
anything about accounts. Real accounts may diverge — the risk engine can
reject an entry on one account — and they are tracked separately by the
execution layer.

Fill semantics (identical to Pine's defaults, so ports behave the same):

* signals are generated on a bar's close and fill at the **next bar's open**;
* LIMIT/STOP entries fill when the next bars trade through their price
  (gaps fill at the open) and expire after ``expires_after_bars``;
* stop-loss and take-profit are checked on every bar after entry, including
  the entry bar; when one bar touches both, the **stop is assumed first**
  (the conservative choice);
* a bar that gaps through a level fills at the open.
"""

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal

from kterminal.core.enums import Direction, OrderType, SignalAction
from kterminal.domain.market import Bar
from kterminal.domain.signals import Signal
from kterminal.strategy_engine.model import (
    CloseReason,
    PositionEvent,
    PositionEventKind,
    PositionView,
)


@dataclass(frozen=True, slots=True)
class _Pending:
    signal: Signal
    bars_waited: int = 0


class TheoreticalBook:
    def __init__(self, instrument: str, *, on_opposite_signal: str = "reverse") -> None:
        self.instrument = instrument
        self.on_opposite_signal = on_opposite_signal
        self._position: PositionView | None = None
        self._pending_entry: _Pending | None = None
        self._pending_exit: Signal | None = None

    @property
    def position(self) -> PositionView | None:
        return self._position

    @property
    def has_pending_entry(self) -> bool:
        return self._pending_entry is not None

    # ── signals (decided on a bar's close) ──────────────────────────────────
    def apply(self, signal: Signal) -> str | None:
        """Register a validated signal. Returns why it was ignored, or None if applied."""
        action = signal.signal
        position = self._position
        if action.is_entry:
            direction = _direction(signal)
            if position is not None and position.direction is direction:
                return "POSITION_EXISTS"
            if position is not None and self.on_opposite_signal == "ignore":
                return "OPPOSITE_POSITION_OPEN"
            if position is not None:  # reverse: close at next open, then enter
                self._pending_exit = signal
            self._pending_entry = _Pending(signal)
            return None
        if action.is_exit:
            if position is not None and position.direction is action.direction:
                self._pending_exit = signal
                return None
            pending = self._pending_entry
            if pending is not None and pending.signal.signal.direction is action.direction:
                self._pending_entry = None  # cancel the resting entry it refers to
                return None
            return "NO_MATCHING_POSITION"
        if action is SignalAction.MOVE_SL:
            if position is None:
                return "NO_POSITION"
            self._position = replace(
                position,
                stop_loss=_stop(signal),
                take_profit=signal.take_profit
                if signal.take_profit is not None
                else position.take_profit,
            )
            return None
        return None  # NO_TRADE

    # ── bars ────────────────────────────────────────────────────────────────
    def on_bar(self, bar: Bar) -> list[PositionEvent]:
        """Advance one closed bar: fill pending orders at its open, then check SL/TP."""
        if bar.instrument != self.instrument:
            raise ValueError(f"bar for {bar.instrument} sent to book of {self.instrument}")
        events: list[PositionEvent] = []
        exit_signal, position = self._pending_exit, self._position
        if exit_signal is not None and position is not None:
            reason = (
                CloseReason.REVERSAL if exit_signal.signal.is_entry else CloseReason.SIGNAL_EXIT
            )
            events.append(self._close(position, bar.open, bar.open_time, reason, exit_signal))
        self._pending_exit = None

        if self._pending_entry is not None and self._position is None:
            events.extend(self._try_fill_entry(self._pending_entry, bar))

        if self._position is not None:
            events.extend(self._check_exits(self._position, bar))
            if self._position is not None:
                self._position = replace(self._position, bars_held=self._position.bars_held + 1)
        return events

    def _try_fill_entry(self, pending: _Pending, bar: Bar) -> list[PositionEvent]:
        signal = pending.signal
        direction = _direction(signal)
        fill: Decimal | None
        if signal.order_type is OrderType.MARKET:
            fill = bar.open
        else:
            fill = _resting_fill(signal, direction, bar)
        if fill is None:
            waited = pending.bars_waited + 1
            if signal.expires_after_bars is not None and waited >= signal.expires_after_bars:
                self._pending_entry = None
                return [
                    PositionEvent(
                        PositionEventKind.ORDER_EXPIRED,
                        self.instrument,
                        direction,
                        bar.close_time,
                        signal=signal,
                    )
                ]
            self._pending_entry = _Pending(signal, waited)
            return []
        self._pending_entry = None
        self._position = PositionView(
            instrument=self.instrument,
            direction=direction,
            entry_price=fill,
            entry_time=bar.open_time,
            stop_loss=_stop(signal),
            take_profit=signal.take_profit,
            bars_held=0,
        )
        return [
            PositionEvent(
                PositionEventKind.OPENED,
                self.instrument,
                direction,
                bar.open_time,
                fill,
                signal=signal,
            )
        ]

    def _check_exits(self, position: PositionView, bar: Bar) -> list[PositionEvent]:
        stop, target = position.stop_loss, position.take_profit
        if position.is_long:
            if bar.low <= stop:
                price = min(bar.open, stop)
                return [self._close(position, price, bar.close_time, CloseReason.STOP_LOSS, None)]
            if target is not None and bar.high >= target:
                price = max(bar.open, target)
                return [self._close(position, price, bar.close_time, CloseReason.TAKE_PROFIT, None)]
        else:
            if bar.high >= stop:
                price = max(bar.open, stop)
                return [self._close(position, price, bar.close_time, CloseReason.STOP_LOSS, None)]
            if target is not None and bar.low <= target:
                price = min(bar.open, target)
                return [self._close(position, price, bar.close_time, CloseReason.TAKE_PROFIT, None)]
        return []

    def _close(
        self,
        position: PositionView,
        price: Decimal,
        at: datetime,
        reason: CloseReason,
        signal: Signal | None,
    ) -> PositionEvent:
        self._position = None
        return PositionEvent(
            PositionEventKind.CLOSED,
            self.instrument,
            position.direction,
            at,
            price,
            reason=reason,
            signal=signal,
        )


def _direction(signal: Signal) -> Direction:
    direction = signal.signal.direction
    if direction is None:
        raise ValueError(f"{signal.signal} has no direction")
    return direction


def _stop(signal: Signal) -> Decimal:
    if signal.stop_loss is None:
        raise ValueError(f"{signal.signal} signal without stop_loss reached the book")
    return signal.stop_loss


def _resting_fill(signal: Signal, direction: Direction, bar: Bar) -> Decimal | None:
    """Fill price of a LIMIT/STOP entry in ``bar``, or None if it did not trade."""
    price = signal.entry
    if price is None:
        raise ValueError("resting entry without a price reached the book")
    buy = direction is Direction.LONG
    if signal.order_type is OrderType.LIMIT:
        if buy and bar.low <= price:
            return min(bar.open, price)
        if not buy and bar.high >= price:
            return max(bar.open, price)
    else:  # STOP entry (breakout)
        if buy and bar.high >= price:
            return max(bar.open, price)
        if not buy and bar.low <= price:
            return min(bar.open, price)
    return None
