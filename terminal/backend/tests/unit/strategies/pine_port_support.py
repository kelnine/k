"""Shared helpers for the Pine-port strategy tests (S1 EliteAlgo, S7 SuperTrend, S8 PSAR).

Bar builders for hand-made sequences, a ``run`` wrapper around the real runner
(``kterminal.strategy_engine.testing.run_strategy``) with the catalog's session
book, and the lab smoke run of a strategy's ``config/instances.d`` file on
synthetic data with the real 14-instrument catalog.
"""

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from kterminal.core.enums import Direction, SignalAction
from kterminal.domain.catalog import InstrumentCatalog
from kterminal.domain.instruments import Instrument
from kterminal.domain.market import Bar
from kterminal.domain.signals import Signal
from kterminal.domain.timeframes import Timeframe
from kterminal.paper.config import LabConfig, load_forward_config
from kterminal.paper.demo import demo_bars
from kterminal.paper.lab import Lab, LabResult
from kterminal.paper.records import FaultRecord, SignalRecord
from kterminal.paper.store import InMemoryLabStore
from kterminal.strategy_engine import CloseReason, PositionEvent, PositionEventKind, Strategy
from kterminal.strategy_engine.registry import discover_strategies
from kterminal.strategy_engine.testing import StrategyTestResult, run_strategy
from tests.fixtures.catalog import lab_catalog
from tests.fixtures.instruments import T0, XAUUSD

CONFIG_DIR = Path(__file__).resolve().parents[4] / "config"
INSTANCES_DIR = CONFIG_DIR / "instances.d"
SESSIONS = lab_catalog().sessions

# The 14 instruments of doc 13 D1/D10 (the catalog's NQ is not one of them).
ALL_14 = (
    "XAUUSD",
    "XAGUSD",
    "NAS100",
    "US30",
    "US500",
    "MNQ",
    "EURUSD",
    "GBPUSD",
    "BTCUSD",
    "SOLUSD",
    "NEARUSD",
    "ZECUSD",
    "HYPEUSD",
    "PUMPUSD",
)

Row = tuple[float, float, float, float] | tuple[float, float, float, float, float]


def make_bars(
    rows: Sequence[Row],
    *,
    start: datetime = T0,
    timeframe: str = "5m",
    instrument: str = "XAUUSD",
    volume: float = 100,
) -> list[Bar]:
    """Consecutive bars from ``(open, high, low, close[, volume])`` rows."""
    tf = Timeframe.parse(timeframe)
    out = []
    for i, row in enumerate(rows):
        o, h, low, c = row[:4]
        v = row[4] if len(row) == 5 else volume
        out.append(
            Bar.of(instrument, tf, start + i * tf.duration, repr(o), repr(h), repr(low), repr(c), v)
        )
    return out


def path_bars(
    closes: Sequence[float],
    *,
    wick: float = 0.5,
    start: datetime = T0,
    timeframe: str = "5m",
    instrument: str = "XAUUSD",
    volume: float = 100,
) -> list[Bar]:
    """Bars following a close path: open = previous close, wicks of ``wick`` beyond the body."""
    rows: list[Row] = []
    previous = closes[0]
    for close in closes:
        o = previous
        rows.append((o, max(o, close) + wick, min(o, close) - wick, close))
        previous = close
    return make_bars(rows, start=start, timeframe=timeframe, instrument=instrument, volume=volume)


def run(
    strategy: type[Strategy[Any]],
    bars: Sequence[Bar],
    *,
    params: dict[str, Any] | None = None,
    instrument: Instrument = XAUUSD,
    timeframe: str = "5m",
    **kwargs: Any,
) -> StrategyTestResult:
    """The strategy through the real runner, with the catalog's session book."""
    return run_strategy(
        strategy,
        instrument=instrument,
        bars=bars,
        timeframe=timeframe,
        params=params,
        sessions=SESSIONS,
        **kwargs,
    )


def index_of(signal: Signal, *, start: datetime = T0, timeframe: str = "5m") -> int:
    """Position of the signal's bar in a gap-free sequence that starts at ``start``."""
    assert signal.bar_time is not None
    return int((signal.bar_time - start) / Timeframe.parse(timeframe).duration)


