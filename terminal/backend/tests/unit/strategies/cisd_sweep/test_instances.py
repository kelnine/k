"""``config/instances.d/cisd_sweep.yaml``: the doc 13 D7/D10/D11 instances of S6, and a lab
run of all of them side by side on synthetic data (each on its own Paper 50K account)."""

from collections import Counter

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

STRATEGY = "cisd_sweep"
WINDOWS = {"any": "Any time", "nyam": "NY AM", "lonny": "London + NY AM"}
IDS = [
    "cisd_sweep_any_tp1_5m",
    "cisd_sweep_any_tp2_5m",
    "cisd_sweep_nyam_tp1_5m",
    "cisd_sweep_nyam_tp2_5m",
    "cisd_sweep_lonny_tp1_5m",
    "cisd_sweep_lonny_tp2_5m",
    "cisd_sweep_any_market_5m",
]


def test_instances_cover_three_windows_two_targets_and_the_market_comparison() -> None:
    entries = instance_entries(STRATEGY)
    assert [e["id"] for e in entries] == IDS
    for entry in entries:
        window, leg = entry["id"].removeprefix(STRATEGY + "_").removesuffix("_5m").split("_")
        assert entry["strategy"] == STRATEGY and entry["timeframe"] == "5m"
        assert tuple(entry["instruments"]) == ALL_14
        assert entry["account"] == {"max_open_positions": 14}
        assert "on_opposite_signal" not in entry and "skip_entry_beyond_levels" not in entry
        market = leg == "market"
        assert entry["params"] == {
            "sig_window": WINDOWS[window],
            "entry": "market" if market else "limit",
            "target": "tp2" if market else leg,
        }


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
        assert resolved.position_rules.skip_entry_beyond_levels is True
        assert [tf.code for tf in resolved.timeframes] == ["5m"]
        versions.add(resolved.version)
    assert len(versions) == len(IDS)  # each variant is its own version


async def test_every_instance_runs_in_the_lab_without_faults() -> None:
    result, store = await lab_smoke(STRATEGY)
    assert_clean_lab_run(result, store, IDS)
    signals = [r.signal for r in store.of(SignalRecord) if r.signal is not None]
    by_instance = Counter(s.strategy_id for s in signals if s.signal.is_entry)
    assert set(by_instance) == set(IDS)
    triggers = {str(s.metadata.get("trigger")) for s in signals}
    assert {"Bullish CISD", "Bearish CISD", "order cancelled", "trade replaced"} <= triggers
    kinds = {
        (s.strategy_id.endswith("market_5m"), s.order_type) for s in signals if s.signal.is_entry
    }
    assert kinds == {(False, OrderType.LIMIT), (True, OrderType.MARKET)}
    # every cancel of a resting limit and every replace exit found its order or position
    exits = {r.id for r in store.of(SignalRecord) if r.signal and r.signal.signal.is_exit}
    decided = [d for d in store.of(DecisionRecord) if d.signal_id in exits]
    assert decided
    refused = [d for d in decided if not d.approved]
    assert len(refused) <= len(decided) // 20, refused[:3]  # see the README (bid/ask fills)
