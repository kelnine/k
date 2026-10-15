"""``config/instances.d/cisd_scanner.yaml``: the doc 13 D7/D10/D11 instances of S10, and a lab
run of all of them side by side on synthetic data (each on its own Paper 50K account)."""

from kterminal.core.enums import OrderType
from kterminal.paper.records import DecisionRecord, SignalRecord
from kterminal.strategy_engine import resolve_instance
from kterminal.strategy_engine.registry import DEFINITIONS, discover_strategies
from tests.unit.strategies.pine_port_support import (
    ALL_14,
    assert_clean_lab_run,
    forward_config,
    instance_entries,
    lab_smoke,
    real_catalog,
)

STRATEGY = "cisd_scanner"
IDS = [
    "cisd_scanner_plain_tp1_5m",
    "cisd_scanner_plain_tp2_5m",
    "cisd_scanner_aplus_tp1_5m",
    "cisd_scanner_aplus_tp2_5m",
]


def test_instances_are_plain_and_a_plus_with_two_targets() -> None:
    entries = instance_entries(STRATEGY)
    assert [e["id"] for e in entries] == IDS
    for entry in entries:
        grade, leg = entry["id"].removeprefix(STRATEGY + "_").removesuffix("_5m").split("_")
        assert entry["strategy"] == STRATEGY and entry["timeframe"] == "5m"
        assert entry["context_timeframes"] == ["15m", "1h", "4h"]
        assert tuple(entry["instruments"]) == ALL_14
        assert entry["account"] == {"max_open_positions": 14}
        assert entry["params"] == {"aplus_only": grade == "aplus", "entry": "limit", "target": leg}


def test_forward_trading_loads_and_resolves_every_instance() -> None:
    discover_strategies(entry_points=False)
    config = forward_config()
    catalog = real_catalog()
    loaded = {i.id: i for i in config.instances}
    versions = set()
    for instance_id in IDS:
        spec = config.instance_spec(loaded[instance_id])
        resolved = resolve_instance(
            spec,
            instruments={s: catalog.instrument(s) for s in spec.instruments},
            sessions=catalog.sessions,
            definitions=DEFINITIONS,
        )
        assert resolved.position_rules.on_opposite_signal == "reverse"
        assert [tf.code for tf in resolved.timeframes] == ["5m", "15m", "1h", "4h"]
        versions.add(resolved.version)
    assert len(versions) == len(IDS)


async def test_every_instance_runs_in_the_lab_without_faults() -> None:
    result, store = await lab_smoke(STRATEGY, days=4)
    assert_clean_lab_run(result, store, IDS)
    signals = [r.signal for r in store.of(SignalRecord) if r.signal is not None]
    entries = [s for s in signals if s.signal.is_entry]
    assert {s.order_type for s in entries} == {OrderType.LIMIT}
    aplus = {s.strategy_id for s in entries if s.metadata["aplus"]}
    assert aplus == set(IDS)  # A+ signals happen, and plain instances take them too
    assert all(s.metadata["aplus"] for s in entries if "aplus" in s.strategy_id)
    exits = {r.id for r in store.of(SignalRecord) if r.signal and r.signal.signal.is_exit}
    decided = [d for d in store.of(DecisionRecord) if d.signal_id in exits]
    assert decided
    refused = [d for d in decided if not d.approved]
    assert len(refused) <= len(decided) // 20, refused[:3]  # bid/ask fills (README)
