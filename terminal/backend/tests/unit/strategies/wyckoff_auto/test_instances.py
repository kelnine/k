"""``config/instances.d/wyckoff_auto.yaml``: the doc 13 D9/D10/D11 instances; a lab run of
all of them side by side on synthetic data (each on its own Paper 50K account); and the
campaigns of the scenario tapes traded through the lab, minute by minute, at bid/ask."""

from decimal import Decimal
from typing import Any

from kterminal.domain.timeframes import Timeframe
from kterminal.marketdata.aggregator import aggregate_stream
from kterminal.paper.config import LabConfig
from kterminal.paper.lab import Lab
from kterminal.paper.records import FaultRecord, SignalRecord, TradeRecord
from kterminal.paper.store import InMemoryLabStore
from kterminal.strategies.wyckoff_auto import WyckoffAutoParams
from kterminal.strategy_engine import InstanceSpec, resolve_instance
from kterminal.strategy_engine.registry import DEFINITIONS, discover_strategies
from tests.unit.strategies.pine_port_support import (
    ALL_14,
    forward_config,
    instance_entries,
    lab_smoke,
    real_catalog,
)
from tests.unit.strategies.wyckoff_auto.scenario import minute_bars, stitched

STRATEGY = "wyckoff_auto"
EXCHANGE = ("MNQ", "BTCUSD", "SOLUSD", "NEARUSD", "ZECUSD", "HYPEUSD", "PUMPUSD")
TICK = ("XAUUSD", "XAGUSD", "NAS100", "US30", "US500", "EURUSD", "GBPUSD")
# variant id → (Entry Strictness, target, timeframes)
VARIANTS = {
    "standard": ("Standard", "structure", ("5m", "15m", "1h")),
    "conservative": ("Conservative", "structure", ("15m",)),
    "aggressive": ("Aggressive", "structure", ("15m",)),
    "standard_2r": ("Standard", "2R", ("15m",)),
}
IDS = [
    f"{STRATEGY}_{variant}_{tf}{suffix}"
    for variant, (_, _, tfs) in VARIANTS.items()
    for tf in tfs
    for suffix in ("", "_tickvol")
]


def test_instances_cover_d10_d11_with_the_tick_volume_runs_named() -> None:
    entries = instance_entries(STRATEGY)
    assert [e["id"] for e in entries] == IDS
    assert len(IDS) == 12
    for entry in entries:
        assert entry["strategy"] == STRATEGY
        tick = entry["id"].endswith("_tickvol")
        # D9: the tick-volume feeds run apart and say so in their name
        assert tuple(entry["instruments"]) == (TICK if tick else EXCHANGE)
        assert ("tick volume" in entry["name"]) is tick
        assert ("tick-volume" in entry["tags"]) is tick
        assert entry["account"] == {"max_open_positions": 7}  # one position per instrument
        variant = entry["id"].removeprefix(f"{STRATEGY}_").removesuffix("_tickvol")
        variant, tf = variant.rsplit("_", 1)
        strictness, target, timeframes = VARIANTS[variant]
        assert entry["timeframe"] == tf and tf in timeframes
        params = WyckoffAutoParams.model_validate(entry["params"])
        # D13: only the strictness and the D5 variant differ from the defaults
        assert params == WyckoffAutoParams(entry_strictness=strictness, target=target)
        assert "on_opposite_signal" not in entry  # D4: the definition's ignore
    assert sorted(TICK + EXCHANGE) == sorted(ALL_14)


def test_forward_trading_loads_and_resolves_every_instance() -> None:
    discover_strategies(entry_points=False)
    config = forward_config()
    catalog = real_catalog()
    loaded = {i.id: i for i in config.instances}
    for instance_id in IDS:
        spec: InstanceSpec = config.instance_spec(loaded[instance_id])
        resolved = resolve_instance(
            spec,
            instruments={s: catalog.instrument(s) for s in spec.instruments},
            sessions=catalog.sessions,
            definitions=DEFINITIONS,
        )
        assert resolved.position_rules.on_opposite_signal == "ignore"
        assert resolved.position_rules.skip_entry_beyond_levels is True
        assert config.account_settings(loaded[instance_id]).max_open_positions == 7


