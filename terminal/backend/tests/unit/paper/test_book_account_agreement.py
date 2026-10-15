"""The theoretical book resolves orders like the paper account (doc 13 P8).

With the account's execution model (``BookExecution``: its bid/ask, slippage, tick grid,
calendar) the book fed the same base bars and the same signals holds what the account
holds — position, entry price, stop, target and resting entry — after every bar and every
signal, unless the account refused something for risk reasons. Scenario tests pin the
cases the mid-price book used to get wrong; a seeded random walk checks the rest.
"""

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import numpy as np
import pytest

from kterminal.core.enums import OrderType, SignalAction
from kterminal.core.ids import uuid7
from kterminal.domain.accounts import AccountSettings
from kterminal.domain.market import Bar
from kterminal.domain.signals import Signal, validate_signal
from kterminal.domain.timeframes import M1
from kterminal.paper.account import InstrumentSetup, PaperAccount
from kterminal.paper.consistency import ConsistencyReport
from kterminal.paper.records import OrderRecord, TradeRecord
from kterminal.strategy_engine import NOTHING_TO_FLATTEN, PositionEventKind, PositionRules
from kterminal.strategy_engine.book import TheoreticalBook
from kterminal.strategy_engine.fills import BookExecution
from kterminal.strategy_engine.model import CloseReason
from tests.fixtures.catalog import lab_catalog

MON = datetime(2026, 1, 5, 14, 0, tzinfo=UTC)
MINUTE = timedelta(minutes=1)
D = Decimal


def setup() -> InstrumentSetup:
    catalog = lab_catalog()
    listing = catalog.execution_listing("lab_default", "XAUUSD")
    return InstrumentSetup(
        instrument=catalog.instrument("XAUUSD"),
        listing=listing,
        costs=catalog.cost_calculator(listing),
        calendar=catalog.calendar_for(listing),
    )


class Pair:
    """A book and an account of one instance, fed identically, checked after every step."""

    def __init__(self, rules: PositionRules | None = None, **book_options: Any) -> None:
        rules = rules or PositionRules()
        market = setup()
        self.account = PaperAccount(
            account_id=uuid7(),
            name="Paper 50K · inst_a",
            instance_id="inst_a",
            settings=AccountSettings(),
            config_version_id=uuid7(),
            markets={"XAUUSD": market},
            timeframe="1m",
            rules=rules,
        )
        execution = BookExecution(
            prices=market.prices,
            base_timeframe=M1,
            calendar=book_options.get("calendar", market.calendar),
            tradable=book_options.get("tradable", True),
        )
        self.book = TheoreticalBook(
            "XAUUSD",
            on_opposite_signal=rules.on_opposite_signal,
            skip_entry_beyond_levels=rules.skip_entry_beyond_levels,
            execution=execution,
        )
        self.report = ConsistencyReport()
        self.minute = 0
        self.events: list[Any] = []
        self.reasons: list[str | None] = []

    @property
    def now(self) -> datetime:
        return MON + self.minute * MINUTE

    def bar(self, o: str | Decimal, h: str | Decimal, low: str | Decimal, c: str | Decimal) -> None:
        bar = Bar.of("XAUUSD", "1m", self.now, o, h, low, c)
        self.account.on_bar(bar)
        self.events.extend(self.book.on_base_bar(bar))
        self.events.extend(self.book.end_bar(bar.close_time))
        self.minute += 1
        self.check()

    def send(self, *signals: Signal) -> list[str | None]:
        reasons = []
        for signal in signals:
            reasons.append(self.book.apply(signal))
            self.account.handle_signal(signal, uuid7(), signal.timestamp)
        self.reasons.extend(reasons)
        self.check()
        return reasons

    def check(self) -> None:
        self.report.observe("inst_a", self.account, self.book.state(self.now))
        assert self.report.divergent == 0, self.report.summary()["examples"]

    def signal(self, action: SignalAction, **kw: Any) -> Signal:
        fields: dict[str, Any] = {
            "strategy_id": "inst_a",
            "strategy_version": "v1",
            "symbol": "XAUUSD",
            "timeframe": "1m",
            "timestamp": self.now,
            "bar_time": self.now - MINUTE,
            "signal": action,
        }
        for name in ("entry", "stop_loss", "take_profit"):
            if kw.get(name) is not None:
                kw[name] = D(str(kw[name]))
        fields.update(kw)
        return validate_signal(Signal(**fields))

    def trades(self) -> list[TradeRecord]:
        return [r for r in self.account.drain() if isinstance(r, TradeRecord)]


