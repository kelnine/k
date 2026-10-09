from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from kterminal.core.enums import Direction, OrderType, SignalAction
from kterminal.domain.signals import Signal
from kterminal.strategy_engine.book import TheoreticalBook
from kterminal.strategy_engine.model import CloseReason, PositionEventKind
from tests.fixtures.instruments import bars

T = datetime(2026, 1, 5, tzinfo=UTC)


def sig(action: SignalAction, **kw: Any) -> Signal:
    base: dict[str, Any] = {
        "strategy_id": "s",
        "strategy_version": "v",
        "symbol": "XAUUSD",
        "timeframe": "5m",
        "timestamp": T,
        "signal": action,
    }
    base.update(kw)
    return Signal(**base)


def long_signal(
    entry: float = 100, stop: float = 95, target: float | None = 110, **kw: Any
) -> Signal:
    return sig(
        SignalAction.LONG,
        entry=Decimal(str(entry)),
        stop_loss=Decimal(str(stop)),
        take_profit=Decimal(str(target)) if target is not None else None,
        **kw,
    )


def test_market_entry_fills_at_next_open_then_take_profit() -> None:
    book = TheoreticalBook("XAUUSD")
    assert book.apply(long_signal()) is None
    b = bars("XAUUSD", "5m", [(101, 104, 100, 103), (103, 111, 102, 110)])
    events = book.on_bar(b[0])
    assert [e.kind for e in events] == [PositionEventKind.OPENED]
    assert events[0].price == Decimal(101)
    assert book.position is not None and book.position.bars_held == 1
    events = book.on_bar(b[1])
    assert events[0].kind is PositionEventKind.CLOSED
    assert events[0].reason is CloseReason.TAKE_PROFIT
    assert events[0].price == Decimal(110)
    assert book.position is None


def test_stop_assumed_first_when_bar_touches_both() -> None:
    book = TheoreticalBook("XAUUSD")
    book.apply(long_signal())
    b = bars("XAUUSD", "5m", [(100, 100.5, 99.5, 100), (100, 112, 94, 105)])
    book.on_bar(b[0])
    (event,) = book.on_bar(b[1])
    assert event.reason is CloseReason.STOP_LOSS
    assert event.price == Decimal(95)


def test_gap_through_stop_fills_at_open() -> None:
    book = TheoreticalBook("XAUUSD")
    book.apply(long_signal())
    b = bars("XAUUSD", "5m", [(100, 101, 99, 100), (90, 92, 89, 91)])
    book.on_bar(b[0])
    (event,) = book.on_bar(b[1])
    assert event.price == Decimal(90)


def test_reversal_closes_then_opens_at_next_open() -> None:
    book = TheoreticalBook("XAUUSD")
    book.apply(long_signal(target=None))
    b = bars("XAUUSD", "5m", [(100, 101, 99, 100), (100, 101, 99, 100.5), (100.5, 101, 99, 100)])
    book.on_bar(b[0])
    assert book.apply(sig(SignalAction.SHORT, entry=Decimal(100), stop_loss=Decimal(106))) is None
    events = book.on_bar(b[1])
    assert [e.kind for e in events] == [PositionEventKind.CLOSED, PositionEventKind.OPENED]
    assert events[0].reason is CloseReason.REVERSAL
    assert book.position is not None and book.position.direction is Direction.SHORT


def test_ignore_opposite_and_duplicate_entries() -> None:
    book = TheoreticalBook("XAUUSD", on_opposite_signal="ignore")
    book.apply(long_signal())
    book.on_bar(bars("XAUUSD", "5m", [(100, 101, 99, 100)])[0])
    assert book.apply(long_signal()) == "POSITION_EXISTS"
    short = sig(SignalAction.SHORT, entry=Decimal(100), stop_loss=Decimal(106))
    assert book.apply(short) == "OPPOSITE_POSITION_OPEN"


