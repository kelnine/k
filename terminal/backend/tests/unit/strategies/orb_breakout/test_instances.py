"""``config/instances.d/orb_breakout.yaml``: the doc 13 D5/D10/D11 instances, and a lab run
of all of them side by side on synthetic data (each on its own Paper 50K account)."""

from decimal import Decimal

from kterminal.strategies.orb_breakout import OrbParams
from kterminal.strategy_engine import InstanceSpec, resolve_instance
from kterminal.strategy_engine.registry import DEFINITIONS, discover_strategies
from tests.unit.strategies.pine_port_support import (
    assert_clean_lab_run,
    forward_config,
    instance_entries,
    lab_smoke,
    real_catalog,
)

STRATEGY = "orb_breakout"
NY_INDICES = ("MNQ", "NAS100", "US30", "US500")
LONDON_SET = ("XAUUSD", "EURUSD", "GBPUSD", "NAS100", "US30", "US500")
# id → (stop_mode, target_r)
EXITS = {
    "orb_breakout_ny_5m": ("range", Decimal(2)),
    "orb_breakout_ny_mid1r_5m": ("midpoint", Decimal(1)),
    "orb_breakout_ny_mid1p5r_5m": ("midpoint", Decimal("1.5")),
    "orb_breakout_ny_mideod_5m": ("midpoint", None),
    "orb_breakout_london_5m": ("range", Decimal(2)),
}
IDS = list(EXITS)


def test_instances_cover_the_d5_exits_and_the_london_variant_on_5m() -> None:
    entries = instance_entries(STRATEGY)
    assert [e["id"] for e in entries] == IDS
    for entry in entries:
        assert entry["strategy"] == STRATEGY
        assert entry["timeframe"] == "5m"
        assert entry["id"].endswith("_5m")
        params = OrbParams.model_validate(entry.get("params", {}))
        assert (params.stop_mode, params.target_r) == EXITS[entry["id"]]
        # the script's signal inputs stay at their defaults (D13)
        assert (params.or_filter, params.fast_length, params.slow_length) == (True, 9, 20)
        london = "_london_" in entry["id"]
        instruments = LONDON_SET if london else NY_INDICES
        assert tuple(entry["instruments"]) == instruments
        assert entry["account"] == {"max_open_positions": len(instruments)}
        if london:
            assert (params.timezone, params.or_session, params.levels_session) == (
                "Europe/London",
                "0800-0815:1234567",
                "0800-1630:1234567",
            )
            assert params.flatten_time == "16:30"
        else:
            assert params == OrbParams(stop_mode=params.stop_mode, target_r=params.target_r)
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
        settings = config.account_settings(loaded[instance_id])
        assert settings.max_open_positions == len(spec.instruments)


async def test_every_instance_runs_in_the_lab_without_faults() -> None:
    result, store = await lab_smoke(STRATEGY)
    assert_clean_lab_run(result, store, IDS)
    # the books resolve like the accounts: any divergence is an account's refusal
    assert result.consistency["unexplained_episodes"] == 0, result.consistency["examples"]
    # and none outlives the day: the daily flatten closes what either side still holds
    assert result.consistency["open_episodes"] == 0