def test_a_target_touched_by_the_mid_only_closes_neither() -> None:
    """The case the ports reported: the mid touches the target, the bid does not."""
    pair = Pair()
    pair.bar("4000", "4001", "3999", "4000")
    pair.send(pair.signal(SignalAction.LONG, entry="4000", stop_loss="3990", take_profit="4010"))
    pair.bar("4000.00", "4002.00", "3999.00", "4001.00")  # fills at the ask + slippage
    position = pair.book.position
    assert position is not None and position.entry_price == D("4000.13")
    pair.bar("4001.00", "4010.05", "4000.00", "4009.00")  # bid high 4009.95 < 4010
    assert pair.book.position is not None
    pair.bar("4009.00", "4010.10", "4008.00", "4009.00")  # bid 4010.00: the target fills
    assert pair.book.position is None
    closed = [e for e in pair.events if e.kind is PositionEventKind.CLOSED]
    assert [(e.reason, e.price) for e in closed] == [(CloseReason.TAKE_PROFIT, D("4010"))]


def test_a_stop_reached_by_the_bid_before_the_mid_and_a_gap_through_it() -> None:
    pair = Pair()
    pair.bar("4000", "4001", "3999", "4000")
    pair.send(pair.signal(SignalAction.LONG, entry="4000", stop_loss="3990", take_profit="4030"))
    pair.bar("4000", "4001", "3999", "4000")
    pair.bar("4000.00", "4000.50", "3990.05", "3995.00")  # mid stays above, the bid hits
    closed = [e for e in pair.events if e.kind is PositionEventKind.CLOSED]
    assert [(e.reason, e.price) for e in closed] == [(CloseReason.STOP_LOSS, D("3989.97"))]
    pair.send(pair.signal(SignalAction.SHORT, entry="3995", stop_loss="4005", take_profit="3980"))
    pair.bar("3995", "3996", "3994", "3995")
    pair.bar("4010.00", "4012.00", "4009.00", "4011.00")  # gaps through the stop: the open ask
    closed = [e for e in pair.events if e.kind is PositionEventKind.CLOSED]
    assert closed[-1].price == D("4010.13")
    trades = [t for t in pair.trades() if t.status == "CLOSED"]
    assert [t.exit_price for t in trades] == [D("3989.97"), D("4010.13")]


def test_a_bar_that_reaches_both_levels_is_a_stop_in_both() -> None:
    pair = Pair()
    pair.bar("4000", "4001", "3999", "4000")
    pair.send(pair.signal(SignalAction.LONG, entry="4000", stop_loss="3995", take_profit="4005"))
    pair.bar("4000", "4001", "3999", "4000")
    pair.bar("4000", "4010", "3990", "4000")
    closed = [e for e in pair.events if e.kind is PositionEventKind.CLOSED]
    assert [e.reason for e in closed] == [CloseReason.STOP_LOSS]


def test_a_limit_touched_by_the_mid_waits_like_the_account_and_expires_with_it() -> None:
    pair = Pair()
    pair.bar("4000", "4001", "3999", "4000")
    limit = pair.signal(
        SignalAction.LONG,
        entry="3995.10",
        stop_loss="3990",
        take_profit="4010",
        order_type=OrderType.LIMIT,
        expires_after_bars=2,
    )
    pair.send(limit)
    pending = pair.book.pending_entry
    assert pending is not None and pending.entry == D("3995.10") and pending.bars_waited == 0
    pair.bar("4000.00", "4001.00", "3995.05", "3999.00")  # mid below, ask 3995.15 above
    assert pair.book.pending_entry is not None and pair.book.pending_entry.bars_waited == 1
    pair.bar("3999.00", "4001.00", "3996.00", "3999.00")
    assert pair.book.pending_entry is None  # expired with its second bar …
    assert [e.kind for e in pair.events] == [PositionEventKind.ORDER_EXPIRED]
    assert "XAUUSD" in pair.account.pending_entries  # … the account drops it next bar
    pair.bar("3990.00", "3991.00", "3980.00", "3985.00")  # would have filled: neither does
    assert pair.book.position is None and not pair.account.positions
    orders = [r for r in pair.account.drain() if isinstance(r, OrderRecord)]
    assert orders[-1].status == "EXPIRED"


def test_a_resting_entry_filled_inside_the_bar_takes_profit_only_on_the_close() -> None:
    pair = Pair()
    pair.bar("4000", "4001", "3999", "4000")
    pair.send(
        pair.signal(
            SignalAction.LONG,
            entry="3995",
            stop_loss="3985",
            take_profit="4005",
            order_type=OrderType.LIMIT,
        )
    )
    pair.bar("4000.00", "4006.00", "3994.00", "4004.00")  # fills, high beyond, close not
    position = pair.book.position
    assert position is not None and position.entry_price == D("3995")
    pair.bar("4004.00", "4006.00", "4003.00", "4004.00")
    assert pair.book.position is None


