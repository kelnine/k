"""The theoretical book: a strategy's own view of its position.

It tracks the position a strategy *would* hold if every one of its signals
executed without costs, exactly like a Pine strategy's tester position. This
lets a strategy ask "am I in a trade?" (``ctx.position``) without knowing
anything about accounts. Real accounts may diverge — the risk engine can
reject an entry on one account — and they are tracked separately by the
execution layer.

Fill semantics (Pine's defaults, made conservative where a bar's path is
unknown — the paper accounts apply the same rules):

* signals are generated on a bar's close and fill at the **next bar's open**;
* LIMIT/STOP entries fill when the next bars trade through their price
  (gaps fill at the open) and expire after ``expires_after_bars`` primary bars;
* an opposite-direction MARKET entry reverses at the next open; an opposite
  LIMIT/STOP entry reverses only **when it fills** (one order, as in Pine);
* stop-loss and take-profit are checked on every bar after entry, including
  the entry bar. A bar that *opens* beyond the target fills it at the open;
  otherwise, when one bar touches both, the **stop is assumed first**. On the
  bar a resting entry fills inside the bar, only the close is known to come
  after the fill, so the target counts only if the bar closes beyond it;
* a bar that gaps through a stop fills at the open;
* ``MOVE_SL`` never widens risk (accounts refuse it too) and reports
  ``STOP_MOVED`` / ``TARGET_MOVED`` events on the next bar.
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
        self._events: list[PositionEvent] = []  # reported with the next bar

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
            if position is not None and signal.order_type is OrderType.MARKET:
                self._pending_exit = signal  # reverse: close at the next open, then enter
            # a resting (LIMIT/STOP) reversal closes the position only when it fills
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
            new_stop = _stop(signal)
            widens = (
                new_stop < position.stop_loss if position.is_long else new_stop > position.stop_loss
            )
            if widens:
                return "STOP_WIDENING_NOT_ALLOWED"
            new_target = (
                signal.take_profit if signal.take_profit is not None else position.take_profit
            )
            at = signal.timestamp
            if new_stop != position.stop_loss:
                self._events.append(
                    PositionEvent(
                        PositionEventKind.STOP_MOVED,
                        self.instrument,
                        position.direction,
                        at,
                        new_stop,
                        signal=signal,
                    )
                )
            if new_target != position.take_profit and new_target is not None:
                self._events.append(
                    PositionEvent(
                        PositionEventKind.TARGET_MOVED,
                        self.instrument,
                        position.direction,
                        at,
                        new_target,
                        signal=signal,
                    )
                )
            self._position = replace(position, stop_loss=new_stop, take_profit=new_target)
            return None
        return None  # NO_TRADE

    # ── bars ────────────────────────────────────────────────────────────────
    def on_bar(self, bar: Bar) -> list[PositionEvent]:
        """Advance one closed bar: fill pending orders at its open, then check SL/TP."""
        if bar.instrument != self.instrument:
            raise ValueError(f"bar for {bar.instrument} sent to book of {self.instrument}")
        events, self._events = self._events, []
        exit_signal, position = self._pending_exit, self._position
        if exit_signal is not None and position is not None:
            reason = (
                CloseReason.REVERSAL if exit_signal.signal.is_entry else CloseReason.SIGNAL_EXIT
            )
            events.append(self._close(position, bar.open, bar.open_time, reason, exit_signal))
        self._pending_exit = None

        if self._position is not None and self._pending_entry is not None:
            # a resting reversal is pending: the open position's own brackets come first
            events.extend(self._check_exits(self._position, bar, after_intrabar_fill=False))
        intrabar = False
        if self._pending_entry is not None:
            fill_events, intrabar = self._try_fill_entry(self._pending_entry, bar)
            events.extend(fill_events)
            if any(e.kind is PositionEventKind.OPENED for e in fill_events):
                position = self._position
                if position is not None:
                    events.extend(self._check_exits(position, bar, after_intrabar_fill=intrabar))
        elif self._position is not None:
            events.extend(self._check_exits(self._position, bar, after_intrabar_fill=False))
        if self._position is not None:
            self._position = replace(self._position, bars_held=self._position.bars_held + 1)
        return events

    def _try_fill_entry(self, pending: _Pending, bar: Bar) -> tuple[list[PositionEvent], bool]:
        """Fill (or expire) the pending entry on this bar. Returns the events and whether
        it filled *inside* the bar (rather than at its open)."""
        signal = pending.signal
        direction = _direction(signal)
        position = self._position
        if position is not None and position.direction is direction:
            self._pending_entry = None  # can't happen via apply(); never pyramid
            return [], False
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
                ], False
            self._pending_entry = _Pending(signal, waited)
            return [], False
        self._pending_entry = None
        events: list[PositionEvent] = []
        if position is not None:  # a resting reversal: one order closes and re-opens
            events.append(self._close(position, fill, bar.open_time, CloseReason.REVERSAL, signal))
        self._position = PositionView(
            instrument=self.instrument,
            direction=direction,
            entry_price=fill,
            entry_time=bar.open_time,
            stop_loss=_stop(signal),
            take_profit=signal.take_profit,
            bars_held=0,
        )
        events.append(
            PositionEvent(
                PositionEventKind.OPENED,
                self.instrument,
                direction,
                bar.open_time,
                fill,
                signal=signal,
            )
        )
        intrabar = signal.order_type is not OrderType.MARKET and fill != bar.open
        return events, intrabar

    def _check_exits(
        self, position: PositionView, bar: Bar, *, after_intrabar_fill: bool
    ) -> list[PositionEvent]:
        stop, target = position.stop_loss, position.take_profit
        long = position.is_long
        at = bar.close_time
        # the open is the bar's first price: beyond the target, the target fills there
        opened_beyond = target is not None and (
            (bar.open >= target) if long else (bar.open <= target)
        )
        if opened_beyond and not after_intrabar_fill:
            return [self._close(position, bar.open, at, CloseReason.TAKE_PROFIT, None)]
        if (bar.low <= stop) if long else (bar.high >= stop):  # stop first
            price = min(bar.open, stop) if long else max(bar.open, stop)
            return [self._close(position, price, at, CloseReason.STOP_LOSS, None)]
        if target is None:
            return []
        if after_intrabar_fill:  # only the close is known to come after the fill
            reached = (bar.close >= target) if long else (bar.close <= target)
        else:
            reached = (bar.high >= target) if long else (bar.low <= target)
        if reached:
            return [self._close(position, target, at, CloseReason.TAKE_PROFIT, None)]
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
