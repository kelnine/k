"""The theoretical book: a strategy's own view of its position.

It tracks the position a strategy *would* hold if every one of its signals
executed, exactly like a Pine strategy's tester position. This lets a strategy
ask "am I in a trade?" (``ctx.position``) or "is my order still resting?"
(``ctx.pending_entry``) without knowing anything about accounts.

In the lab the book resolves orders **like the instance's paper account**: on the
same base (1-minute) bars, with the account's bid/ask, slippage and tick rounding
(:class:`~kterminal.strategy_engine.fills.BookExecution`), and it refuses an entry the
account would refuse for venue reasons (listing not tradable, market closed, stop or
target not beyond the price). Both call the rules in
:mod:`~kterminal.strategy_engine.fills`, so ``ctx.position`` matches the account unless
the account refused something for risk reasons (sizing, limits, kill switch). Without
an execution model (golden tests) the book trades at the mid prices of the primary bars,
without costs or rounding.

Fill semantics (Pine's defaults, made conservative where a bar's path is
unknown):

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
  ``STOP_MOVED`` / ``TARGET_MOVED`` events on the next bar — only for a level
  that actually changes;
* **replace**: an ``EXIT_*`` followed, on the same bar, by a new entry (in either
  direction) closes the position at the next open and enters at that same open —
  a position with a pending exit counts as flat for the entry;
* an exit whose ``reason`` is ``SESSION_CLOSE`` closes with that reason
  (:func:`~kterminal.strategy_engine.model.exit_reason`);
* ``FLATTEN`` closes the position, whatever its direction, at the next open and
  cancels the resting entry; with neither it changes nothing (``NOTHING_TO_FLATTEN``);
* with ``skip_entry_beyond_levels`` a MARKET entry is skipped (``ORDER_CANCELLED``,
  ``OPEN_BEYOND_STOP`` / ``OPEN_BEYOND_TARGET``) when the bar it would fill on opens
  at or beyond its stop or target.

Events of the base bars inside a primary bar are reported to the strategy when that
primary bar closes (:class:`~kterminal.strategy_engine.runner.StrategyRunner`).
"""

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal

from kterminal.core.enums import Direction, OrderSide, OrderType, SignalAction
from kterminal.domain.market import Bar
from kterminal.domain.signals import Signal
from kterminal.strategy_engine.fills import (
    BookExecution,
    MidPrices,
    PriceModel,
    bracket_exit,
    levels_on_grid,
    levels_problem,
    resting_entry_fill,
)
from kterminal.strategy_engine.model import (
    NOTHING_TO_FLATTEN,
    BookState,
    CloseReason,
    OppositeSignalPolicy,
    PendingEntryView,
    PositionEvent,
    PositionEventKind,
    PositionView,
    exit_reason,
    open_beyond_levels,
)


@dataclass(frozen=True, slots=True)
class _Pending:
    signal: Signal  # as the strategy sent it (events carry this one)
    levels: Signal  # the same order with its levels on the tick grid (what trades)
    bars_waited: int = 0


