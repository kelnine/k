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
    (stopped,) = book.on_bar(b[1])  # low 99.5 touches the moved stop
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
