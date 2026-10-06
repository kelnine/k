"""The strategy lab: many strategy instances, one clock, identical conditions.

For every batch of bars that closed at the same instant the lab:

1. lets every **account** process the base-timeframe bars first — orders
   decided on the previous close fill at these bars' opens, brackets and
   holding costs are applied;
2. hands the **same immutable batch** to every strategy host (subprocess
   hosts compute in parallel) and collects outputs in a fixed order;
3. records each signal and routes it **only to the accounts allocated to the
   instance that produced it** — an instance can never reach another
   instance's account;
4. snapshots equity on a fixed cadence and flushes all records to the store in
   one write per batch.

Faulted instances stop producing signals; everyone else carries on.
"""

import itertools
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from kterminal.analytics.summary import TradeSummary, summarize_trades
from kterminal.core.enums import SignalAction
from kterminal.core.ids import uuid7
from kterminal.core.registry import Registry
from kterminal.domain.accounts import AccountSettings
from kterminal.domain.catalog import InstrumentCatalog
from kterminal.domain.market import Bar
from kterminal.domain.timeframes import Timeframe
from kterminal.marketdata.aggregator import aggregate_stream
from kterminal.observability.logging import get_logger
from kterminal.paper.account import InstrumentSetup, PaperAccount
from kterminal.paper.config import LabConfig
from kterminal.paper.records import FaultRecord, Record, SignalRecord
from kterminal.paper.store import LabStore, ProvisionedAccount
from kterminal.strategy_engine.base import StrategyMeta
from kterminal.strategy_engine.hosts import HostState, InProcessHost, StrategyHost, SubprocessHost
from kterminal.strategy_engine.instances import ResolvedInstance, resolve_instance
from kterminal.strategy_engine.model import RunnerOutput
from kterminal.strategy_engine.registry import (
    DEFINITIONS,
    StrategyDefinition,
    discover_strategies,
    register_external,
)

_log = get_logger(__name__)


@dataclass
class LabMember:
    resolved: ResolvedInstance
    version_id: UUID
    host: StrategyHost
    accounts: list[PaperAccount]
    settings: AccountSettings
    markets: dict[str, InstrumentSetup]
    fault_recorded: bool = False


@dataclass(frozen=True, slots=True)
class AccountResult:
    instance_id: str
    account_id: UUID
    account_name: str
    starting_balance: Any
    balance: Any
    equity: Any
    signals: int
    approved: int
    rejected: int
    reject_codes: dict[str, int]
    host_state: str
    fault: str | None
    summary: TradeSummary


@dataclass
class LabResult:
    run_id: UUID
    batches: int
    started_at: datetime | None
    finished_at: datetime | None
    accounts: list[AccountResult] = field(default_factory=list)


