"""``config/instances.d/ict_model_b.yaml``: the doc 13 D6/D10 instances of Model B, and a lab
run of all of them side by side on synthetic data (each on its own Paper 50K account)."""

from kterminal.paper.records import SignalRecord
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

STRATEGY = "ict_model_b"
IDS = ["ict_model_b_main_1m", "ict_model_b_flat_1m"]


def test_instances_hold_and_flatten_on_1m_for_all_14_instruments() -> None:
    entries = instance_entries(STRATEGY)
    assert [e["id"] for e in entries] == IDS
    for entry in entries:
        variant = entry["id"].removeprefix(STRATEGY + "_").split("_")[0]
        assert entry["strategy"] == STRATEGY and entry["timeframe"] == "1m"
        assert entry["params"] == {"after_window": "hold" if variant == "main" else "flat"}
        assert tuple(entry["instruments"]) == ALL_14
        assert entry["account"] == {"max_open_positions": 14}
        assert "on_opposite_signal" not in entry  # D4: the definition's "ignore"


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
        assert resolved.position_rules.on_opposite_signal == "ignore"
        assert resolved.position_rules.skip_entry_beyond_levels is False  # limits only
        assert [tf.code for tf in resolved.timeframes] == ["1m"]
        versions.add(resolved.version)
    assert len(versions) == len(IDS)  # the variant is part of the version


async def test_every_instance_runs_in_the_lab_without_faults() -> None:
    result, store = await lab_smoke(STRATEGY)
    assert_clean_lab_run(result, store, IDS)
    triggers = {str(r.signal.metadata.get("trigger")) for r in store.of(SignalRecord)}
    assert {"B long setup", "B short setup"} <= triggers
