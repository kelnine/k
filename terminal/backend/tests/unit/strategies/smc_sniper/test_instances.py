"""``config/instances.d/smc_sniper.yaml``: the doc 13 D10/D11 instances, and a lab run of
all of them side by side on synthetic data (each on its own Paper 50K account)."""

from kterminal.paper.records import FaultRecord, SignalRecord
from kterminal.strategies.smc_sniper import SmcSniperParams
from kterminal.strategy_engine import InstanceSpec, resolve_instance
from kterminal.strategy_engine.registry import DEFINITIONS, discover_strategies
from tests.unit.strategies.pine_port_support import (
    ALL_14,
    forward_config,
    instance_entries,
    lab_smoke,
    real_catalog,
)

STRATEGY = "smc_sniper"
IDS = [
    "smc_sniper_min3_15m",
    "smc_sniper_min4_15m",
    "smc_sniper_min3_5m",
    "smc_sniper_min4_5m",
]


def test_instances_cover_min_score_3_and_4_on_15m_and_5m_for_all_14_instruments() -> None:
    entries = instance_entries(STRATEGY)
    assert [e["id"] for e in entries] == IDS
    for entry in entries:
        assert entry["strategy"] == STRATEGY
        assert tuple(entry["instruments"]) == ALL_14
        assert entry["id"].endswith("_" + entry["timeframe"])
        assert entry["account"] == {"max_open_positions": 14}  # one position per instrument
        params = SmcSniperParams.model_validate(entry["params"])
        assert entry["id"].startswith(f"smc_sniper_min{params.sniper_min}_")
        # D13: everything but Min Score at the script's defaults
        assert params == SmcSniperParams(sniper_min=params.sniper_min)
        assert "on_opposite_signal" not in entry  # D4: the definition's ignore


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
        assert config.account_settings(loaded[instance_id]).max_open_positions == 14


async def test_every_instance_runs_in_the_lab_without_faults() -> None:
    result, store = await lab_smoke(STRATEGY)
    assert [a.instance_id for a in result.accounts] == IDS
    assert store.of(FaultRecord) == []
    for account in result.accounts:
        assert account.fault is None, account
        assert account.balance == account.starting_balance + account.summary.net_pnl
    signals = store.of(SignalRecord)
    by_instance = {i: [r.signal for r in signals if r.instance_id == i] for i in IDS}
    # Min Score 3 signals on both timeframes. Min Score 4 needs the trend point (EMA200)
    # and a zone on the BOS bar, so three synthetic days may hold none: whatever it
    # emits is a 4/4 signal.
    assert by_instance["smc_sniper_min3_15m"] and by_instance["smc_sniper_min3_5m"]
    for instance_id in ("smc_sniper_min4_15m", "smc_sniper_min4_5m"):
        assert all(s.metadata["score"] == 4 for s in by_instance[instance_id])
