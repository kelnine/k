"""``config/instances.d/ict_model_c.yaml``: the doc 13 D6/D10 instances of Model C, and a lab
run of all of them side by side on synthetic data (each on its own Paper 50K account)."""

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

STRATEGY = "ict_model_c"
IDS = ["ict_model_c_main_1m", "ict_model_c_flat_1m"]


def test_instances_hold_and_flatten_on_1m_for_all_14_instruments() -> None:
    entries = instance_entries(STRATEGY)
    assert [e["id"] for e in entries] == IDS
    for entry in entries:
        variant = entry["id"].removeprefix(STRATEGY + "_").split("_")[0]
        assert entry["strategy"] == STRATEGY and entry["timeframe"] == "1m"
        assert entry["params"] == {"after_window": "hold" if variant == "main" else "flat"}
        assert entry["context_timeframes"] == ["5m", "1h"]
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
        assert resolved.position_rules.skip_entry_beyond_levels is True  # D3
        assert [tf.code for tf in resolved.timeframes] == ["1m", "5m", "1h"]
        versions.add(resolved.version)
    assert len(versions) == len(IDS)  # the variant is part of the version


async def test_every_instance_runs_in_the_lab_without_faults() -> None:
    result, store = await lab_smoke(STRATEGY)
    assert_clean_lab_run(result, store, IDS)
    signals = [r.signal for r in store.of(SignalRecord) if r.signal is not None]
    triggers = {str(s.metadata.get("trigger")) for s in signals}
    assert {"C long", "C short"} <= triggers
    # every time exit (ctx.flatten) that reached an account closed something there
    flattens = {r.id for r in store.of(SignalRecord) if r.signal and r.signal.signal.is_flatten}
    flattened = [d for d in store.of(DecisionRecord) if d.signal_id in flattens]
    assert flattens and all(d.approved for d in flattened)
    # the books resolve like the accounts: any divergence is an account's refusal
    assert result.consistency["unexplained_episodes"] == 0, result.consistency["examples"]