class TheoreticalBook:
    def __init__(
        self,
        instrument: str,
        *,
        on_opposite_signal: OppositeSignalPolicy = "reverse",
        skip_entry_beyond_levels: bool = False,
        execution: BookExecution | None = None,
    ) -> None:
        self.instrument = instrument
        self.on_opposite_signal = on_opposite_signal
        self.skip_entry_beyond_levels = skip_entry_beyond_levels
        self.execution = execution
        self.prices: PriceModel = execution.prices if execution is not None else MidPrices()
        self._position: PositionView | None = None
        self._pending_entry: _Pending | None = None
        self._pending_exit: Signal | None = None
        self._mark: Decimal | None = None  # close of the latest bar (market entries' price)
        self._events: list[PositionEvent] = []  # reported with the next bar

    @property
    def position(self) -> PositionView | None:
        return self._position

    @property
    def has_pending_entry(self) -> bool:
        return self._pending_entry is not None

    @property
    def pending_entry(self) -> PendingEntryView | None:
        """The resting (or not yet filled market) entry order, or None."""
        pending = self._pending_entry
        if pending is None:
            return None
        levels = pending.levels
        return PendingEntryView(
            instrument=self.instrument,
            direction=_direction(levels),
            order_type=levels.order_type,
            entry=levels.entry,
            stop_loss=_stop(levels),
            take_profit=levels.take_profit,
            placed_at=pending.signal.timestamp,
            bars_waited=pending.bars_waited,
            expires_after_bars=levels.expires_after_bars,
            signal=pending.signal,
        )

    def state(self, at: datetime) -> BookState:
        """The book after the batch closing at ``at`` (for the consistency report)."""
        return BookState(
            instrument=self.instrument,
            time=at,
            position=self._position,
            pending_entry=self.pending_entry,
            exiting=self._position is not None and self._pending_exit is not None,
        )

    # ── signals (decided on a bar's close) ──────────────────────────────────
    def apply(self, signal: Signal) -> str | None:
        """Register a validated signal. Returns why it changed nothing, or None if applied."""
        action = signal.signal
        position = self._position
        if action.is_entry:
            direction = _direction(signal)
            # replace: a position already exiting at the next open counts as flat
            holding = position is not None and self._pending_exit is None
            if holding and position is not None and position.direction is direction:
                return "POSITION_EXISTS"
            if holding and self.on_opposite_signal == "ignore":
                return "OPPOSITE_POSITION_OPEN"
            levels = levels_on_grid(self.prices, signal)
            refusal = self._venue_refusal(levels)
            # reverse = exit, then enter: a MARKET reversal exits at the next open even when
            # the entry itself is refused (as the account does); a resting (LIMIT/STOP)
            # reversal closes the position only when it fills
            reverse_now = holding and signal.order_type is OrderType.MARKET
            if reverse_now:
                self._pending_exit = signal
            if refusal is not None:
                return None if reverse_now else refusal
            self._pending_entry = _Pending(signal, levels)
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
        if action.is_flatten:
            if position is None and self._pending_entry is None:
                return NOTHING_TO_FLATTEN
            self._pending_entry = None  # cancel the resting entry, whatever its direction
            if position is not None:
                self._pending_exit = signal  # close at the next open, whatever the direction
            return None
        if action is SignalAction.MOVE_SL:
            if position is None:
                return "NO_POSITION"
            exit_is_buy = position.direction.exit_side is OrderSide.BUY
            new_stop = self.prices.round_level(_stop(signal), is_buy=exit_is_buy)
            widens = (
                new_stop < position.stop_loss if position.is_long else new_stop > position.stop_loss
            )
            if widens:
                return "STOP_WIDENING_NOT_ALLOWED"
            new_target = (
                self.prices.round_level(signal.take_profit, is_buy=exit_is_buy)
                if signal.take_profit is not None
                else position.take_profit
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

    def _venue_refusal(self, levels: Signal) -> str | None:
        """Why the instance's account would refuse this entry whatever its balance: the
        listing is data-only, the market is closed at the decision, or the stop/target is
        not beyond the price it is placed at. None without an execution model."""
        execution = self.execution
        if execution is None:
            return None
        if not execution.tradable:
            return "NOT_TRADABLE"
        if execution.calendar is not None and not execution.calendar.is_open(levels.timestamp):
            return "MARKET_CLOSED"
        market = levels.order_type is OrderType.MARKET
        reference = self._mark if market and self._mark is not None else levels.entry
        if reference is None:  # pragma: no cover - validated entries carry a price
            raise ValueError("entry without a price reached the book")
        problem = levels_problem(_direction(levels), reference, _stop(levels), levels.take_profit)
        return problem[0] if problem is not None else None

    # ── bars ────────────────────────────────────────────────────────────────
    def on_bar(self, bar: Bar) -> list[PositionEvent]:
        """Advance one closed bar that is both the base and the primary bar: fill pending
        orders at its open, check SL/TP, then end the bar (expiry, bars held)."""
        return [*self.on_base_bar(bar), *self.end_bar(bar.close_time)]

    def on_base_bar(self, bar: Bar) -> list[PositionEvent]:
        """Resolve one base bar: pending exits and entries fill at its open, then the
        brackets are checked — in the order the paper account processes the same bar."""
        if bar.instrument != self.instrument:
            raise ValueError(f"bar for {bar.instrument} sent to book of {self.instrument}")
        events, self._events = self._events, []
        exit_signal, position = self._pending_exit, self._position
        if exit_signal is not None and position is not None:
            reason = (
                CloseReason.REVERSAL if exit_signal.signal.is_entry else exit_reason(exit_signal)
            )
            fill = self.prices.market(position.direction.exit_side, bar.open, bar.open_time)
            events.append(self._close(position, fill.price, bar.open_time, reason, exit_signal))
        self._pending_exit = None

        if self._position is not None and self._pending_entry is not None:
            # a resting reversal is pending: the open position's own brackets come first
            events.extend(self._check_exits(self._position, bar, after_intrabar_fill=False))
        if self._pending_entry is not None:
            fill_events, intrabar = self._try_fill_entry(self._pending_entry, bar)
            events.extend(fill_events)
            if any(e.kind is PositionEventKind.OPENED for e in fill_events):
                position = self._position
                if position is not None:
                    events.extend(self._check_exits(position, bar, after_intrabar_fill=intrabar))
        elif self._position is not None:
            events.extend(self._check_exits(self._position, bar, after_intrabar_fill=False))
        self._mark = bar.close
        return events

    def end_bar(self, at: datetime) -> list[PositionEvent]:
        """A primary bar closed at ``at``: a resting entry that did not fill has waited one
        more bar (and expires after ``expires_after_bars``); the position is one bar older.
        The account drops an expired order before the next base bar can fill it."""
        events: list[PositionEvent] = []
        pending = self._pending_entry
        if pending is not None:
            waited = pending.bars_waited + 1
            expires = pending.signal.expires_after_bars
            if expires is not None and waited >= expires:
                self._pending_entry = None
                events.append(
                    PositionEvent(
                        PositionEventKind.ORDER_EXPIRED,
                        self.instrument,
                        _direction(pending.signal),
                        at,
                        signal=pending.signal,
                    )
                )
            else:
                self._pending_entry = replace(pending, bars_waited=waited)
        if self._position is not None:
            self._position = replace(self._position, bars_held=self._position.bars_held + 1)
        return events

    def _try_fill_entry(self, pending: _Pending, bar: Bar) -> tuple[list[PositionEvent], bool]:
        """Fill the pending entry on this bar if it trades. Returns the events and whether
        it filled *inside* the bar (rather than at its open)."""
        signal, levels = pending.signal, pending.levels
        direction = _direction(signal)
        position = self._position
        if position is not None and position.direction is direction:
            self._pending_entry = None  # can't happen via apply(); never pyramid
            return [], False
        side = direction.entry_side
        if levels.order_type is OrderType.MARKET:
            skip = (
                open_beyond_levels(direction, bar.open, _stop(levels), levels.take_profit)
                if self.skip_entry_beyond_levels
                else None
            )
            if skip is not None:
                self._pending_entry = None
                return [
                    PositionEvent(
                        PositionEventKind.ORDER_CANCELLED,
                        self.instrument,
                        direction,
                        bar.open_time,
                        bar.open,
                        signal=signal,
                        detail=skip,
                    )
                ], False
            fill = self.prices.market(side, bar.open, bar.open_time)
        else:
            if levels.entry is None:
                raise ValueError("resting entry without a price reached the book")
            resting = resting_entry_fill(self.prices, levels.order_type, side, levels.entry, bar)
            if resting is None:
                return [], False
            fill = resting
        self._pending_entry = None
        events: list[PositionEvent] = []
        if position is not None:  # a resting reversal: one order closes and re-opens
            events.append(
                self._close(position, fill.price, bar.open_time, CloseReason.REVERSAL, signal)
            )
        self._position = PositionView(
            instrument=self.instrument,
            direction=direction,
            entry_price=fill.price,
            entry_time=bar.open_time,
            stop_loss=_stop(levels),
            take_profit=levels.take_profit,
            bars_held=0,
        )
        events.append(
            PositionEvent(
                PositionEventKind.OPENED,
                self.instrument,
                direction,
                bar.open_time,
                fill.price,
                signal=signal,
            )
        )
        return events, fill.intrabar

    def _check_exits(
        self, position: PositionView, bar: Bar, *, after_intrabar_fill: bool
    ) -> list[PositionEvent]:
        hit = bracket_exit(
            self.prices,
            position.direction,
            position.stop_loss,
            position.take_profit,
            bar,
            after_intrabar_fill=after_intrabar_fill,
        )
        if hit is None:
            return []
        kind, fill = hit
        reason = CloseReason.TAKE_PROFIT if kind == "TAKE_PROFIT" else CloseReason.STOP_LOSS
        return [self._close(position, fill.price, bar.close_time, reason, None)]

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
