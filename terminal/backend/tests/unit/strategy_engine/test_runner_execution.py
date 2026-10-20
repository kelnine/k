"""The runner with an execution model: the theoretical book resolves the base bars like the
account, the strategy sees ``ctx.warming_up`` / ``ctx.pending_entry``, the book's reasons
reach the output, and ``ctx.flatten()`` closes or cancels whatever the book holds."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from kterminal.core.enums import Direction, OrderType, SignalAction
from kterminal.core.registry import Registry
from kterminal.domain.market import Bar
from kterminal.domain.timeframes import M1, M5
from kterminal.marketdata.aggregator import aggregate_stream
from kterminal.strategy_engine import NOTHING_TO_FLATTEN, CloseReason, PositionEventKind
from kterminal.strategy_engine.fills import BookExecution, VenuePrices
from kterminal.strategy_engine.hosts import InProcessHost, SubprocessHost
from kterminal.strategy_engine.instances import InstanceSpec, ResolvedInstance, resolve_instance
from kterminal.strategy_engine.model import RunnerOutput
from kterminal.strategy_engine.registry import StrategyDefinition, definition_from_class
from kterminal.strategy_engine.runner import StrategyRunner
from kterminal.strategy_engine.testing import run_strategy
from tests.fixtures.catalog import lab_catalog
from tests.fixtures.engine_strategies import Probe

START = datetime(2026, 1, 5, 14, 0, tzinfo=UTC)
MIN = timedelta(minutes=1)
CATALOG = lab_catalog()
XAU = CATALOG.instrument("XAUUSD")
LISTING = CATALOG.execution_listing("lab_default", "XAUUSD")
EXECUTION = BookExecution(
    VenuePrices(CATALOG.cost_calculator(LISTING), LISTING), M1, CATALOG.calendar_for(LISTING)
)
REGISTRY: Registry[StrategyDefinition] = Registry("strategy definition")
REGISTRY.register("probe", definition_from_class(Probe))
D = Decimal


def resolved(steps: Sequence[dict[str, Any]], timeframe: str = "5m") -> ResolvedInstance:
    spec = InstanceSpec(
        id="probe_a",
        strategy="probe",
        params={"steps": list(steps)},
        instruments=("XAUUSD",),
        timeframe=timeframe,
    )
    return resolve_instance(spec, instruments={"XAUUSD": XAU}, definitions=REGISTRY)


def runner(
    steps: Sequence[dict[str, Any]], *, execution: BookExecution | None = EXECUTION
) -> StrategyRunner:
    run = StrategyRunner(resolved(steps), XAU, execution=execution)
    assert run.start() is None
    return run


def minutes(rows: Sequence[tuple[str, str, str, str]], start: datetime = START) -> list[Bar]:
    return [Bar.of("XAUUSD", "1m", start + i * MIN, *row) for i, row in enumerate(rows)]


FLAT = ("4000.00", "4000.50", "3999.50", "4000.00")


def batches(bars: Sequence[Bar]) -> list[list[Bar]]:
    return list(aggregate_stream(bars, M1, [M5]))


def feed(run: StrategyRunner, bars: Sequence[Bar]) -> list[RunnerOutput]:
    outputs = []
    for batch in batches(bars):
        output = run.process(batch)
        if output is not None:
            outputs.append(output)
    return outputs


def probe(run: StrategyRunner) -> Probe:
    strategy = run._strategy
    assert isinstance(strategy, Probe)
    return strategy


def test_the_book_fills_and_stops_on_base_bars_and_reports_at_the_primary_close() -> None:
    steps = [{"bar": 1, "action": "long", "stop": "3995", "target": "4020"}]
    rows = [FLAT] * 5 + [
        ("4000.00", "4001.00", "3999.50", "4000.50"),  # fills at its open (ask + slippage)
        FLAT,
        ("4000.00", "4000.50", "3994.80", "3996.00"),  # the bid reaches the stop
        FLAT,
        FLAT,
    ]
    outputs = feed(runner(steps), minutes(rows))
    primary = [o for o in outputs if o.signals or o.events]
    base_only = [o for o in outputs if not o.signals and not o.events]
    assert len(outputs) == 10  # one output per base bar: the book after every batch
    assert all(o.book is not None for o in outputs)
    held = [o.book.position is not None for o in base_only if o.book is not None]
    assert held == [False] * 4 + [True, True, False, False]  # minutes 5, 6 held; 7 stopped
    events = primary[-1].events
    assert [(e.kind, e.time) for e in events] == [
        (PositionEventKind.OPENED, START + 5 * MIN),
        (PositionEventKind.CLOSED, START + 8 * MIN),  # the 1m bar's close, not the 5m one
    ]
    assert events[0].price == D("4000.13") and events[1].price == D("3994.97")
    assert events[1].reason is CloseReason.STOP_LOSS

    legacy = feed(runner(steps, execution=None), minutes(rows))
    assert all(o.book is None for o in legacy) and len(legacy) == 2  # primary bars only
    opened, closed = legacy[-1].events
    assert opened.price == D("4000.00")  # the mid of the 5m open
    assert closed.price == D("3995") and closed.time == START + 10 * MIN


def test_warming_up_is_visible_and_nothing_trades_during_warm_up() -> None:
    steps = [
        {"bar": 1, "action": "long", "stop": "3990"},
        {"bar": 2, "action": "flatten"},
        {"bar": 4, "action": "long", "stop": "3990"},
    ]
    run = runner(steps)
    warm = [bar for batch in batches(minutes([FLAT] * 10)) for bar in batch]
    run.warmup(warm)
    live = feed(run, minutes([FLAT] * 10, start=START + 10 * MIN))
    seen = probe(run).seen
    assert [w for w, _, _ in seen] == [True, True, False, False]
    assert all(position is None for _, _, position in seen[:3])
    assert run.book.position is None  # nothing filled in warm-up …
    assert run.book.pending_entry is not None  # … the live long of bar 4 fills on the next bar
    signals = [s for o in live for s in o.signals]
    assert [s.signal for s in signals] == [SignalAction.LONG]  # bar 1 and 2 were discarded
    assert not run.ctx.warming_up


def test_pending_entry_shows_the_resting_order_until_it_expires() -> None:
    steps = [
        {
            "bar": 1,
            "action": "long",
            "entry": "3990",
            "stop": "3985",
            "order_type": "LIMIT",
            "expires_after_bars": 2,
        }
    ]
    run = runner(steps)
    outputs = feed(run, minutes([FLAT] * 20))
    seen = probe(run).seen
    pending = seen[1][1]
    assert pending is not None
    assert (pending.direction, pending.order_type, pending.entry, pending.stop_loss) == (
        Direction.LONG,
        OrderType.LIMIT,
        D("3990"),
        D("3985"),
    )
    assert pending.bars_waited == 1 and pending.expires_after_bars == 2
    assert pending.placed_at == START + 5 * MIN
    assert seen[2][1] is None and seen[3][1] is None
    expired = [e for o in outputs for e in o.events if e.kind is PositionEventKind.ORDER_EXPIRED]
    assert [e.time for e in expired] == [START + 15 * MIN]  # with the close of its 2nd bar


def test_the_books_reasons_reach_the_output_and_run_strategy() -> None:
    steps = [
        {"bar": 1, "action": "long", "stop": "3990"},
        {"bar": 2, "action": "long", "stop": "3990"},
        {"bar": 2, "action": "exit_short"},
        {"bar": 3, "action": "move_sl", "stop": "3980"},
    ]
    outputs = feed(runner(steps), minutes([FLAT] * 20))
    with_signals = [o for o in outputs if o.signals]
    assert [o.book_reasons for o in with_signals] == [
        (None,),
        ("POSITION_EXISTS", "NO_MATCHING_POSITION"),
        ("STOP_WIDENING_NOT_ALLOWED",),
    ]
    assert with_signals[1].book_reason(5) is None
    result = run_strategy(
        Probe,
        instrument=XAU,
        bars=[b for batch in batches(minutes([FLAT] * 20)) for b in batch],
        timeframe="5m",
        params={"steps": steps},
        execution=EXECUTION,
    )
    assert [(s.signal, reason) for s, reason in result.ignored] == [
        (SignalAction.LONG, "POSITION_EXISTS"),
        (SignalAction.EXIT_SHORT, "NO_MATCHING_POSITION"),
        (SignalAction.MOVE_SL, "STOP_WIDENING_NOT_ALLOWED"),
    ]


def test_flatten_closes_the_position_cancels_the_order_and_is_a_no_op_when_flat() -> None:
    steps = [
        {"bar": 1, "action": "short", "stop": "4010"},
        {"bar": 3, "action": "flatten"},
        {"bar": 4, "action": "long", "entry": "3990", "stop": "3985", "order_type": "LIMIT"},
        {"bar": 5, "action": "flatten", "reason": "window end"},
        {"bar": 6, "action": "flatten"},
    ]
    run = runner(steps)
    outputs = feed(run, minutes([FLAT] * 35))
    events = [e for o in outputs for e in o.events]
    closed = [e for e in events if e.kind is PositionEventKind.CLOSED]
    assert [(e.direction, e.reason, e.time) for e in closed] == [
        (Direction.SHORT, CloseReason.SESSION_CLOSE, START + 15 * MIN)
    ]
    assert closed[0].price == D("4000.13")  # bought back at the ask + slippage
    seen = probe(run).seen
    assert seen[4][1] is not None and seen[5][1] is None  # the resting limit was cancelled
    flattens = [
        (o.signals[i].reason, o.book_reason(i))
        for o in outputs
        for i in range(len(o.signals))
        if o.signals[i].signal is SignalAction.FLATTEN
    ]
    assert flattens == [
        ("SESSION_CLOSE", None),
        ("window end", None),
        ("SESSION_CLOSE", NOTHING_TO_FLATTEN),
    ]


@pytest.mark.parametrize("subprocess", [False, True])
def test_hosts_carry_the_execution_model_and_agree(subprocess: bool) -> None:
    steps = [
        {"bar": 1, "action": "long", "stop": "3995", "target": "4002"},
        {"bar": 4, "action": "short", "entry": "4001", "stop": "4006", "order_type": "LIMIT"},
        {"bar": 6, "action": "flatten"},
    ]
    rows = [FLAT] * 5 + [("4000.00", "4001.50", "3999.50", "4001.00")] + [FLAT] * 24
    bars = batches(minutes(rows))
    reference = StrategyRunner(resolved(steps), XAU, execution=EXECUTION)
    reference.start()
    expected = [o for o in (reference.process(b) for b in bars) if o is not None]
    execution = {"XAUUSD": EXECUTION}
    host = (
        SubprocessHost(resolved(steps), {"XAUUSD": XAU}, execution=execution)
        if subprocess
        else InProcessHost(resolved(steps), {"XAUUSD": XAU}, execution=execution)
    )
    host.start()
    got = [o for batch in bars for o in host.on_bars(batch)]
    host.stop()
    assert host.fault is None

    def comparable(outputs: list[RunnerOutput]) -> list[tuple[Any, ...]]:
        return [(o.time, o.signals, o.events, o.book_reasons, o.book) for o in outputs]

    assert comparable(got) == comparable(expected)
    assert any(o.book is not None and o.book.position is not None for o in got)