class Lab:
    def __init__(
        self,
        config: LabConfig,
        catalog: InstrumentCatalog,
        store: LabStore,
        *,
        definitions: Registry[StrategyDefinition] = DEFINITIONS,
        run_kind: str = "LAB_SIMULATION",
        run_name: str = "lab",
        config_dir: Path | None = None,
        discover: bool = True,
    ) -> None:
        self.config = config
        self.catalog = catalog
        self.store = store
        self.definitions = definitions
        self.run_kind = run_kind
        self.run_name = run_name
        self.config_dir = config_dir
        self.discover = discover
        self.base_timeframe = Timeframe.parse(config.base_timeframe)
        self.members: list[LabMember] = []
        self._records: list[Record] = []
        self._clock_start = _epoch()

    # ── setup ───────────────────────────────────────────────────────────────
    async def setup(self) -> None:
        if self.discover and self.definitions is DEFINITIONS:
            discover_strategies()
        for external in self.config.external_strategies:
            pine = None
            if external.pine_source:
                pine = Path(external.pine_source)
                if self.config_dir is not None and not pine.is_absolute():
                    pine = self.config_dir / pine
            meta = StrategyMeta.model_validate(external.model_dump(exclude={"pine_source"}))
            register_external(meta, pine_source=pine)

        for instance in self.config.enabled_instances:
            spec = self.config.instance_spec(instance)
            resolved = resolve_instance(
                spec,
                instruments=self.catalog.instruments,
                sessions=self.catalog.sessions,
                definitions=self.definitions,
            )
            for tf in resolved.timeframes:
                if not self.base_timeframe.divides(tf):
                    raise ValueError(
                        f"instance {spec.id}: timeframe {tf} is not built from the base "
                        f"timeframe {self.base_timeframe}"
                    )
            version_id = await self.store.register_instance(resolved)
            settings = self.config.account_settings(instance)
            markets = {}
            for symbol in spec.instruments:
                listing = self.catalog.execution_listing(settings.venue_profile, symbol)
                markets[symbol] = InstrumentSetup(
                    instrument=self.catalog.instrument(symbol),
                    listing=listing,
                    costs=self.catalog.cost_calculator(listing),
                    calendar=self.catalog.calendar_for(listing),
                )
            host_cls = SubprocessHost if spec.host == "subprocess" else InProcessHost
            host = host_cls(resolved, self.catalog.instruments, self.catalog.sessions)
            self.members.append(LabMember(resolved, version_id, host, [], settings, markets))
        _log.info("lab.setup", instances=[m.resolved.id for m in self.members])

    async def provision_dedicated(self) -> list[tuple[str, ProvisionedAccount]]:
        """Create (or update) each instance's persistent forward-test account.

        Idempotent: re-running with unchanged settings changes nothing; changed
        settings create a new account configuration version.
        """
        if not self.members:
            await self.setup()
        await self.store.apply_catalog(
            document=self.catalog.to_document(),
            fingerprint=self.catalog.fingerprint,
            applied_by="lab:provision",
        )
        provisioned = []
        for member in self.members:
            spec = member.resolved.spec
            account = await self.store.provision_account(
                instance_id=spec.id,
                name=f"{member.settings.display_name_prefix} · {spec.id}",
                settings=member.settings,
            )
            provisioned.append((spec.id, account))
        return provisioned

    async def _provision_accounts(self, run_id: UUID) -> None:
        """One account per instance, created for this run (never shared between instances)."""
        for member in self.members:
            spec = member.resolved.spec
            settings = member.settings
            provisioned = await self.store.provision_account(
                instance_id=spec.id,
                name=f"{settings.display_name_prefix} · {spec.id}",
                settings=settings,
                run_id=run_id,
                opened_at=self._clock_start,
            )
            member.accounts = [
                PaperAccount(
                    account_id=provisioned.account_id,
                    name=provisioned.name,
                    instance_id=spec.id,
                    settings=settings,
                    config_version_id=provisioned.config_version_id,
                    markets=member.markets,
                    timeframe=member.resolved.timeframe.code,
                    trading_day_rule=self.catalog.sessions.trading_day_rule(settings.trading_day),
                    classify=self.catalog.sessions.classify,
                    on_opposite_signal=member.resolved.definition.meta.on_opposite_signal,
                )
            ]

    @property
    def timeframes(self) -> list[Timeframe]:
        needed = {tf for m in self.members for tf in m.resolved.timeframes}
        return sorted(needed - {self.base_timeframe})

    @property
    def accounts(self) -> list[PaperAccount]:
        return [a for m in self.members for a in m.accounts]

    # ── run ─────────────────────────────────────────────────────────────────
    async def run(
        self,
        base_bars: Iterable[Bar],
        *,
        warmup_bars: Sequence[Bar] = (),
        close_at_end: bool = True,
    ) -> LabResult:
        if not self.members:
            await self.setup()
        bars_iter = iter(base_bars)
        first = next(bars_iter, None)
        if first is None:
            raise ValueError("the lab needs at least one base bar")
        self._clock_start = warmup_bars[0].open_time if warmup_bars else first.open_time
        started: datetime | None = None
        last: datetime | None = None
        run_id = await self.store.start_run(
            kind=self.run_kind,
            name=self.run_name,
            config=self.config.model_dump(mode="json"),
            catalog_document=self.catalog.to_document(),
            catalog_fingerprint=self.catalog.fingerprint,
            started_at=self._clock_start,
        )
        await self._provision_accounts(run_id)
        for member in self.members:
            member.host.start()
            if warmup_bars:
                warm = [
                    b
                    for batch in aggregate_stream(warmup_bars, self.base_timeframe, self.timeframes)
                    for b in batch
                ]
                member.host.warmup(warm)
            self._check_fault(member, None)
        await self._flush(run_id)

        snapshot_every = timedelta(minutes=self.config.equity_snapshot_minutes)
        last_snapshot: datetime | None = None
        batches = 0
        stream = itertools.chain([first], bars_iter)
        for batch in aggregate_stream(stream, self.base_timeframe, self.timeframes):
            at = batch[0].close_time
            started = started or batch[0].open_time
            last = at
            batches += 1
            base = [b for b in batch if b.timeframe == self.base_timeframe]
            for account in self.accounts:  # 1. fills/brackets/costs on this batch's bars
                for bar in base:
                    account.on_bar(bar)
            for member in self.members:  # 2. same batch to every instance
                member.host.dispatch(batch)
            for member in self.members:  # 3. collect in fixed order and route
                for output in member.host.collect():
                    self._route(member, output, batch, run_id)
                self._check_fault(member, at)
            if last_snapshot is None or at - last_snapshot >= snapshot_every:
                for account in self.accounts:
                    account.mark(at)
                last_snapshot = at
            await self._flush(run_id)

        if last is not None:
            for account in self.accounts:
                if close_at_end:
                    account.close_all(last)
                account.mark(last)
        for member in self.members:
            member.host.stop()
        await self._flush(run_id)
        result = await self._result(run_id, batches, started, last)
        await self.store.finish_run(
            run_id,
            status="COMPLETED",
            summary={"batches": batches, "accounts": len(result.accounts)},
            finished_at=last or self._clock_start,
        )
        return result

    def _route(
        self, member: LabMember, output: RunnerOutput, batch: Sequence[Bar], run_id: UUID
    ) -> None:
        resolved = member.resolved
        for rejected in output.rejected:
            self._records.append(
                SignalRecord(
                    id=uuid7(),
                    instance_id=resolved.id,
                    strategy_version=resolved.version,
                    definition_id=resolved.definition.id,
                    received_at=rejected.time,
                    status="INVALID",
                    instrument=rejected.instrument,
                    timeframe=resolved.timeframe.code,
                    raw_payload=dict(rejected.payload),
                    reject_code=rejected.code,
                    reject_detail=rejected.message,
                )
            )
        for signal in output.signals:
            if signal.strategy_id != resolved.id:  # defence in depth: runner already checks
                raise RuntimeError(f"{resolved.id} produced a signal for {signal.strategy_id}")
            if signal.signal is SignalAction.NO_TRADE and not signal.persist:
                continue
            signal_id = uuid7()
            routed = signal.signal is not SignalAction.NO_TRADE
            self._records.append(
                SignalRecord(
                    id=signal_id,
                    instance_id=resolved.id,
                    strategy_version=resolved.version,
                    definition_id=resolved.definition.id,
                    received_at=signal.timestamp,
                    status="ROUTED" if routed else "IGNORED",
                    signal=signal,
                    instrument=signal.symbol,
                    timeframe=signal.timeframe,
                    market_snapshot=_snapshot(
                        signal.symbol, signal.timeframe, batch, self.catalog.fingerprint, run_id
                    ),
                )
            )
            if routed:
                for account in member.accounts:  # only this instance's own accounts
                    account.handle_signal(signal, signal_id, signal.timestamp)

    def _check_fault(self, member: LabMember, at: datetime | None) -> None:
        fault = member.host.fault
        if fault is not None and not member.fault_recorded:
            member.fault_recorded = True
            self._records.append(FaultRecord(member.resolved.id, fault, at or self._clock_start))
            _log.error(
                "lab.instance_faulted",
                instance=member.resolved.id,
                error=fault.error_type,
                stage=fault.stage,
            )

    async def _flush(self, run_id: UUID) -> None:
        records = list(self._records)
        self._records.clear()
        for account in self.accounts:
            records.extend(account.drain())
        if records:
            await self.store.write(records, run_id=run_id)

    async def _result(
        self, run_id: UUID, batches: int, started: datetime | None, finished: datetime | None
    ) -> LabResult:
        result = LabResult(run_id, batches, started, finished)
        for member in self.members:
            for account in member.accounts:
                trades = await self.store.closed_trades(account.account_id)
                balance = await self.store.ledger_balance(account.account_id)
                result.accounts.append(
                    AccountResult(
                        instance_id=member.resolved.id,
                        account_id=account.account_id,
                        account_name=account.name,
                        starting_balance=account.settings.starting_balance,
                        balance=balance if balance is not None else account.balance,
                        equity=account.equity,
                        signals=account.stats.signals,
                        approved=account.stats.approved,
                        rejected=account.stats.rejected,
                        reject_codes=dict(account.stats.reject_codes),
                        host_state=member.host.state.value,
                        fault=None
                        if member.host.fault is None
                        else f"{member.host.fault.error_type}: {member.host.fault.message}",
                        summary=summarize_trades(trades),
                    )
                )
        return result


def _snapshot(
    symbol: str, timeframe: str, batch: Sequence[Bar], fingerprint: str, run_id: UUID
) -> dict[str, Any]:
    """The bar a signal was decided on, plus the data/catalog provenance."""
    for bar in batch:
        if bar.instrument == symbol and bar.timeframe.code == timeframe:
            return {
                "bar": {
                    "open_time": bar.open_time.isoformat(),
                    "close_time": bar.close_time.isoformat(),
                    "open": str(bar.open),
                    "high": str(bar.high),
                    "low": str(bar.low),
                    "close": str(bar.close),
                    "volume": str(bar.volume),
                },
                "source": bar.source,
                "catalog_fingerprint": fingerprint,
                "run_id": str(run_id),
            }
    return {"catalog_fingerprint": fingerprint, "run_id": str(run_id)}


def _epoch() -> datetime:
    return datetime(1970, 1, 1, tzinfo=UTC)


__all__ = ["AccountResult", "HostState", "Lab", "LabMember", "LabResult"]
