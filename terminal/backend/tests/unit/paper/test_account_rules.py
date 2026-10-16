"""Position rules in the paper account — and the theoretical book agreeing with it."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from kterminal.core.enums import Direction, OrderType, SignalAction
from kterminal.core.ids import uuid7
from kterminal.domain.accounts import AccountSettings
from kterminal.domain.market import Bar
from kterminal.domain.signals import Signal
from kterminal.paper.account import InstrumentSetup, PaperAccount
from kterminal.paper.records import OrderRecord, Record, TradeEventRecord, TradeRecord
from kterminal.strategy_engine import PositionEventKind, PositionRules
from kterminal.strategy_engine.book import TheoreticalBook
from kterminal.strategy_engine.model import OPEN_BEYOND_STOP, OPEN_BEYOND_TARGET
from tests.fixtures.catalog import lab_catalog

MON = datetime(2026, 1, 5, 14, 0, tzinfo=UTC)  # Monday 09:00 New York: metals open
MINUTE = timedelta(minutes=1)
GUARDED = PositionRules(skip_entry_beyond_levels=True)


def account(rules: PositionRules | None = None, **settings: Any) -> PaperAccount:
    catalog = lab_catalog()
    listing = catalog.execution_listing("lab_default", "XAUUSD")
    return PaperAccount(
        account_id=uuid7(),
        name="Paper 50K · inst_a",
        instance_id="inst_a",
        settings=AccountSettings(**settings),
        config_version_id=uuid7(),
        markets={
            "XAUUSD": InstrumentSetup(
                instrument=catalog.instrument("XAUUSD"),
                listing=listing,
                costs=catalog.cost_calculator(listing),
                calendar=catalog.calendar_for(listing),
            )
        },
        timeframe="1m",
        trading_day_rule=catalog.sessions.trading_day_rule("ny_1700"),
        classify=catalog.sessions.classify,
        rules=rules,
    )


def sig(action: SignalAction, at: datetime = MON, **kw: Any) -> Signal:
    fields: dict[str, Any] = {
        "strategy_id": "inst_a",
        "strategy_version": "v1",
        "symbol": "XAUUSD",
        "timeframe": "1m",
        "timestamp": at,
        "signal": action,
    }
    for name in ("entry", "stop_loss", "take_profit"):
        if name in kw and kw[name] is not None:
            kw[name] = Decimal(str(kw[name]))
    fields.update(kw)
    return Signal(**fields)


def long(stop: str, target: str | None = None, entry: str = "4000.00") -> Signal:
    return sig(SignalAction.LONG, entry=entry, stop_loss=stop, take_profit=target)


def short(stop: str, target: str | None = None, entry: str = "4000.00") -> Signal:
    return sig(SignalAction.SHORT, entry=entry, stop_loss=stop, take_profit=target)


def bar(minute: int, o: str, h: str, low: str, c: str) -> Bar:
    return Bar.of("XAUUSD", "1m", MON + minute * MINUTE, o, h, low, c)


def decide(acc: PaperAccount, signal: Signal) -> Any:
    decision = acc.handle_signal(signal, uuid7(), signal.timestamp)
    assert decision is not None
    return decision


def opened_long(acc: PaperAccount) -> TradeRecord:
    acc.marks["XAUUSD"] = Decimal("4000.00")
    assert decide(acc, long("3990.00")).approved
    acc.on_bar(bar(0, "4000.00", "4001.00", "3999.00", "4000.00"))
    return acc.positions["XAUUSD"].trade


def of(records: list[Record], kind: type) -> list[Any]:
    return [r for r in records if isinstance(r, kind)]


# ── replace ─────────────────────────────────────────────────────────────────
def test_exit_then_same_direction_entry_replaces_at_the_next_open() -> None:
    acc = account()
    first = opened_long(acc)
    assert decide(acc, sig(SignalAction.EXIT_LONG)).approved
    decision = decide(acc, long("3992.00", "4025.00"))
    assert decision.approved  # max_open_positions = 1: the exiting position frees its slot
    rule = next(r for r in decision.rule_results if r["rule"] == "one_position_per_instrument")
    assert rule["values"]["replacing"] is True
    acc.drain()
    acc.on_bar(bar(1, "4002.00", "4003.00", "4001.00", "4002.00"))
    out = acc.drain()
    (closed,) = [t for t in of(out, TradeRecord) if t.status == "CLOSED"]
    (opened,) = [t for t in of(out, TradeRecord) if t.status == "OPEN"]
    assert closed.id == first.id and closed.exit_reason == "SIGNAL_EXIT"
    assert closed.exit_time == opened.entry_time == MON + MINUTE  # one open, both orders
    assert closed.exit_price == Decimal("4001.87")  # bid 4001.90 − slippage
    assert opened.entry_price == Decimal("4002.13")  # ask 4002.10 + slippage
    assert opened.initial_stop == Decimal("3992.00") and opened.initial_target == Decimal("4025.00")


def test_without_an_exit_a_second_entry_is_still_refused() -> None:
    acc = account()
    opened_long(acc)
    assert decide(acc, long("3992.00")).primary_reason == "POSITION_EXISTS"


def test_an_exit_frees_the_position_for_an_opposite_entry_even_when_ignoring() -> None:
    acc = account(PositionRules(on_opposite_signal="ignore"))
    opened_long(acc)
    assert decide(acc, short("4010.00")).primary_reason == "OPPOSITE_POSITION_OPEN"
    assert decide(acc, sig(SignalAction.EXIT_LONG)).approved
    assert decide(acc, short("4010.00")).approved
    acc.drain()
    acc.on_bar(bar(1, "4000.00", "4001.00", "3999.00", "4000.00"))
    (closed,) = [t for t in of(acc.drain(), TradeRecord) if t.status == "CLOSED"]
    assert closed.exit_reason == "SIGNAL_EXIT"  # the strategy's exit, not a reversal
    assert acc.positions["XAUUSD"].trade.direction is Direction.SHORT


# ── the level guard ─────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("open_", "code"),
    [("3994.00", OPEN_BEYOND_STOP), ("3995.00", OPEN_BEYOND_STOP), ("4010.00", OPEN_BEYOND_TARGET)],
)
def test_the_guard_cancels_a_market_entry_whose_bar_opens_beyond_a_level(
    open_: str, code: str
) -> None:
    acc = account(GUARDED)
    acc.marks["XAUUSD"] = Decimal("4000.00")
    decision = decide(acc, long("3995.00", "4010.00"))
    assert decision.approved  # decided on the signal bar; the open is not known yet
    acc.drain()
    acc.on_bar(bar(0, open_, open_, open_, open_))
    out = acc.drain()
    assert of(out, TradeRecord) == [] and acc.positions == {} and acc.pending_entries == {}
    (order,) = of(out, OrderRecord)
    assert order.status == "CANCELLED" and order.reject_reason == code
    assert order.decision_id == decision.id and order.completed_at == MON
    assert acc.stats.cancel_codes == {code: 1}
    # unguarded, the same entry is filled at that open
    plain = account()
    plain.marks["XAUUSD"] = Decimal("4000.00")
    decide(plain, long("3995.00", "4010.00"))
    plain.on_bar(bar(0, open_, open_, open_, open_))
    trades = of(plain.drain(), TradeRecord)
    assert trades and trades[0].status == "OPEN" and trades[0].entry_time == MON


def test_a_guarded_market_reversal_still_exits() -> None:
    acc = account(GUARDED)
    opened_long(acc)
    assert decide(acc, short("4002.00", "3990.00")).approved
    acc.drain()
    acc.on_bar(bar(1, "4003.00", "4004.00", "4002.50", "4003.00"))  # opens above the stop
    out = acc.drain()
    (closed,) = [t for t in of(out, TradeRecord) if t.status == "CLOSED"]
    assert closed.exit_reason == "REVERSAL" and acc.positions == {}
    cancelled = [o for o in of(out, OrderRecord) if o.status == "CANCELLED"]
    assert [o.reject_reason for o in cancelled] == [OPEN_BEYOND_STOP]


# ── session-close exits and stop moves ──────────────────────────────────────
def test_a_session_close_exit_is_recorded_with_its_reason() -> None:
    acc = account()
    opened_long(acc)
    assert decide(acc, sig(SignalAction.EXIT_LONG, reason="SESSION_CLOSE")).approved
    acc.on_bar(bar(1, "4001.00", "4002.00", "4000.00", "4001.00"))
    (closed,) = [t for t in of(acc.drain(), TradeRecord) if t.status == "CLOSED"]
    assert closed.exit_reason == "SESSION_CLOSE" and closed.exit_time == MON + MINUTE


def test_a_move_sl_that_keeps_the_stop_writes_no_stop_moved_row() -> None:
    acc = account()
    opened_long(acc)
    acc.drain()
    same = decide(acc, sig(SignalAction.MOVE_SL, stop_loss="3990.00"))
    assert same.approved and of(acc.drain(), TradeEventRecord) == []
    target_only = decide(acc, sig(SignalAction.MOVE_SL, stop_loss="3990.00", take_profit="4020"))
    assert target_only.approved
    assert [e.kind for e in of(acc.drain(), TradeEventRecord)] == ["TARGET_MOVED"]
    assert decide(acc, sig(SignalAction.MOVE_SL, stop_loss="3995.00")).approved
    (moved,) = of(acc.drain(), TradeEventRecord)
    assert moved.kind == "STOP_MOVED" and moved.new_value == Decimal("3995.00")


def test_rules_take_precedence_over_the_legacy_argument() -> None:
    assert account(PositionRules(on_opposite_signal="ignore")).on_opposite_signal == "ignore"
    catalog = lab_catalog()
    listing = catalog.execution_listing("lab_default", "XAUUSD")
    legacy = PaperAccount(
        account_id=uuid7(),
        name="Paper 50K · inst_a",
        instance_id="inst_a",
        settings=AccountSettings(),
        config_version_id=uuid7(),
        markets={
            "XAUUSD": InstrumentSetup(
                catalog.instrument("XAUUSD"), listing, catalog.cost_calculator(listing)
            )
        },
        timeframe="1m",
        on_opposite_signal="ignore",
    )
    assert legacy.rules == PositionRules(on_opposite_signal="ignore")


# ── the book and the account agree ──────────────────────────────────────────
# (open, high, low, close) per 1m bar, and the signals decided on its close. Levels keep
# clear of the account's half spread (0.10) and slippage (0.03), so both sides see the
# same triggers: replace, a session-close exit, a guarded short opening beyond its stop,
# a stop-out, a guarded long opening beyond its target, a reversal and a target.
def _scenario() -> list[tuple[Bar, list[Signal]]]:
    rows: list[tuple[tuple[str, str, str, str], list[tuple[str, dict[str, str]]]]] = [
        (
            ("4000", "4001", "3999", "4000"),
            [("LONG", {"stop_loss": "3990", "take_profit": "4030"})],
        ),
        (
            ("4000", "4001", "3999", "4000"),
            [
                ("EXIT_LONG", {}),
                ("LONG", {"stop_loss": "3992", "take_profit": "4025"}),
            ],
        ),
        (("4002", "4003", "4001", "4002"), []),
        (("4002", "4003", "4001", "4003"), [("EXIT_LONG", {"reason": "SESSION_CLOSE"})]),
        (
            ("4003", "4004", "4002", "4003"),
            [("SHORT", {"stop_loss": "4010", "take_profit": "3980"})],
        ),
        (
            ("4012", "4013", "4011", "4012"),
            [("SHORT", {"stop_loss": "4030", "take_profit": "3990"})],
        ),
        (("4011", "4012", "4010", "4011"), []),
        (
            ("4011", "4035", "4010", "4030"),
            [("LONG", {"stop_loss": "4020", "take_profit": "4040"})],
        ),
        (
            ("4041", "4042", "4040", "4041"),
            [("LONG", {"stop_loss": "4030", "take_profit": "4060"})],
        ),
        (
            ("4041", "4042", "4040", "4041"),
            [("SHORT", {"stop_loss": "4050", "take_profit": "4020"})],
        ),
        (("4040", "4041", "4039", "4040"), []),
        (("4035", "4036", "4019", "4020"), []),
    ]
    out: list[tuple[Bar, list[Signal]]] = []
    for minute, ((o, h, low, c), planned) in enumerate(rows):
        b = bar(minute, o, h, low, c)
        signals = [
            sig(
                SignalAction(action),
                at=b.close_time,
                entry=c if action in ("LONG", "SHORT") else None,
                **fields,
            )
            for action, fields in planned
        ]
        out.append((b, signals))
    return out


@dataclass(frozen=True)
class Outcome:
    entry_time: datetime
    direction: Direction
    exit_time: datetime
    reason: str


def test_the_book_and_the_account_agree_on_every_trade_and_skip() -> None:
    book = TheoreticalBook("XAUUSD", skip_entry_beyond_levels=True)
    acc = account(GUARDED)
    book_trades: list[Outcome] = []
    book_skips: list[tuple[datetime, str | None]] = []
    entries: dict[Direction, datetime] = {}
    for b, signals in _scenario():
        acc.on_bar(b)
        for event in book.on_bar(b):
            if event.kind is PositionEventKind.OPENED:
                entries[event.direction] = event.time
            elif event.kind is PositionEventKind.CLOSED:
                assert event.reason is not None
                book_trades.append(
                    Outcome(
                        entries[event.direction], event.direction, event.time, event.reason.value
                    )
                )
            elif event.kind is PositionEventKind.ORDER_CANCELLED:
                book_skips.append((event.time, event.detail))
        for signal in signals:
            book.apply(signal)
            acc.handle_signal(signal, uuid7(), signal.timestamp)
    out = acc.drain()
    account_trades = [
        Outcome(t.entry_time, t.direction, t.exit_time, t.exit_reason)
        for t in of(out, TradeRecord)
        if t.status == "CLOSED"
    ]
    account_skips = [
        (o.completed_at, o.reject_reason) for o in of(out, OrderRecord) if o.status == "CANCELLED"
    ]
    assert [t.reason for t in book_trades] == [
        "SIGNAL_EXIT",
        "SESSION_CLOSE",
        "STOP_LOSS",
        "REVERSAL",
        "TAKE_PROFIT",
    ]
    assert book_trades == account_trades
    assert [code for _t, code in book_skips] == [OPEN_BEYOND_STOP, OPEN_BEYOND_TARGET]
    assert book_skips == account_skips
    assert book.position is None and acc.positions == {}


def test_replace_with_a_resting_entry_exits_now_and_waits_for_the_fill() -> None:
    acc = account()
    opened_long(acc)
    assert decide(acc, sig(SignalAction.EXIT_LONG)).approved
    limit = sig(
        SignalAction.LONG,
        entry="3995.00",
        stop_loss="3990.00",
        order_type=OrderType.LIMIT,
    )
    assert decide(acc, limit).approved
    acc.drain()
    acc.on_bar(bar(1, "4000.00", "4001.00", "3999.00", "4000.00"))  # the limit is not reached
    (closed,) = [t for t in of(acc.drain(), TradeRecord) if t.status == "CLOSED"]
    assert closed.exit_reason == "SIGNAL_EXIT" and "XAUUSD" in acc.pending_entries
    acc.on_bar(bar(2, "3998.00", "3998.00", "3994.00", "3996.00"))
    assert acc.positions["XAUUSD"].trade.entry_price == Decimal("3995.00")
