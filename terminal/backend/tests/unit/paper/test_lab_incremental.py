"""The lab driven minute by minute is the lab run in one go; kill switches stop entries."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from kterminal.core.registry import Registry
from kterminal.domain.accounts import AccountSettings
from kterminal.domain.market import Bar
from kterminal.marketdata.synthetic import merge_streams, synthetic_bars
from kterminal.paper.config import LabConfig
from kterminal.paper.ids import SessionIds
from kterminal.paper.kill_switch import ActiveSwitch, KillSwitchState
from kterminal.paper.lab import AccountOpening, Lab
from kterminal.paper.records import (
    DecisionRecord,
    OrderRecord,
    SignalRecord,
    TradeRecord,
)
from kterminal.paper.store import InMemoryLabStore, ProvisionedAccount
from kterminal.strategy_engine.registry import (
    DEFINITIONS,
    StrategyDefinition,
    definition_from_class,
    discover_strategies,
)
from tests.fixtures.catalog import lab_catalog
from tests.fixtures.strategies import Scripted

discover_strategies(entry_points=False)

# Monday 5 January 2026 20:30 UTC: gold pauses 22:00-23:00 UTC, NEAR trades on.
START = datetime(2026, 1, 5, 20, 30, tzinfo=UTC)
MIN = timedelta(minutes=1)
RUN_ID = UUID(int=1)


class FixedIdStore(InMemoryLabStore):
    """Run and account ids from a counter, so two labs on the same bars record the same."""

    def __init__(self) -> None:
        super().__init__()
        self._next = 100

    async def start_run(self, **kwargs: Any) -> UUID:
        await super().start_run(**kwargs)
        run = next(iter(self.runs.values()))
        self.runs = {RUN_ID: run}
        return RUN_ID

    async def provision_account(
        self,
        *,
        instance_id: str,
        name: str,
        settings: AccountSettings,
        run_id: UUID | None = None,
        opened_at: datetime | None = None,
    ) -> ProvisionedAccount:
        self._next += 2
        account = ProvisionedAccount(UUID(int=self._next), UUID(int=self._next + 1), name, True)
        self.run_accounts.setdefault(run_id or RUN_ID, {})[instance_id] = account
        self.starting_balances[account.account_id] = settings.starting_balance
        return account


def registry() -> Registry[StrategyDefinition]:
    reg: Registry[StrategyDefinition] = Registry("strategy definition")
    for definition_id, definition in DEFINITIONS.items():
        reg.register(definition_id, definition)
    scripted = definition_from_class(Scripted)
    reg.register(scripted.id, scripted)
    return reg


def market(minutes: int = 240) -> list[Bar]:
    catalog = lab_catalog()
    gold = synthetic_bars(
        "XAUUSD",
        start=START,
        count=minutes,
        start_price=Decimal("4000.00"),
        tick_size=Decimal("0.01"),
        seed=5,
        is_open=catalog.sessions.calendar("metals_otc").is_open,
        volatility=0.002,
    )
    near = synthetic_bars(
        "NEARUSD",
        start=START,
        count=minutes,
        start_price=Decimal("3.000"),
        tick_size=Decimal("0.001"),
        seed=6,
        volatility=0.002,
    )
    end = START + minutes * MIN
    return [b for b in merge_streams(gold, near) if b.open_time < end]


CONFIG = LabConfig.model_validate(
    {
        "equity_snapshot_minutes": 5,
        "instances": [
            {
                "id": "sma_gold",
                "strategy": "demo_sma_cross",
                "params": {"fast": 3, "slow": 8},
                "instruments": ["XAUUSD"],
                "timeframe": "1m",
                "context_timeframes": ["5m", "15m"],
            },
            {
                "id": "breakout_near",
                "strategy": "demo_breakout",
                "params": {"channel_bars": 5, "trend_filter": False},
                "instruments": ["NEARUSD"],
                "timeframe": "5m",
            },
            {
                "id": "scripted_both",
                "strategy": "scripted",
                "params": {
                    "long_on": [3, 40, 90],
                    "exit_long_on": [20],
                    "move_sl_on": [50],
                    "stop_distance": "0.5",
                    "target_distance": "1",
                },
                "instruments": ["XAUUSD", "NEARUSD"],
                "timeframe": "1m",
            },
        ],
    }
)


def records(store: InMemoryLabStore) -> dict[str, list[Any]]:
    return {kind.__name__: list(rows) for kind, rows in store.records.items()}


def by_minute(bars: Sequence[Bar]) -> list[list[Bar]]:
    groups: dict[datetime, list[Bar]] = {}
    for bar in bars:
        groups.setdefault(bar.open_time, []).append(bar)
    return [groups[t] for t in sorted(groups)]


async def test_incremental_processing_records_exactly_what_lab_run_records() -> None:
    bars = market()
    warm, live = bars[:60], bars[60:]

    run_store = FixedIdStore()
    run_lab = Lab(CONFIG, lab_catalog(), run_store, definitions=registry(), ids=SessionIds(9))
    result = await run_lab.run(live, warmup_bars=warm)

    inc_store = FixedIdStore()
    inc_lab = Lab(CONFIG, lab_catalog(), inc_store, definitions=registry(), ids=SessionIds(9))
    run_id = await inc_store.start_run(
        kind="LAB_SIMULATION",
        name="lab",
        config={},
        catalog_document={},
        catalog_fingerprint="x",
        started_at=warm[0].open_time,
    )
    await inc_lab.begin(run_id, warmup_bars=warm, started_at=warm[0].open_time)
    minutes = by_minute(live)
    for index, group in enumerate(minutes):  # a live feed advances after every minute
        last = index == len(minutes) - 1
        await inc_lab.process_bars(group, through=None if last else group[0].close_time)
    incremental = await inc_lab.end()

    assert records(inc_store) == records(run_store)
    assert incremental.batches == result.batches > 150
    assert [a.summary for a in incremental.accounts] == [a.summary for a in result.accounts]
    trades = [r for r in run_store.of(TradeRecord) if r.status == "CLOSED"]
    assert len({t.instance_id for t in trades}) == 3  # every instance traded


WIDE_GOLD = {"stop_distance": "150", "target_distance": "400"}
WIDE_NEAR = {"stop_distance": "2", "target_distance": "5"}


def scripted_config(gold: dict[str, Any], near: dict[str, Any]) -> LabConfig:
    """Two scripted instances (signals on given bar numbers), with stops so wide that
    positions stay open until the script or a kill switch closes them."""
    return LabConfig.model_validate(
        {
            "instances": [
                {
                    "id": "scripted_gold",
                    "strategy": "scripted",
                    "params": {**WIDE_GOLD, **gold},
                    "instruments": ["XAUUSD"],
                    "timeframe": "1m",
                },
                {
                    "id": "scripted_near",
                    "strategy": "scripted",
                    "params": {**WIDE_NEAR, **near},
                    "instruments": ["NEARUSD"],
                    "timeframe": "1m",
                },
            ]
        }
    )


async def forward(
    config: LabConfig,
    bars: Sequence[Bar],
    switches: dict[int, KillSwitchState],
    *,
    schedule: bool = False,
) -> tuple[Lab, InMemoryLabStore]:
    """Drive a lab like a forward session; switches[i] applies from the i-th minute."""
    store = FixedIdStore()
    lab = Lab(config, lab_catalog(), store, definitions=registry(), ids=SessionIds(3))
    await lab.begin(RUN_ID, accounts=openings(config), started_at=bars[0].open_time)
    for index, group in enumerate(by_minute(bars)):
        state = switches.get(index)
        if state is not None:
            if schedule:
                lab.schedule_kill_switches(group[0].close_time, state)
            else:
                lab.set_kill_switches(state)
        await lab.process_bars(group, through=group[0].close_time)
    return lab, store


def openings(config: LabConfig) -> dict[str, AccountOpening]:
    return {
        instance.id: AccountOpening(
            account_id=UUID(int=500 + n),
            config_version_id=UUID(int=600 + n),
            name=f"Paper 50K · {instance.id}",
            balance=Decimal(50000),
            high_water_mark=Decimal(50000),
        )
        for n, instance in enumerate(config.instances)
    }


def global_switch(*, close: bool = False) -> KillSwitchState:
    return KillSwitchState((ActiveSwitch("GLOBAL", "*", "operator drill", close_positions=close),))


async def test_a_kill_switch_rejects_new_entries_but_exits_and_stop_moves_still_work() -> None:
    bars = market(60)
    config = scripted_config(
        {"long_on": [2, 6, 30], "exit_long_on": [12]},
        {"long_on": [2, 6, 30], "move_sl_on": [8]},
    )
    lab, store = await forward(config, bars, {4: global_switch(), 25: KillSwitchState()})
    decisions = store.of(DecisionRecord)
    by_signal = {s.id: s for s in store.of(SignalRecord)}

    def action(decision: DecisionRecord) -> tuple[int, str]:
        signal = by_signal[decision.signal_id].signal
        assert signal is not None
        minute = int((signal.bar_time - bars[0].open_time) / MIN) + 1
        return minute, signal.signal.value

    outcome = {(d.instance_id, *action(d)): (d.approved, d.primary_reason) for d in decisions}
    for instance in ("scripted_gold", "scripted_near"):
        assert outcome[(instance, 2, "LONG")] == (True, None)  # before the switch
        assert outcome[(instance, 6, "LONG")] == (False, "KILL_SWITCH_ACTIVE")
    assert outcome[("scripted_gold", 12, "EXIT_LONG")] == (True, None)  # exits still work
    assert outcome[("scripted_near", 8, "MOVE_SL")] == (True, None)  # so do stop moves
    assert outcome[("scripted_gold", 30, "LONG")] == (True, None)  # switched off again
    rejected = next(d for d in decisions if d.primary_reason == "KILL_SWITCH_ACTIVE")
    rule = rejected.rule_results[0]
    assert rule["rule"] == "kill_switch" and "GLOBAL kill switch active" in rule["message"]
    changes = lab.drain_kill_switch_changes()
    assert [at for at, _ in changes] == [bars[0].open_time + 5 * MIN, bars[0].open_time + 26 * MIN]


async def test_close_positions_flattens_the_scope_at_the_next_bar() -> None:
    bars = market(30)
    config = scripted_config({"long_on": [2]}, {"long_on": [2]})
    accounts = openings(config)
    strategy_switch = KillSwitchState(
        (ActiveSwitch("STRATEGY", "scripted_gold", "drill", close_positions=True),)
    )
    _, store = await forward(config, bars, {10: strategy_switch})
    trades = {t.instance_id: t for t in store.of(TradeRecord)}  # latest record per trade
    gold = trades["scripted_gold"]
    assert gold.status == "CLOSED" and gold.exit_reason == "KILL_SWITCH"
    gold_bars = [b for b in bars if b.instrument == "XAUUSD"]
    assert gold.exit_time == gold_bars[11].open_time  # the next bar after the switch took effect
    flatten = [o for o in store.of(OrderRecord) if o.purpose == "FLATTEN"]
    assert [(o.instance_id, o.status) for o in flatten] == [("scripted_gold", "FILLED")]
    assert trades["scripted_near"].status == "OPEN"  # another strategy's scope: untouched
    assert accounts["scripted_gold"].account_id == gold.account_id


async def test_an_account_switch_covers_only_that_account_and_cancels_its_resting_entries() -> None:
    bars = market(30)
    config = scripted_config({"long_on": [2]}, {"long_on": [2]})
    accounts = openings(config)
    near = accounts["scripted_near"].account_id
    account_switch = KillSwitchState((ActiveSwitch("ACCOUNT", str(near), "risk review"),))
    lab, _ = await forward(config, bars, {})
    gold_account = next(a for a in lab.accounts if a.instance_id == "scripted_gold")
    near_account = next(a for a in lab.accounts if a.instance_id == "scripted_near")
    assert account_switch.halt_reason(near_account.account_id, "scripted_near") is not None
    assert account_switch.halt_reason(gold_account.account_id, "scripted_gold") is None
    assert account_switch.summary() == {"global": False, "accounts": [str(near)], "strategies": []}


async def test_a_scheduled_switch_replays_exactly_like_a_live_one() -> None:
    bars = market(60)
    config = scripted_config({"long_on": [2, 6, 30], "exit_long_on": [12]}, {"long_on": [2, 6, 30]})
    switches = {4: global_switch(close=True), 25: KillSwitchState()}
    _, live = await forward(config, bars, switches)
    _, replayed = await forward(config, bars, switches, schedule=True)
    assert records(replayed) == records(live)
    assert any(d.primary_reason == "KILL_SWITCH_ACTIVE" for d in live.of(DecisionRecord))


def test_kill_switch_state_round_trips_and_orders_scopes() -> None:
    state = KillSwitchState(
        (
            ActiveSwitch("STRATEGY", "x", "s"),
            ActiveSwitch("GLOBAL", "*", "g", close_positions=True),
        )
    )
    assert KillSwitchState.from_document(state.document()) == KillSwitchState(
        tuple(sorted(state.switches))
    )
    assert state.halt_reason(UUID(int=1), "x") == "GLOBAL kill switch active: g"
    assert state.closes_positions(UUID(int=1), "y")
    assert KillSwitchState().halt_reason(UUID(int=1), "x") is None


async def test_turning_on_close_positions_for_an_active_switch_flattens() -> None:
    bars = market(30)
    config = scripted_config({"long_on": [2]}, {"long_on": [2]})
    _, store = await forward(config, bars, {5: global_switch(), 10: global_switch(close=True)})
    trades = {t.instance_id: t for t in store.of(TradeRecord)}
    assert {t.exit_reason for t in trades.values()} == {"KILL_SWITCH"}