def test_venue_refusals_are_mirrored_and_a_refused_reversal_still_exits() -> None:
    pair = Pair()
    pair.bar("4000", "4001", "3984", "3984.50")  # the mark: 3984.50
    # a market entry whose stop is not beyond the current price is refused by both
    wrong = pair.signal(SignalAction.LONG, entry="3990", stop_loss="3985", take_profit="4010")
    assert pair.send(wrong) == ["STOP_WRONG_SIDE"]
    assert pair.account.stats.reject_codes == {"STOP_WRONG_SIDE": 1}
    pair.send(pair.signal(SignalAction.SHORT, entry="3984.50", stop_loss="3995"))
    pair.bar("3984.50", "3985", "3984", "3984.50")
    assert pair.book.position is not None and pair.book.position.is_short
    # a reversal whose entry is refused (its target is not beyond the price) still exits
    refused = pair.signal(SignalAction.LONG, entry="3980", stop_loss="3975", take_profit="3984")
    assert pair.send(refused) == [None]
    assert pair.account.entry_rejects == {"XAUUSD": "TARGET_WRONG_SIDE"}
    pair.bar("3984.50", "3985", "3984", "3984.50")
    assert pair.book.position is None and not pair.account.positions


def test_closed_market_and_data_only_listings_are_refused_like_the_account() -> None:
    catalog = lab_catalog()
    weekdays = catalog.sessions.calendar("metals_otc")
    saturday = datetime(2026, 1, 10, 12, 0, tzinfo=UTC)
    assert not weekdays.is_open(saturday)
    pair = Pair(calendar=weekdays)
    pair.account.markets["XAUUSD"] = replace(pair.account.markets["XAUUSD"], calendar=weekdays)
    pair.minute = int((saturday - MON) / MINUTE)
    pair.bar("4000", "4001", "3999", "4000")
    assert pair.send(pair.signal(SignalAction.LONG, entry="4000", stop_loss="3990")) == [
        "MARKET_CLOSED"
    ]
    data_only = Pair(tradable=False)
    data_only.bar("4000", "4001", "3999", "4000")
    reason = data_only.book.apply(
        data_only.signal(SignalAction.LONG, entry="4000", stop_loss="3990")
    )
    assert reason == "NOT_TRADABLE"


@pytest.mark.parametrize("held", [True, False])
def test_flatten_closes_or_cancels_whatever_is_there_in_both(held: bool) -> None:
    pair = Pair()
    pair.bar("4000", "4001", "3999", "4000")
    if held:
        pair.send(pair.signal(SignalAction.SHORT, entry="4000", stop_loss="4010"))
    else:
        pair.send(
            pair.signal(
                SignalAction.LONG,
                entry="3990",
                stop_loss="3980",
                order_type=OrderType.LIMIT,
            )
        )
    pair.bar("4000", "4001", "3999", "4000")
    assert (pair.book.position is not None) is held
    assert (pair.book.pending_entry is not None) is not held
    assert pair.send(pair.signal(SignalAction.FLATTEN, reason="SESSION_CLOSE")) == [None]
    assert pair.book.pending_entry is None and not pair.account.pending_entries
    pair.bar("4002.00", "4003.00", "4001.00", "4002.00")
    assert pair.book.position is None and not pair.account.positions
    if held:
        closed = [e for e in pair.events if e.kind is PositionEventKind.CLOSED]
        assert [(e.reason, e.price) for e in closed] == [(CloseReason.SESSION_CLOSE, D("4002.13"))]
        trade = [t for t in pair.trades() if t.status == "CLOSED"][-1]
        assert (trade.exit_reason, trade.exit_price) == ("SESSION_CLOSE", D("4002.13"))
    # nothing left: a silent no-op in both
    decisions_before = pair.account.stats.signals
    assert pair.send(pair.signal(SignalAction.FLATTEN)) == [NOTHING_TO_FLATTEN]
    assert pair.account.stats.signals == decisions_before


SCENARIO_RULES = [
    PositionRules(),
    PositionRules(on_opposite_signal="ignore"),
    PositionRules(skip_entry_beyond_levels=True),
]


def _pick[T](rng: np.random.Generator, options: Sequence[T]) -> T:
    return options[int(rng.integers(len(options)))]