def test_exit_and_move_sl() -> None:
    book = TheoreticalBook("XAUUSD")
    assert book.apply(sig(SignalAction.EXIT_LONG)) == "NO_MATCHING_POSITION"
    assert book.apply(sig(SignalAction.MOVE_SL, stop_loss=Decimal(99))) == "NO_POSITION"
    book.apply(long_signal())
    b = bars("XAUUSD", "5m", [(100, 101, 99, 100), (100, 101, 99.5, 100), (100, 101, 99, 100)])
    book.on_bar(b[0])
    assert book.apply(sig(SignalAction.MOVE_SL, stop_loss=Decimal("99.5"))) is None
    assert book.position is not None and book.position.stop_loss == Decimal("99.5")
    assert book.apply(sig(SignalAction.MOVE_SL, stop_loss=Decimal("99"))) == (
        "STOP_WIDENING_NOT_ALLOWED"  # accounts refuse it too: the book must not diverge
    )
    moved, stopped = book.on_bar(b[1])  # the move is reported; low 99.5 touches the stop
    assert moved.kind is PositionEventKind.STOP_MOVED and moved.price == Decimal("99.5")
    assert stopped.reason is CloseReason.STOP_LOSS
    book.apply(long_signal())
    book.on_bar(b[2])
    assert book.apply(sig(SignalAction.EXIT_LONG)) is None
    (closed,) = book.on_bar(
        bars("XAUUSD", "5m", [(100.2, 101, 99.9, 100)], start=b[2].close_time)[0]
    )
    assert closed.reason is CloseReason.SIGNAL_EXIT
    assert closed.price == Decimal("100.2")


def test_limit_entry_fills_on_touch_and_expires() -> None:
    book = TheoreticalBook("XAUUSD")
    limit = long_signal(
        entry=98, stop=95, target=None, order_type=OrderType.LIMIT, expires_after_bars=2
    )
    book.apply(limit)
    b = bars("XAUUSD", "5m", [(100, 101, 99, 100), (100, 101, 97.5, 99)])
    assert book.on_bar(b[0]) == []
    (opened,) = book.on_bar(b[1])
    assert opened.price == Decimal(98)

    book2 = TheoreticalBook("XAUUSD")
    book2.apply(limit)
    never = bars("XAUUSD", "5m", [(100, 101, 99, 100), (100, 101, 99, 100)])
    book2.on_bar(never[0])
    (expired,) = book2.on_bar(never[1])
    assert expired.kind is PositionEventKind.ORDER_EXPIRED
    assert not book2.has_pending_entry


def test_exit_cancels_resting_entry() -> None:
    book = TheoreticalBook("XAUUSD")
    book.apply(long_signal(entry=98, stop=95, order_type=OrderType.LIMIT))
    assert book.has_pending_entry
    assert book.apply(sig(SignalAction.EXIT_LONG)) is None
    assert not book.has_pending_entry


def test_a_bar_opening_beyond_the_target_takes_profit_at_the_open() -> None:
    book = TheoreticalBook("XAUUSD")
    book.apply(long_signal())  # stop 95, target 110
    b = bars("XAUUSD", "5m", [(100, 100.5, 99.8, 100.2), (112, 113, 94, 95)])
    book.on_bar(b[0])
    position = book.position
    assert position is not None and position.take_profit is not None
    (closed,) = book.on_bar(b[1])
    assert closed.reason is CloseReason.TAKE_PROFIT and closed.price == Decimal(112)


def test_resting_reversal_closes_only_when_it_fills() -> None:
    book = TheoreticalBook("XAUUSD")
    book.apply(long_signal())
    b = bars("XAUUSD", "5m", [(100, 100.5, 99.8, 100.2)] * 3 + [(100.2, 102, 100, 101)])
    book.on_bar(b[0])
    short_limit = sig(
        SignalAction.SHORT,
        entry=Decimal(101),
        stop_loss=Decimal(103),
        order_type=OrderType.LIMIT,
        expires_after_bars=3,
    )
    assert book.apply(short_limit) is None
    assert book.on_bar(b[1]) == [] and book.on_bar(b[2]) == []  # not reached: still long
    position = book.position
    assert position is not None and position.is_long
    reversed_, opened = book.on_bar(b[3])  # high 102 reaches the 101 limit
    assert reversed_.reason is CloseReason.REVERSAL and reversed_.price == Decimal(101)
    assert opened.kind is PositionEventKind.OPENED and opened.price == Decimal(101)