async def test_every_instance_runs_in_the_lab_without_faults() -> None:
    """Three synthetic days: uniform random volume makes no climax, so the instances may
    hold no campaign yet — every one runs, audits and keeps its own account."""
    result, store = await lab_smoke(STRATEGY)
    assert [a.instance_id for a in result.accounts] == IDS
    assert store.of(FaultRecord) == []
    for account in result.accounts:
        assert account.fault is None, account
        assert account.balance == account.starting_balance + account.summary.net_pnl
    assert result.consistency["unexplained_episodes"] == 0, result.consistency["examples"]


def test_the_minute_bars_aggregate_back_to_the_tape() -> None:
    tape = stitched()
    minutes = minute_bars(tape, instrument="BTCUSD")
    m1, m15_tf = Timeframe.parse("1m"), Timeframe.parse("15m")
    m15 = [
        b
        for batch in aggregate_stream(minutes, m1, (m15_tf,))
        for b in batch
        if b.timeframe == m15_tf
    ]
    assert len(m15) == len(tape.rows)
    for bar, (o, h, low, c, v) in zip(m15, tape.rows, strict=True):
        assert (bar.open, bar.high, bar.low, bar.close) == tuple(
            Decimal(repr(x)) for x in (o, h, low, c)
        )
        assert bar.volume == Decimal(int(v))


LAB_IDS = [
    "wyckoff_auto_standard_15m",
    "wyckoff_auto_conservative_15m",
    "wyckoff_auto_standard_2r_15m",
]


def tape_lab_config() -> LabConfig:
    """Three 15m instances of the file, on BTCUSD only (a 24/7 market for the tape)."""
    entries: list[dict[str, Any]] = []
    for entry in instance_entries(STRATEGY):
        if entry["id"] in LAB_IDS:
            entries.append(
                {**entry, "instruments": ["BTCUSD"], "account": {"max_open_positions": 1}}
            )
    defaults = forward_config().defaults.model_dump(mode="json")
    return LabConfig.model_validate({"defaults": defaults, "instances": entries})


async def test_the_scenario_campaigns_trade_through_the_lab() -> None:
    discover_strategies(entry_points=False)
    store = InMemoryLabStore()
    result = await Lab(tape_lab_config(), real_catalog(), store, discover=False).run(
        minute_bars(stitched(), instrument="BTCUSD")
    )
    assert store.of(FaultRecord) == []
    assert [a.instance_id for a in result.accounts] == LAB_IDS
    signals = store.of(SignalRecord)
    for instance_id in LAB_IDS:
        mine = [r.signal for r in signals if r.instance_id == instance_id and r.signal]
        entries = [s for s in mine if s.signal.is_entry]
        exits = [s for s in mine if s.signal.value == "FLATTEN"]
        assert entries and exits, instance_id
        assert {s.metadata["exit_event"] for s in exits} <= {
            "INVALIDATION",
            "DEMOTION",
            "PHASE_E_FAILURE",
            "PHASE_E_TIMEOUT",
            "REPLACED_BY_CLIMAX",
        }
    for account in result.accounts:
        assert account.fault is None
        assert account.balance == account.starting_balance + account.summary.net_pnl
    trades = [t for t in store.of(TradeRecord) if t.status == "CLOSED"]
    assert {t.exit_reason for t in trades} >= {"SIGNAL_EXIT"}
    standard = [t for t in trades if t.instance_id == "wyckoff_auto_standard_15m"]
    assert len(standard) >= 5
    two_r = [t for t in trades if t.instance_id == "wyckoff_auto_standard_2r_15m"]
    assert all(t.initial_target is not None for t in two_r)
    # the books resolve like the accounts: any divergence is an account's refusal
    assert result.consistency["checks"] > 0
    assert result.consistency["unexplained_episodes"] == 0, result.consistency["examples"]
