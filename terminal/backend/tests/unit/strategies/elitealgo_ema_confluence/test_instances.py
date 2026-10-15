"""``config/instances.d/elitealgo_ema_confluence.yaml``: the doc 13 D4/D10 instances, and a
lab run of all of them side by side on synthetic data (each on its own Paper 50K account)."""

from kterminal.strategy_engine import InstanceSpec, resolve_instance
from kterminal.strategy_engine.registry import DEFINITIONS, discover_strategies
from tests.unit.strategies.pine_port_support import (
    ALL_14,
    assert_clean_lab_run,
    forward_config,
    instance_entries,
    lab_smoke,
    real_catalog,
)

STRATEGY = "elitealgo_ema_confluence"
IDS = [
    "elitealgo_ema_confluence_main_5m",
    "elitealgo_ema_confluence_main_15m",
    "elitealgo_ema_confluence_reverse_5m",
    "elitealgo_ema_confluence_reverse_15m",
]


def test_instances_cover_both_policies_on_5m_and_15m_for_all_14_instruments() -> None:
    entries = instance_entries(STRATEGY)
    assert [e["id"] for e in entries] == IDS
    for entry in entries:
        assert entry["strategy"] == STRATEGY
        assert tuple(entry["instruments"]) == ALL_14
        assert entry["id"].endswith("_" + entry["timeframe"])
        assert entry["account"] == {"max_open_positions": 14}  # one position per instrument
        assert "params" not in entry  # D13: the script's defaults
        reverse = "_reverse_" in entry["id"]
        assert entry.get("on_opposite_signal") == ("reverse" if reverse else None)


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
        rules = resolved.position_rules
        expected = "reverse" if "_reverse_" in instance_id else "ignore"
        assert rules.on_opposite_signal == expected
        assert rules.skip_entry_beyond_levels is True
        assert config.account_settings(loaded[instance_id]).max_open_positions == 14


async def test_every_instance_runs_in_the_lab_without_faults() -> None:
    result, store = await lab_smoke(STRATEGY)
    assert_clean_lab_run(result, store, IDS)