def _random_signals(pair: Pair, rng: np.random.Generator, close: Decimal) -> list[Signal]:
    def dist(low: float, high: float) -> Decimal:
        return D(str(round(float(rng.uniform(low, high)), 2)))

    out: list[Signal] = []
    for _ in range(_pick(rng, (0, 0, 0, 1, 1, 2))):
        kind = _pick(
            rng, ("market", "market", "limit", "stop", "exit", "move", "flatten", "replace")
        )
        long = rng.random() < 0.5
        sign = 1 if long else -1
        action = SignalAction.LONG if long else SignalAction.SHORT
        if kind in ("market", "replace"):
            stop = close - sign * dist(1, 12)
            target = close + sign * dist(1, 15) if rng.random() < 0.8 else None
            if kind == "replace":
                exit_action = SignalAction.EXIT_SHORT if long else SignalAction.EXIT_LONG
                out.append(pair.signal(_pick(rng, (exit_action, SignalAction.FLATTEN))))
            out.append(pair.signal(action, entry=close, stop_loss=stop, take_profit=target))
        elif kind in ("limit", "stop"):
            away = dist(0.05, 4) * (-sign if kind == "limit" else sign)
            entry = close + away
            out.append(
                pair.signal(
                    action,
                    entry=entry,
                    stop_loss=entry - sign * dist(1, 10),
                    take_profit=entry + sign * dist(1, 12) if rng.random() < 0.8 else None,
                    order_type=OrderType.LIMIT if kind == "limit" else OrderType.STOP,
                    expires_after_bars=_pick(rng, (None, 1, 2, 4)),
                )
            )
        elif kind == "exit":
            out.append(pair.signal(SignalAction.EXIT_LONG if long else SignalAction.EXIT_SHORT))
        elif kind == "move":
            out.append(
                pair.signal(
                    SignalAction.MOVE_SL,
                    stop_loss=close - sign * dist(0.5, 8),
                    take_profit=close + sign * dist(1, 10) if rng.random() < 0.5 else None,
                )
            )
        else:
            out.append(
                pair.signal(
                    SignalAction.FLATTEN, reason=_pick(rng, ("SESSION_CLOSE", "window end"))
                )
            )
    return out


@pytest.mark.parametrize("seed", range(12))
def test_random_walks_keep_book_and_account_identical(seed: int) -> None:
    rng = np.random.default_rng(seed)
    pair = Pair(SCENARIO_RULES[seed % len(SCENARIO_RULES)])
    close = D("4000.00")
    for _ in range(400):
        gap = D(str(round(float(rng.normal(0, 3)), 2))) if rng.random() < 0.08 else D(0)
        o = close + gap
        c = o + D(str(round(float(rng.normal(0, 1.5)), 2)))
        h = max(o, c) + D(str(round(float(rng.uniform(0, 2)), 2)))
        low = min(o, c) - D(str(round(float(rng.uniform(0, 2)), 2)))
        pair.bar(o, h, low, c)
        close = c
        pair.send(*_random_signals(pair, rng, close))
    assert pair.report.checks == 2 * 400
    opened = sum(1 for e in pair.events if e.kind is PositionEventKind.OPENED)
    assert opened > 20  # the walk really traded
    assert pair.account.stats.trades_opened == opened
    risk_only = set(pair.account.stats.reject_codes) - {
        "POSITION_EXISTS",
        "OPPOSITE_POSITION_OPEN",
        "NO_MATCHING_POSITION",
        "NO_POSITION",
        "STOP_WIDENING_NOT_ALLOWED",
        "STOP_WRONG_SIDE",
        "TARGET_WRONG_SIDE",
    }
    assert risk_only == set()  # every refusal was one the book made too
    assert pair.account.entry_rejects == {} or set(pair.account.entry_rejects.values()) <= {
        "POSITION_EXISTS",
        "OPPOSITE_POSITION_OPEN",
        "STOP_WRONG_SIDE",
        "TARGET_WRONG_SIDE",
    }


def test_a_kill_switch_flatten_keeps_its_reason_when_the_strategy_flattens_too() -> None:
    pair = Pair()
    pair.bar("4000", "4001", "3999", "4000")
    pair.send(pair.signal(SignalAction.LONG, entry="4000", stop_loss="3990"))
    pair.bar("4000", "4001", "3999", "4000")
    pair.account.entry_halt = "GLOBAL kill switch active: drill"
    pair.account.flatten(pair.now, "KILL_SWITCH")  # close_positions: FLATTEN orders
    assert pair.send(pair.signal(SignalAction.FLATTEN)) == [None]  # exits stay permitted
    pair.bar("4000", "4001", "3999", "4000")
    closed = [t for t in pair.trades() if t.status == "CLOSED"]
    assert [t.exit_reason for t in closed] == ["KILL_SWITCH"]
    flatten = pair.signal(SignalAction.FLATTEN).model_copy(update={"symbol": "NEARUSD"})
    assert pair.account.handle_signal(flatten, uuid7(), pair.now) is None  # not traded here
