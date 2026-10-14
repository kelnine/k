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

Faulted instances stop producing signals; everyone else carries on. A signal
that its own account cannot process faults that instance only. If the run
itself fails, every host is stopped and the run is recorded as FAILED.

:meth:`Lab.run` processes a finite list of bars in one call. A forward session
drives the same steps incrementally — :meth:`Lab.begin` (accounts, warm-up),
:meth:`Lab.process_bars` / :meth:`Lab.process_batch` as bars arrive, and
:meth:`Lab.end` — with ids from an injected :class:`~kterminal.paper.ids.IdSource`
and kill switches applied between a batch's fills and its signals.
"""

import itertools
import traceback
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from kterminal.analytics.summary import TradeSummary, summarize_trades
from kterminal.core.enums import SignalAction
from kterminal.core.registry import Registry
from kterminal.domain.accounts import AccountSettings
from kterminal.domain.catalog import InstrumentCatalog
from kterminal.domain.market import Bar
from kterminal.domain.timeframes import Timeframe
from kterminal.marketdata.aggregator import StreamAggregator
from kterminal.observability.logging import get_logger
from kterminal.paper.account import InstrumentSetup, PaperAccount
from kterminal.paper.config import LabConfig
from kterminal.paper.ids import IdSource, RandomIds
from kterminal.paper.kill_switch import NO_KILL_SWITCHES, KillSwitchState
from kterminal.paper.records import FaultRecord, Record, SignalRecord
from kterminal.paper.store import LabStore, ProvisionedAccount
from kterminal.strategy_engine.base import StrategyMeta
from kterminal.strategy_engine.hosts import HostState, InProcessHost, StrategyHost, SubprocessHost
from kterminal.strategy_engine.instances import ResolvedInstance, resolve_instance
from kterminal.strategy_engine.model import Fault, RunnerOutput
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
    routing_stopped: bool = False  # set when the instance's output broke its own account


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


@dataclass(frozen=True, slots=True)
class AccountOpening:
    """A persistent (dedicated) account an instance continues to trade in."""

    account_id: UUID
    config_version_id: UUID
    name: str
    balance: Decimal  # from the ledger when the session began
    high_water_mark: Decimal


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
        ids: IdSource | None = None,
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
        self.ids: IdSource = ids if ids is not None else RandomIds()
        self.run_id: UUID | None = None
        self.batch_count = 0
        self.started_at: datetime | None = None  # open time of the first processed batch
        self.last_batch_at: datetime | None = None  # close time of the latest processed batch
        self.kill_switches: KillSwitchState = NO_KILL_SWITCHES
        self._records: list[Record] = []
        self._clock_start = _epoch()
        self._stream: StreamAggregator | None = None
        self._snapshot_every = timedelta(minutes=config.equity_snapshot_minutes)
        self._last_snapshot: datetime | None = None
        self._kill_pending: KillSwitchState | None = None
        self._kill_schedule: dict[datetime, KillSwitchState] = {}
        self._kill_changes: list[tuple[datetime, KillSwitchState]] = []
        self._injected: dict[tuple[str, datetime | None], Fault] = {}

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
                self._account(member, provisioned.account_id, provisioned.name, provisioned)
            ]

    def _open_accounts(self, openings: Mapping[str, AccountOpening]) -> None:
        """Each instance continues in its own persistent account (forward sessions)."""
        for member in self.members:
            opening = openings.get(member.resolved.id)
            if opening is None:
                raise ValueError(f"no account for instance {member.resolved.id}")
            account = self._account(member, opening.account_id, opening.name, opening)
            account.open_with(opening.balance, opening.high_water_mark)
            member.accounts = [account]

    def _account(
        self,
        member: LabMember,
        account_id: UUID,
        name: str,
        provisioned: ProvisionedAccount | AccountOpening,
    ) -> PaperAccount:
        settings = member.settings
        return PaperAccount(
            account_id=account_id,
            name=name,
            instance_id=member.resolved.spec.id,
            settings=settings,
            config_version_id=provisioned.config_version_id,
            markets=member.markets,
            timeframe=member.resolved.timeframe.code,
            trading_day_rule=self.catalog.sessions.trading_day_rule(settings.trading_day),
            classify=self.catalog.sessions.classify,
            on_opposite_signal=member.resolved.definition.meta.on_opposite_signal,
            new_id=self.ids,
        )

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
        """Run a whole simulation: a fresh run, run-scoped accounts, every bar, results."""
        if not self.members:
            await self.setup()
        bars_iter = iter(base_bars)
        first = next(bars_iter, None)
        if first is None:
            raise ValueError("the lab needs at least one base bar")
        self._clock_start = warmup_bars[0].open_time if warmup_bars else first.open_time
        run_id = await self.store.start_run(
            kind=self.run_kind,
            name=self.run_name,
            config=self.config.model_dump(mode="json"),
            catalog_document=self.catalog.to_document(),
            catalog_fingerprint=self.catalog.fingerprint,
            started_at=self._clock_start,
        )
        try:
            await self.begin(run_id, warmup_bars=warmup_bars)
            await self.process_bars(itertools.chain([first], bars_iter))
            result = await self.end(close_positions=close_at_end)
            await self.store.finish_run(
                run_id,
                status="COMPLETED",
                summary={"batches": result.batches, "accounts": len(result.accounts)},
                finished_at=result.finished_at or self._clock_start,
            )
            return result
        except BaseException as exc:
            self.abort()
            await self.store.finish_run(
                run_id,
                status="FAILED",
                summary={"error": f"{type(exc).__name__}: {exc}"[:2_000]},
                finished_at=self._clock_start,
            )
            raise

    # ── incremental processing ──────────────────────────────────────────────
    async def begin(
        self,
        run_id: UUID,
        *,
        warmup_bars: Sequence[Bar] = (),
        accounts: Mapping[str, AccountOpening] | None = None,
        started_at: datetime | None = None,
    ) -> None:
        """Open the accounts, start every host and warm it up on ``warmup_bars``.

        Without ``accounts`` each instance gets a fresh run-scoped account; with them
        (forward sessions) each continues in its persistent account. Warm-up bars are
        time-ordered base bars before the first live bar; they prime indicators and are
        never traded. One aggregator spans warm-up and live bars, so a higher-timeframe
        period that straddles the boundary is built from all of its base bars.
        """
        if not self.members:
            await self.setup()
        if started_at is not None:
            self._clock_start = started_at
        self.run_id = run_id
        if accounts is None:
            await self._provision_accounts(run_id)
        else:
            self._open_accounts(accounts)
        stream = StreamAggregator(self.base_timeframe, self.timeframes)
        self._stream = stream
        warm: list[Bar] = []
        for bar in warmup_bars:
            for batch in stream.push(bar):
                warm.extend(batch)
        if warmup_bars:
            for batch in stream.complete_through(warmup_bars[-1].close_time):
                warm.extend(batch)
        for member in self.members:
            member.host.start()
            self._inject_fault(member, None)
            if warm:
                member.host.warmup(warm)
            self._check_fault(member, None)
        await self._flush()

    async def process_bars(self, bars: Iterable[Bar], *, through: datetime | None = None) -> int:
        """Feed time-ordered base bars and process every batch they complete.

        ``through`` declares that no base bar opening before it will follow (a live
        minute is over): batches closing at or before it are processed now instead of
        when the next bar arrives. Returns the number of batches processed.
        """
        stream = self._require_stream()
        processed = 0
        for bar in bars:
            for batch in stream.push(bar):
                await self.process_batch(batch)
                processed += 1
        if through is not None:
            for batch in stream.advance(through):
                await self.process_batch(batch)
                processed += 1
        return processed

    async def process_batch(self, batch: Sequence[Bar]) -> None:
        """Process one batch of bars that closed at the same instant."""
        at = batch[0].close_time
        self.ids.advance(at)
        self.started_at = self.started_at or batch[0].open_time
        self.last_batch_at = at
        self.batch_count += 1
        base = [b for b in batch if b.timeframe == self.base_timeframe]
        for account in self.accounts:  # 1. fills/brackets/costs on this batch's bars
            for bar in base:
                account.on_bar(bar)
        self._apply_kill_switches(at)  # a change takes effect after fills, before signals
        for member in self.members:  # 2. same batch to every instance
            self._inject_fault(member, at)
            member.host.dispatch(batch)
        for member in self.members:  # 3. collect in fixed order and route
            for output in member.host.collect():
                self._route(member, output, batch)
            self._check_fault(member, at)
        if self._last_snapshot is None or at - self._last_snapshot >= self._snapshot_every:
            for account in self.accounts:
                account.mark(at)
            self._last_snapshot = at
        await self._flush()

    async def end(self, *, close_positions: bool = True) -> LabResult:
        """Process what is left of the stream, optionally flatten, stop every host and
        return the results (computed from the recorded rows)."""
        stream = self._require_stream()
        for batch in stream.finish():
            await self.process_batch(batch)
        last = self.last_batch_at
        if last is not None:
            for account in self.accounts:
                if close_positions:
                    account.close_all(last)
                account.mark(last)  # replaces a snapshot the last batch took at the same instant
        for member in self.members:
            member.host.stop()
        await self._flush()
        if self.run_id is None:  # pragma: no cover - begin() sets it
            raise RuntimeError("the lab was not begun")
        return await self._result(self.run_id, self.batch_count, self.started_at, last)

    def abort(self) -> None:
        """Stop every host (the run failed, or the process is shutting down)."""
        for member in self.members:
            member.host.stop()

    def _require_stream(self) -> StreamAggregator:
        if self._stream is None:
            raise RuntimeError("Lab.begin() must be called first")
        return self._stream

    # ── kill switches and replayed faults ───────────────────────────────────
    def set_kill_switches(self, state: KillSwitchState) -> None:
        """Make ``state`` the active kill switches from the next processed batch on."""
        self._kill_pending = state

    def schedule_kill_switches(self, at: datetime, state: KillSwitchState) -> None:
        """Apply ``state`` at the batch that closes at ``at`` (replaying a session)."""
        self._kill_schedule[at] = state

    def drain_kill_switch_changes(self) -> list[tuple[datetime, KillSwitchState]]:
        """The states that took effect since the last call, with their batch times."""
        changes, self._kill_changes = self._kill_changes, []
        return changes

    def inject_fault(self, instance_id: str, at: datetime | None, fault: Fault) -> None:
        """Fault an instance at the batch closing at ``at`` (``None``: at warm-up) — used
        to replay host failures (time-outs, crashed processes) that replay cannot cause."""
        self._injected[(instance_id, at)] = fault

    def _inject_fault(self, member: LabMember, at: datetime | None) -> None:
        fault = self._injected.pop((member.resolved.id, at), None)
        if fault is not None and member.host.fault is None:
            member.host.fail(fault)

    def _apply_kill_switches(self, at: datetime) -> None:
        state = self._kill_schedule.pop(at, None)
        if state is None:
            state = self._kill_pending
        self._kill_pending = None
        if state is None or state == self.kill_switches:
            return
        previous = self.kill_switches
        for member in self.members:
            instance = member.resolved.id
            for account in member.accounts:
                was_halted = previous.halt_reason(account.account_id, instance) is not None
                reason = state.halt_reason(account.account_id, instance)
                account.entry_halt = reason
                if (
                    reason is not None
                    and not was_halted
                    and state.cancels_orders(account.account_id, instance)
                ):
                    account.cancel_entries(at, "KILL_SWITCH")
                if state.closes_positions(
                    account.account_id, instance
                ) and not previous.closes_positions(account.account_id, instance):
                    account.flatten(at, "KILL_SWITCH")
        self.kill_switches = state
        self._kill_changes.append((at, state))
        _log.warning("lab.kill_switches", at=at.isoformat(), **state.summary())

    def _route(self, member: LabMember, output: RunnerOutput, batch: Sequence[Bar]) -> None:
        resolved = member.resolved
        run_id = self.run_id
        if member.routing_stopped:
            return
        for rejected in output.rejected:
            self._records.append(
                SignalRecord(
                    id=self.ids(),
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
            signal_id = self.ids()
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
                    try:
                        account.handle_signal(signal, signal_id, output.time)
                    except Exception as exc:
                        # The instance's output broke its own account: fault that instance
                        # (its account keeps its state); nobody else is affected.
                        member.host.fail(_route_fault(resolved.id, signal.symbol, output.time, exc))
                        member.routing_stopped = True
                        return

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

    async def _flush(self) -> None:
        records = list(self._records)
        self._records.clear()
        for account in self.accounts:
            records.extend(account.drain())
        if records:
            if self.run_id is None:  # pragma: no cover - begin() sets it
                raise RuntimeError("the lab was not begun")
            await self.store.write(records, run_id=self.run_id)

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


def _route_fault(instance_id: str, symbol: str, at: datetime, exc: Exception) -> Fault:
    return Fault(
        instance_id=instance_id,
        instrument=symbol,
        time=at,
        stage="route",
        error_type=type(exc).__name__,
        message=str(exc)[:2_000],
        traceback="".join(traceback.format_exception(exc))[-8_000:],
    )


def _snapshot(
    symbol: str, timeframe: str, batch: Sequence[Bar], fingerprint: str, run_id: UUID | None
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


__all__ = ["AccountOpening", "AccountResult", "HostState", "Lab", "LabMember", "LabResult"]