def actions(
    result: StrategyTestResult, *, start: datetime = T0, timeframe: str = "5m"
) -> list[tuple[int, SignalAction]]:
    """``(bar index, action)`` of every signal of a run over a gap-free sequence."""
    return [(index_of(s, start=start, timeframe=timeframe), s.signal) for s in result.signals]


def of_kind(result: StrategyTestResult, kind: PositionEventKind) -> list[PositionEvent]:
    return [e for e in result.events if e.kind is kind]


def entries(result: StrategyTestResult) -> list[Signal]:
    return [s for s in result.signals if s.signal.is_entry]


def positions_at_decisions(bars: list[Bar], events: list[PositionEvent]) -> list[Direction | None]:
    """The theoretical position each ``on_bar`` saw. Fills, cancels and signal exits happen
    at a bar's open (event time = its open), stops and targets inside it (its close)."""
    by_open = {bar.open_time: i for i, bar in enumerate(bars)}
    by_close = {bar.close_time: i for i, bar in enumerate(bars)}
    per_bar: dict[int, list[PositionEvent]] = {}
    for event in events:
        if event.kind is PositionEventKind.STOP_MOVED:
            continue
        intrabar = event.kind is PositionEventKind.CLOSED and event.reason in (
            CloseReason.STOP_LOSS,
            CloseReason.TAKE_PROFIT,
        )
        bar = by_close[event.time] if intrabar else by_open[event.time]
        per_bar.setdefault(bar, []).append(event)
    held: Direction | None = None
    out: list[Direction | None] = []
    for i in range(len(bars)):
        for event in per_bar.get(i, []):
            if event.kind is PositionEventKind.OPENED:
                held = event.direction
            elif event.kind is PositionEventKind.CLOSED:
                held = None
        out.append(held)
    return out


def strategy_object(result: StrategyTestResult) -> Any:
    """The strategy instance the runner drove (to inspect its indicator state)."""
    assert result.runner is not None
    return result.runner._strategy


def dumps(result: StrategyTestResult) -> list[dict[str, Any]]:
    return [s.model_dump(mode="json") for s in result.signals]


# ── lab smoke runs on the real catalog ───────────────────────────────────────────


@cache
def real_catalog() -> InstrumentCatalog:
    return InstrumentCatalog.load(CONFIG_DIR / "catalog")


def instance_entries(strategy_id: str) -> list[dict[str, Any]]:
    """The instance list of ``config/instances.d/<strategy_id>.yaml``."""
    data = yaml.safe_load((INSTANCES_DIR / f"{strategy_id}.yaml").read_text(encoding="utf-8"))
    assert isinstance(data, list)
    return data


def forward_config() -> LabConfig:
    """What forward paper trading loads: ``lab.yaml`` plus every ``instances.d`` file."""
    return load_forward_config(CONFIG_DIR / "lab.yaml")


async def lab_smoke(strategy_id: str, *, days: float = 3) -> tuple[LabResult, InMemoryLabStore]:
    """Run every instance of the strategy's ``instances.d`` file side by side in the lab,
    each on its own Paper 50K account, on synthetic 1-minute bars of its instruments."""
    discover_strategies(entry_points=False)
    defaults = forward_config().defaults
    config = LabConfig.model_validate(
        {"defaults": defaults.model_dump(mode="json"), "instances": instance_entries(strategy_id)}
    )
    catalog = real_catalog()
    store = InMemoryLabStore()
    result = await Lab(config, catalog, store, discover=False).run(
        demo_bars(catalog, config, days=days)
    )
    return result, store


def assert_clean_lab_run(result: LabResult, store: InMemoryLabStore, ids: Sequence[str]) -> None:
    """Every instance ran to the end without a fault, signalled, and kept its own account."""
    assert [a.instance_id for a in result.accounts] == list(ids)
    assert store.of(FaultRecord) == []
    for account in result.accounts:
        assert account.fault is None, account
        assert account.signals > 0, account.instance_id
        assert account.balance == account.starting_balance + account.summary.net_pnl
    signal_instances = {r.instance_id for r in store.of(SignalRecord)}
    assert signal_instances == set(ids)


def as_float(value: Decimal | None) -> float:
    assert value is not None
    return float(value)
