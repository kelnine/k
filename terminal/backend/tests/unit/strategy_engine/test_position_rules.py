"""Position rules in the theoretical book: level guard, replace, session-close exits,
no-op stop moves, and per-instance overrides of the definition's rules."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from kterminal.core.enums import Direction, OrderType, SignalAction
from kterminal.core.registry import Registry
from kterminal.domain.market import Bar
from kterminal.domain.signals import Signal
from kterminal.strategy_engine import CloseReason, PositionEventKind, PositionRules
from kterminal.strategy_engine.book import TheoreticalBook
from kterminal.strategy_engine.instances import InstanceSpec, ResolvedInstance, resolve_instance
from kterminal.strategy_engine.model import (
    OPEN_BEYOND_STOP,
    OPEN_BEYOND_TARGET,
    exit_reason,
    open_beyond_levels,
)
from kterminal.strategy_engine.registry import StrategyDefinition, definition_from_class
from kterminal.strategy_engine.testing import run_strategy
from tests.fixtures.engine_strategies import Planned
from tests.fixtures.instruments import INSTRUMENTS, XAUUSD, bars

T = datetime(2026, 1, 5, tzinfo=UTC)
FLAT = (100.0, 100.5, 99.5, 100.0)


def sig(action: SignalAction, **kw: Any) -> Signal:
    fields: dict[str, Any] = {
        "strategy_id": "s",
        "strategy_version": "v",
        "symbol": "XAUUSD",
        "timeframe": "5m",
        "timestamp": T,
        "signal": action,
    }
    fields.update(kw)
    return Signal(**fields)


def entry(
    action: SignalAction, entry: float, stop: float, target: float | None, **kw: Any
) -> Signal:
    return sig(
        action,
        entry=Decimal(str(entry)),
        stop_loss=Decimal(str(stop)),
        take_profit=Decimal(str(target)) if target is not None else None,
        **kw,
    )


def long(stop: float = 95, target: float | None = 110, **kw: Any) -> Signal:
    return entry(SignalAction.LONG, 100, stop, target, **kw)


def short(stop: float = 105, target: float | None = 90, **kw: Any) -> Signal:
    return entry(SignalAction.SHORT, 100, stop, target, **kw)


def opened_long(book: TheoreticalBook) -> None:
    book.apply(long(target=None))
    book.on_bar(bars("XAUUSD", "5m", [FLAT])[0])
    assert book.position is not None and book.position.is_long


def bar_at(index: int, o: float, h: float, low: float, c: float) -> Bar:
    return bars("XAUUSD", "5m", [FLAT] * index + [(o, h, low, c)])[index]


# ── the level guard ─────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("signal", "open_", "code"),
    [
        (long(), 94.0, OPEN_BEYOND_STOP),
        (long(), 95.0, OPEN_BEYOND_STOP),  # at the stop counts
        (long(), 110.0, OPEN_BEYOND_TARGET),  # at the target counts
        (long(), 112.0, OPEN_BEYOND_TARGET),
        (short(), 105.0, OPEN_BEYOND_STOP),
        (short(), 89.0, OPEN_BEYOND_TARGET),
    ],
)
def test_the_guard_skips_a_market_entry_whose_bar_opens_beyond_a_level(
    signal: Signal, open_: float, code: str
) -> None:
    book = TheoreticalBook("XAUUSD", skip_entry_beyond_levels=True)
    assert book.apply(signal) is None
    (cancelled,) = book.on_bar(bar_at(0, open_, open_ + 1, open_ - 1, open_))
    assert cancelled.kind is PositionEventKind.ORDER_CANCELLED and cancelled.detail == code
    assert cancelled.price == Decimal(str(open_)) and cancelled.signal == signal
    assert book.position is None and not book.has_pending_entry
    # without the guard the same entry fills at that open
    plain = TheoreticalBook("XAUUSD")
    plain.apply(signal)
    events = plain.on_bar(bar_at(0, open_, open_ + 1, open_ - 1, open_))
    assert events[0].kind is PositionEventKind.OPENED


def test_the_guard_lets_entries_inside_the_levels_and_resting_orders_through() -> None:
    book = TheoreticalBook("XAUUSD", skip_entry_beyond_levels=True)
    book.apply(long())
    (opened,) = book.on_bar(bar_at(0, 96, 97, 95.5, 96.5))  # between stop and target
    assert opened.kind is PositionEventKind.OPENED
    resting = TheoreticalBook("XAUUSD", skip_entry_beyond_levels=True)
    resting.apply(long(order_type=OrderType.LIMIT))  # limit 100, target 110
    events = resting.on_bar(bar_at(0, 99, 99.5, 98, 99))  # a gap fill at the open
    assert [e.kind for e in events] == [PositionEventKind.OPENED]
    assert open_beyond_levels(Direction.SHORT, Decimal(100), Decimal(105), None) is None


def test_a_guarded_market_reversal_still_exits() -> None:
    book = TheoreticalBook("XAUUSD", skip_entry_beyond_levels=True)
    opened_long(book)
    book.apply(short(stop=101, target=95))
    closed, cancelled = book.on_bar(bar_at(1, 101.5, 102, 101, 101.5))  # opens above the stop
    assert closed.kind is PositionEventKind.CLOSED and closed.reason is CloseReason.REVERSAL
    assert closed.price == Decimal("101.5")
    assert cancelled.kind is PositionEventKind.ORDER_CANCELLED
    assert cancelled.detail == OPEN_BEYOND_STOP and book.position is None


# ── replace: exit and re-enter on one bar ───────────────────────────────────
def test_exit_then_entry_in_the_same_direction_replaces_at_the_next_open() -> None:
    book = TheoreticalBook("XAUUSD")
    opened_long(book)
    assert book.apply(sig(SignalAction.EXIT_LONG)) is None
    assert book.apply(long(stop=97, target=104)) is None  # refused before (POSITION_EXISTS)
    closed, opened = book.on_bar(bar_at(1, 100.2, 100.6, 99.8, 100.4))
    assert closed.reason is CloseReason.SIGNAL_EXIT and opened.kind is PositionEventKind.OPENED
    assert closed.price == opened.price == Decimal("100.2") and closed.time == opened.time
    position = book.position
    assert position is not None and position.stop_loss == Decimal(97)
    assert position.take_profit == Decimal(104) and position.entry_price == Decimal("100.2")


def test_the_exit_must_come_first() -> None:
    book = TheoreticalBook("XAUUSD")
    opened_long(book)
    assert book.apply(long()) == "POSITION_EXISTS"  # still holding: refused
    assert book.apply(sig(SignalAction.EXIT_LONG)) is None
    (closed,) = book.on_bar(bar_at(1, *FLAT))
    assert closed.reason is CloseReason.SIGNAL_EXIT and book.position is None


def test_an_exit_frees_the_position_for_an_opposite_entry_even_when_ignoring() -> None:
    book = TheoreticalBook("XAUUSD", on_opposite_signal="ignore")
    opened_long(book)
    assert book.apply(short()) == "OPPOSITE_POSITION_OPEN"
    book.apply(sig(SignalAction.EXIT_LONG))
    assert book.apply(short()) is None
    closed, opened = book.on_bar(bar_at(1, *FLAT))
    assert closed.reason is CloseReason.SIGNAL_EXIT  # the strategy's own exit, not a reversal
    assert opened.direction is Direction.SHORT


def test_replace_with_a_resting_entry_exits_now_and_waits_for_the_fill() -> None:
    book = TheoreticalBook("XAUUSD")
    opened_long(book)
    book.apply(sig(SignalAction.EXIT_LONG))
    book.apply(entry(SignalAction.LONG, 99, 97, None, order_type=OrderType.LIMIT))
    (closed,) = book.on_bar(bar_at(1, 100, 100.5, 99.5, 100))  # limit 99 not reached
    assert closed.reason is CloseReason.SIGNAL_EXIT and book.has_pending_entry
    (opened,) = book.on_bar(bar_at(2, 100, 100.5, 98.5, 99))
    assert opened.price == Decimal(99)


# ── session-close exits and stop moves ──────────────────────────────────────
def test_an_exit_with_reason_session_close_is_recorded_as_one() -> None:
    book = TheoreticalBook("XAUUSD")
    opened_long(book)
    book.apply(sig(SignalAction.EXIT_LONG, reason="SESSION_CLOSE"))
    (closed,) = book.on_bar(bar_at(1, *FLAT))
    assert closed.reason is CloseReason.SESSION_CLOSE
    assert exit_reason(sig(SignalAction.EXIT_LONG, reason="session ended")) is (
        CloseReason.SIGNAL_EXIT  # free text stays a plain signal exit
    )


def test_a_move_sl_that_keeps_the_stop_reports_nothing() -> None:
    book = TheoreticalBook("XAUUSD")
    book.apply(long())
    book.on_bar(bar_at(0, *FLAT))
    book.apply(sig(SignalAction.MOVE_SL, stop_loss=Decimal(95)))  # unchanged stop and target
    assert book.on_bar(bar_at(1, *FLAT)) == []
    book.apply(sig(SignalAction.MOVE_SL, stop_loss=Decimal(95), take_profit=Decimal(108)))
    (moved,) = book.on_bar(bar_at(2, *FLAT))
    assert moved.kind is PositionEventKind.TARGET_MOVED and moved.price == Decimal(108)


# ── through the runner: ctx builders and per-instance rules ─────────────────
def test_the_runner_applies_the_instance_rules_and_session_close_exits() -> None:
    plan = {
        "steps": [
            {"bar": 1, "action": "long", "stop": "95", "target": "110"},
            {"bar": 2, "action": "exit_long"},
            {"bar": 2, "action": "long", "stop": "96", "target": "104"},
            {"bar": 4, "action": "short", "stop": "106"},
            {"bar": 5, "action": "exit_long", "session_close": True},
            {"bar": 6, "action": "short", "stop": "101", "target": "90"},
        ]
    }
    rows = [FLAT, FLAT, FLAT, FLAT, FLAT, FLAT, (101.5, 102, 101, 101.5), FLAT]
    result = run_strategy(
        Planned,
        instrument=XAUUSD,
        bars=bars("XAUUSD", "5m", rows),
        timeframe="5m",
        params=plan,
        on_opposite_signal="ignore",
        skip_entry_beyond_levels=True,
    )
    assert result.fault is None
    kinds = [(e.kind.value, e.reason.value if e.reason else e.detail) for e in result.events]
    assert kinds == [
        ("OPENED", None),  # bar 2
        ("CLOSED", "SIGNAL_EXIT"),  # bar 3: replace …
        ("OPENED", None),  # … at the same open
        # bar 4's short is ignored (on_opposite_signal: ignore for this instance)
        ("CLOSED", "SESSION_CLOSE"),  # bar 6
        ("ORDER_CANCELLED", OPEN_BEYOND_STOP),  # bar 7 opens above the short's stop
    ]


def test_instance_rules_override_the_definition_and_join_the_version() -> None:
    registry: Registry[StrategyDefinition] = Registry("strategy definition")
    definition = definition_from_class(Planned)
    registry.register(definition.id, definition)

    def resolve(**overrides: Any) -> ResolvedInstance:
        spec = InstanceSpec(
            id="planned_a",
            strategy="planned",
            instruments=("XAUUSD",),
            timeframe="5m",
            **overrides,
        )
        return resolve_instance(spec, instruments=INSTRUMENTS, definitions=registry)

    default = resolve()
    assert default.position_rules == PositionRules("reverse", skip_entry_beyond_levels=False)
    assert "skip_entry_beyond_levels" not in default.config["behaviour"]  # hashes unchanged
    assert resolve(on_opposite_signal="reverse").version == default.version  # = the meta value
    ignoring = resolve(on_opposite_signal="ignore")
    assert ignoring.position_rules.on_opposite_signal == "ignore"
    assert ignoring.version != default.version
    guarded = resolve(skip_entry_beyond_levels=True)
    assert guarded.position_rules.skip_entry_beyond_levels
    assert guarded.config["behaviour"]["skip_entry_beyond_levels"] is True
    assert guarded.version != default.version
    assert resolve(skip_entry_beyond_levels=False).version == default.version
    runner_book = run_strategy(
        Planned, instrument=XAUUSD, bars=[], timeframe="5m", on_opposite_signal="ignore"
    ).runner
    assert runner_book is not None and runner_book.book.on_opposite_signal == "ignore"


def test_session_close_builder_refuses_a_conflicting_reason() -> None:
    result = run_strategy(
        Planned, instrument=XAUUSD, bars=bars("XAUUSD", "5m", [FLAT]), timeframe="5m"
    )
    ctx = result.runner.ctx  # type: ignore[union-attr]
    assert ctx.exit_short(session_close=True).reason == "SESSION_CLOSE"
    assert ctx.exit_long(reason="SESSION_CLOSE", session_close=True).reason == "SESSION_CLOSE"
    assert ctx.exit_long(reason="trail hit").reason == "trail hit"
    with pytest.raises(ValueError, match="SESSION_CLOSE"):
        ctx.exit_long(reason="end of day", session_close=True)


def test_a_guarded_replacement_still_exits_when_its_entry_is_skipped() -> None:
    book = TheoreticalBook("XAUUSD", skip_entry_beyond_levels=True)
    opened_long(book)
    book.apply(sig(SignalAction.EXIT_LONG))
    book.apply(long(stop=99, target=104))
    closed, cancelled = book.on_bar(bar_at(1, 98.5, 99, 98, 98.5))  # opens below the new stop
    assert closed.reason is CloseReason.SIGNAL_EXIT and closed.price == Decimal("98.5")
    assert cancelled.kind is PositionEventKind.ORDER_CANCELLED
    assert cancelled.detail == OPEN_BEYOND_STOP and book.position is None
