"""Forward paper sessions: the strategy lab on live bars, in each instance's own account.

A forward session is the lab run incrementally on closed live 1-minute bars.
Every instance trades in its **dedicated** account (``Paper 50K · <id>``,
created by ``Lab.provision_dedicated``), continuing from that account's ledger
balance; simulations never touch these accounts. The session is a ``runs``
row of kind ``FORWARD`` that stays ``RUNNING`` until a new session replaces it.

Starting
    The lab is set up, the dedicated accounts are provisioned (a changed
    account configuration becomes a new configuration version), and every
    instance is warmed up on recent history — stored candles of the
    instrument's live source, completed from the provider's history (and
    stored) — up to a configurable number of days. Warm-up bars prime
    indicators and are never traded.

Running
    Each minute's bars are pushed through the lab and committed in one
    transaction with everything the lab recorded (see :mod:`pg_forward`). The
    bars go into ``candles``: that table is the session's input log.

Restarting
    The open session is resumed by replaying its logged candles through a fresh
    lab with every write suppressed: ids are deterministic
    (:class:`~kterminal.paper.ids.SessionIds`), kill-switch changes and host
    failures are applied at the batches where they happened, so the strategy
    state, theoretical books and accounts are rebuilt exactly. The rebuilt
    state is then checked against the database (row counts, ledger balances,
    open trades, latest equity) and the session refuses to continue on any
    difference. A changed lab configuration, catalog or strategy version means
    the old session can no longer be reproduced: the operator starts a new one,
    which closes the old session's positions at their last price.
"""

import inspect
import itertools
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from kterminal.core.canonical import decimal_text, hash_data, sha256_text
from kterminal.core.errors import KTerminalError
from kterminal.core.registry import Registry
from kterminal.db.repositories.candles import plain_bar
from kterminal.domain.catalog import InstrumentCatalog
from kterminal.domain.market import Bar
from kterminal.domain.timeframes import M1
from kterminal.marketdata.base import MarketDataProvider
from kterminal.observability.logging import get_logger
from kterminal.paper.account import InstrumentSetup, PaperAccount
from kterminal.paper.config import LabConfig, LabInstance
from kterminal.paper.feed import MinuteBatch
from kterminal.paper.ids import SessionIds
from kterminal.paper.kill_switch import KillSwitchState
from kterminal.paper.lab import AccountOpening, Lab
from kterminal.paper.pg_forward import FORWARD, PostgresForwardStore, StoredSession
from kterminal.paper.records import (
    DecisionRecord,
    EquityRecord,
    FillRecord,
    LedgerRecord,
    OrderRecord,
    Record,
    SignalRecord,
    TradeEventRecord,
    TradeRecord,
)
from kterminal.paper.store import ProvisionedAccount
from kterminal.strategy_engine.model import Fault
from kterminal.strategy_engine.periods import Period, period_warmup_bars
from kterminal.strategy_engine.registry import DEFINITIONS, StrategyDefinition

_log = get_logger(__name__)

MINUTE = timedelta(minutes=1)
GENESIS = "0" * 64
NEW_SESSION_HINT = "start a new session: kterminal paper start --new-session"
DEFAULT_WARMUP_DAYS = 10.0


class ForwardSessionError(KTerminalError):
    """A forward session cannot be started, resumed or ended as requested."""


class SessionMismatchError(ForwardSessionError):
    """The open session was started under a different configuration, catalog or strategy
    version: replaying it with today's code would not reproduce what it did."""


class SessionVerificationError(ForwardSessionError):
    """The state rebuilt by replay differs from what the database recorded."""


# ── the session document ─────────────────────────────────────────────────────
class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class InputSegment(_Frozen):
    """Bars of one instrument from one source: ``start <= open time < end``."""

    source: str
    start: datetime
    end: datetime | None = None  # open: up to the session's processed_through
    phase: Literal["warmup", "live"]


class AccountPlan(_Frozen):
    account_id: UUID
    config_version_id: UUID
    name: str
    balance: Decimal  # ledger balance when the session began
    high_water_mark: Decimal


class SessionPlan(_Frozen):
    """What a session was started with (``runs.config["plan"]``); never changes."""

    lab_config_hash: str  # the lab-wide settings replay depends on (lab_config_hash)
    catalog_fingerprint: str
    versions: dict[str, str]  # instance → config hash (strategy version)
    instance_settings: dict[str, str]  # instance → instance_settings_hash
    accounts: dict[str, AccountPlan]
    instruments: tuple[str, ...]
    live_start: datetime
    warmup_days: float


class SessionProgress(_Frozen):
    """How far a session got (``runs.data_fingerprint``); updated with every minute."""

    inputs: dict[str, tuple[InputSegment, ...]]
    warmup_bars: int
    warmup_sha256: str
    processed_through: datetime  # every minute that closed at or before this is processed
    minutes: int = 0  # minutes that had bars
    input_bars: int = 0
    input_sha256: str = GENESIS  # hash chain over every processed minute's bars
    batches: int = 0  # lab batches processed
    last_bars: dict[str, datetime] = Field(default_factory=dict)  # newest bar per instrument

    def document(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def lab_config_hash(config: LabConfig) -> str:
    """The lab-wide settings a session's results depend on: the base timeframe, the
    equity-snapshot cadence and the declared external strategies. (Instances are
    compared one by one; ``forward``, ``experiments`` and disabled instances do not
    matter.)"""
    return hash_data(
        {
            "base_timeframe": config.base_timeframe,
            "equity_snapshot_minutes": config.equity_snapshot_minutes,
            "external_strategies": [e.model_dump(mode="json") for e in config.external_strategies],
        }
    )


def instance_settings_hash(config: LabConfig, instance: LabInstance) -> str:
    """An instance's lab settings beyond its strategy version: its instruments and
    timeframes, position rules and merged account settings. The host (in-process or
    subprocess) is left out: it does not change what the instance does."""
    spec = config.instance_spec(instance).model_dump(mode="json", exclude={"host"})
    return hash_data({"spec": spec, "account": config.account_settings(instance).document()})


def bars_text(bars: Iterable[Bar]) -> str:
    """Canonical text of bars (numbers without redundant zeros), for input hashes."""
    return "\n".join(
        "|".join(
            (
                b.instrument,
                b.timeframe.code,
                b.open_time.isoformat(),
                decimal_text(b.open),
                decimal_text(b.high),
                decimal_text(b.low),
                decimal_text(b.close),
                decimal_text(b.volume),
                b.source,
            )
        )
        for b in bars
    )


def chain_hash(previous: str, bars: Sequence[Bar]) -> str:
    return sha256_text(previous + bars_text(bars))


def as_input(bar: Bar, source: str) -> Bar:
    """A bar exactly as a session processes and logs it: canonical numbers, the
    segment's source (what a replay will read back from ``candles``)."""
    plain = plain_bar(bar)
    if plain.source == source:
        return plain
    return Bar(
        instrument=plain.instrument,
        timeframe=plain.timeframe,
        open_time=plain.open_time,
        close_time=plain.close_time,
        open=plain.open,
        high=plain.high,
        low=plain.low,
        close=plain.close,
        volume=plain.volume,
        source=source,
    )


def warmup_need(lab: Lab) -> dict[str, int]:
    """Base bars each instrument needs: the largest need of the instances trading it.

    An instance needs ``meta.warmup_bars`` (plus the aggregator's dropped first period)
    of its largest timeframe, and — if its code uses ``ctx.periods`` — enough primary
    bars for every period level it asks for (``period_warmup_bars``, docs/05 §5.2.2).
    """
    need: dict[str, int] = {}
    base = lab.base_timeframe.seconds
    for member in lab.members:
        resolved = member.resolved
        largest = max(resolved.timeframes)
        bars = (resolved.definition.meta.warmup_bars + 1) * (largest.seconds // base)
        primary = resolved.timeframe
        for period in period_levels_used(resolved.definition):
            levels = period_warmup_bars(period, primary) * (primary.seconds // base)
            bars = max(bars, levels)
        for symbol in resolved.spec.instruments:
            need[symbol] = max(need.get(symbol, 0), bars)
    return need


_PERIODS_USED = re.compile(r"\.periods\b")
_PERIOD_LITERAL = re.compile(
    r"\.periods\s*\.\s*(?:previous|current)\(\s*(?:[\"']([DWMdw]|day|week|month)[\"']"
    r"|Period\.(DAY|WEEK|MONTH))"
)


def period_levels_used(definition: StrategyDefinition) -> tuple[Period, ...]:
    """The period levels a strategy's code asks ``ctx.periods`` for, read from the source
    of its module: the literal periods passed to ``previous`` / ``current``, or the
    trading day when it uses ``ctx.periods`` in another way. Nothing for external
    strategies or when the source is not available."""
    if definition.strategy_cls is None:
        return ()
    try:
        source = inspect.getsource(inspect.getmodule(definition.strategy_cls) or object)
    except (OSError, TypeError):
        return ()
    if not _PERIODS_USED.search(source):
        return ()
    found = {
        Period.parse(literal or word.lower()) for literal, word in _PERIOD_LITERAL.findall(source)
    }
    return tuple(sorted(found or {Period.DAY}, key=list(Period).index))


class _Recorder:
    """The lab's store during a forward session: records are collected, then committed
    with the minute's bars and progress — or discarded while replaying."""

    def __init__(self, store: PostgresForwardStore) -> None:
        self.store = store
        self.records: list[Record] = []

    def take(self) -> list[Record]:
        records, self.records = self.records, []
        return records

    async def write(self, records: Sequence[Record], *, run_id: UUID) -> None:
        self.records.extend(records)

    async def apply_catalog(
        self, *, document: dict[str, Any], fingerprint: str, applied_by: str
    ) -> None:
        await self.store.apply_catalog(
            document=document, fingerprint=fingerprint, applied_by=applied_by
        )

    async def start_run(self, **kwargs: Any) -> UUID:  # pragma: no cover - sessions create runs
        raise RuntimeError("forward sessions are created by PostgresForwardStore.create_session")

    async def register_instance(self, resolved: Any) -> UUID:
        return await self.store.register_instance(resolved)

    async def provision_account(self, **kwargs: Any) -> ProvisionedAccount:
        return await self.store.provision_account(**kwargs)

    async def finish_run(self, run_id: UUID, **kwargs: Any) -> None:  # pragma: no cover
        await self.store.finish_run(run_id, **kwargs)

    async def closed_trades(self, account_id: UUID) -> list[TradeRecord]:  # pragma: no cover
        return await self.store.closed_trades(account_id)

    async def ledger_balance(self, account_id: UUID) -> Any:  # pragma: no cover
        return await self.store.ledger_balance(account_id)

    async def isolation_checks(self, run_id: UUID) -> list[Any]:  # pragma: no cover
        return await self.store.isolation_checks(run_id)


# ── the session ──────────────────────────────────────────────────────────────
class ForwardSession:
    def __init__(
        self,
        *,
        lab: Lab,
        store: PostgresForwardStore,
        recorder: _Recorder,
        run_id: UUID,
        plan: SessionPlan,
        progress: SessionProgress,
        resumed: bool,
    ) -> None:
        self.lab = lab
        self.store = store
        self.recorder = recorder
        self.run_id = run_id
        self.plan = plan
        self.progress = progress
        self.resumed = resumed

    @property
    def instruments(self) -> tuple[str, ...]:
        return self.plan.instruments

    @property
    def processed_through(self) -> datetime:
        return self.progress.processed_through

    @property
    def last_bars(self) -> dict[str, datetime]:
        return dict(self.progress.last_bars)

    # ── start ───────────────────────────────────────────────────────────────
    @classmethod
    async def start(
        cls,
        config: LabConfig,
        catalog: InstrumentCatalog,
        store: PostgresForwardStore,
        providers: Mapping[str, MarketDataProvider],
        *,
        now: datetime,
        warmup_days: float = DEFAULT_WARMUP_DAYS,
        name: str = "paper-forward",
        definitions: Registry[StrategyDefinition] = DEFINITIONS,
        discover: bool = True,
        config_dir: Path | None = None,
    ) -> "ForwardSession":
        """Begin a new session at the current minute, warmed up on recent history."""
        if warmup_days < 0:
            raise ForwardSessionError("warm-up days cannot be negative")
        recorder = _Recorder(store)
        lab = Lab(
            config,
            catalog,
            recorder,
            definitions=definitions,
            run_kind=FORWARD,
            run_name=name,
            config_dir=config_dir,
            discover=discover,
        )
        await lab.setup()
        if not lab.members:
            raise ForwardSessionError("the lab configuration has no enabled instances")
        openings = await _open_dedicated(lab, store)
        live_start = M1.floor(now)
        warm, inputs = await _assemble_warmup(
            lab, store, providers, live_start, live_start - timedelta(days=warmup_days)
        )
        instruments = tuple(sorted({s for m in lab.members for s in m.resolved.spec.instruments}))
        plan = SessionPlan(
            lab_config_hash=lab_config_hash(config),
            catalog_fingerprint=catalog.fingerprint,
            versions={m.resolved.id: m.resolved.config_hash for m in lab.members},
            instance_settings=_instance_settings(config),
            accounts={
                instance: AccountPlan(
                    account_id=o.account_id,
                    config_version_id=o.config_version_id,
                    name=o.name,
                    balance=o.balance,
                    high_water_mark=o.high_water_mark,
                )
                for instance, o in openings.items()
            },
            instruments=instruments,
            live_start=live_start,
            warmup_days=warmup_days,
        )
        last_bars: dict[str, datetime] = {}
        for bar in warm:
            last_bars[bar.instrument] = bar.open_time
        progress = SessionProgress(
            inputs={s: tuple(segments) for s, segments in inputs.items()},
            warmup_bars=len(warm),
            warmup_sha256=sha256_text(bars_text(warm)),
            processed_through=live_start,
            last_bars=last_bars,
        )
        run_id = await store.create_session(
            name=name,
            config={"lab": config.model_dump(mode="json"), "plan": plan.model_dump(mode="json")},
            progress=progress.document(),
            catalog_document=catalog.to_document(),
            catalog_fingerprint=catalog.fingerprint,
            started_at=live_start,
        )
        lab.ids = SessionIds.for_run(run_id)  # before begin(): the accounts take it from there
        await lab.begin(run_id, warmup_bars=warm, accounts=openings, started_at=live_start)
        try:
            await store.save_progress(run_id, progress.document(), recorder.take())
        except BaseException:
            lab.abort()
            raise
        _log.info(
            "paper.session_started",
            run_id=str(run_id),
            instances=sorted(plan.versions),
            live_start=live_start.isoformat(),
            warmup_bars=len(warm),
        )
        return cls(
            lab=lab,
            store=store,
            recorder=recorder,
            run_id=run_id,
            plan=plan,
            progress=progress,
            resumed=False,
        )

    # ── resume ──────────────────────────────────────────────────────────────
    @classmethod
    async def resume(
        cls,
        stored: StoredSession,
        config: LabConfig,
        catalog: InstrumentCatalog,
        store: PostgresForwardStore,
        providers: Mapping[str, MarketDataProvider],
        *,
        definitions: Registry[StrategyDefinition] = DEFINITIONS,
        discover: bool = True,
        config_dir: Path | None = None,
    ) -> "ForwardSession":
        """Rebuild the open session's state by replaying its input log, verify it
        against the database, and return it ready to continue live."""
        plan = SessionPlan.model_validate(stored.config["plan"])
        progress = SessionProgress.model_validate(stored.progress)
        recorder = _Recorder(store)
        lab = Lab(
            config,
            catalog,
            recorder,
            definitions=definitions,
            run_kind=FORWARD,
            run_name=stored.name,
            config_dir=config_dir,
            discover=discover,
        )
        await lab.setup()
        problems = _mismatches(plan, config, catalog, lab)
        if problems:
            raise SessionMismatchError(
                f"forward session {stored.run_id} cannot be resumed: "
                + "; ".join(problems)
                + f". Its trades stay as recorded — {NEW_SESSION_HINT}"
            )
        store.attach(stored)
        run_id = stored.run_id
        lab.ids = SessionIds.for_run(run_id)
        openings = {
            instance: AccountOpening(
                account_id=a.account_id,
                config_version_id=a.config_version_id,
                name=a.name,
                balance=a.balance,
                high_water_mark=a.high_water_mark,
            )
            for instance, a in plan.accounts.items()
        }
        warm = await _load_inputs(store, progress.inputs, "warmup", plan.live_start)
        if len(warm) != progress.warmup_bars or sha256_text(bars_text(warm)) != (
            progress.warmup_sha256
        ):
            raise SessionVerificationError(
                f"forward session {run_id}: its warm-up candles changed since it began "
                f"({len(warm)} bars stored, {progress.warmup_bars} used) — {NEW_SESSION_HINT}"
            )
        for instance, ts, message in await store.host_faults(run_id):
            error_type, _, detail = message.partition(": ")
            lab.inject_fault(
                instance,
                None if ts == plan.live_start else ts,
                Fault(instance, "", ts, "host", error_type, detail),
            )
        for effective_from, state in await store.kill_switch_history(run_id):
            lab.schedule_kill_switches(effective_from, KillSwitchState.from_document(state))
        await lab.begin(run_id, warmup_bars=warm, accounts=openings, started_at=plan.live_start)
        session = cls(
            lab=lab,
            store=store,
            recorder=recorder,
            run_id=run_id,
            plan=plan,
            progress=progress,
            resumed=True,
        )
        try:
            minutes = await session._replay()
            session.progress = _reconcile_sources(progress, providers, plan.instruments)
            if session.progress != progress:
                await store.save_progress(run_id, session.progress.document())
        except BaseException:
            lab.abort()  # strategy hosts (and their processes) must not outlive a refusal
            raise
        _log.info(
            "paper.session_resumed",
            run_id=str(run_id),
            processed_through=progress.processed_through.isoformat(),
            minutes=minutes,
            batches=lab.batch_count,
        )
        return session

    async def _replay(self) -> int:
        """Replay the logged live minutes with writes suppressed; verify. Returns the
        number of minutes with bars."""
        progress, lab = self.progress, self.lab
        live = await _load_inputs(self.store, progress.inputs, "live", progress.processed_through)
        chain, minutes = GENESIS, 0
        for minute, group in itertools.groupby(live, key=lambda b: b.open_time):
            bars = list(group)
            chain = chain_hash(chain, bars)
            minutes += 1
            await lab.process_bars(bars, through=minute + MINUTE)
        await lab.process_bars((), through=progress.processed_through)
        if (chain, minutes, len(live), lab.batch_count) != (
            progress.input_sha256,
            progress.minutes,
            progress.input_bars,
            progress.batches,
        ):
            raise SessionVerificationError(
                f"forward session {self.run_id}: its input log (candles) does not match what "
                f"it processed ({len(live)} bars in {minutes} minutes stored, "
                f"{progress.input_bars} in {progress.minutes} processed) — {NEW_SESSION_HINT}"
            )
        replayed = self.recorder.take()
        lab.drain_kill_switch_changes()  # replayed changes are already recorded
        problems = await self.verify(replayed)
        if problems:
            raise SessionVerificationError(
                f"forward session {self.run_id}: the state rebuilt by replay differs from the "
                "database: " + "; ".join(problems[:20]) + f" — {NEW_SESSION_HINT}"
            )
        return minutes

    # ── live ────────────────────────────────────────────────────────────────
    async def process_minute(self, batch: MinuteBatch, *, now: datetime, attempts: int = 3) -> int:
        """Process one live minute and commit it (bars, records, progress) atomically."""
        if batch.minute != self.progress.processed_through:
            raise ForwardSessionError(
                f"minute {batch.minute.isoformat()} is not the next one "
                f"({self.progress.processed_through.isoformat()})"
            )
        sources = self._live_sources()
        bars = [as_input(b, sources.get(b.instrument, b.source)) for b in batch.bars]
        bars.sort(key=lambda b: b.instrument)
        processed = await self.lab.process_bars(bars, through=batch.close_time)
        changes = self.lab.drain_kill_switch_changes()
        last_bars = dict(self.progress.last_bars)
        for bar in bars:
            last_bars[bar.instrument] = bar.open_time
        progress = self.progress.model_copy(
            update={
                "processed_through": batch.close_time,
                "minutes": self.progress.minutes + (1 if bars else 0),
                "input_bars": self.progress.input_bars + len(bars),
                "input_sha256": chain_hash(self.progress.input_sha256, bars)
                if bars
                else self.progress.input_sha256,
                "batches": self.lab.batch_count,
                "last_bars": last_bars,
            }
        )
        records = self.recorder.take()
        for attempt in range(1, attempts + 1):
            try:
                await self.store.commit_minute(
                    self.run_id,
                    records=records,
                    bars=bars,
                    progress=progress.document(),
                    kill_switch_changes=[(at, state.document()) for at, state in changes],
                    now=now,
                )
                break
            except Exception as exc:
                # The transaction rolled back as a whole, so retrying is safe; giving up
                # stops the session (the in-memory state is ahead of the database, and a
                # restart rebuilds it from what was committed).
                _log.error(
                    "paper.commit_failed",
                    minute=batch.minute.isoformat(),
                    attempt=attempt,
                    error=f"{type(exc).__name__}: {exc}"[:500],
                )
                if attempt == attempts:
                    raise
        self.progress = progress
        return processed

    def _live_sources(self) -> dict[str, str]:
        return {
            symbol: segment.source
            for symbol, segments in self.progress.inputs.items()
            for segment in segments
            if segment.phase == "live" and segment.end is None
        }

    def abort(self) -> None:
        """Stop the strategy hosts. The session stays open and resumes on restart."""
        self.lab.abort()

    def instances_status(self) -> dict[str, dict[str, Any]]:
        status: dict[str, dict[str, Any]] = {}
        for member in self.lab.members:
            fault = member.host.fault
            status[member.resolved.id] = {
                "state": member.host.state.value,
                "fault": None if fault is None else f"{fault.error_type}: {fault.message}"[:500],
                "account_id": str(member.accounts[0].account_id) if member.accounts else None,
            }
        return status

    # ── verification ────────────────────────────────────────────────────────
    async def verify(self, replayed: Sequence[Record]) -> list[str]:
        """Differences between the replayed state and the database (empty: identical)."""
        problems: list[str] = []
        expected = _record_counts(replayed)
        recorded = await self.store.run_counts(self.run_id)
        for table, count in sorted(recorded.items()):
            if expected.get(table, 0) != count:
                problems.append(
                    f"{table}: {count} rows recorded, replay produced {expected.get(table, 0)}"
                )
        ledger = [
            (r.id, r.account_id, r.kind, r.amount, r.balance_after)
            for r in replayed
            if isinstance(r, LedgerRecord)
        ]
        recorded_ledger = await self.store.ledger_entries(self.run_id)
        if ledger != recorded_ledger:
            first = next(
                (
                    n
                    for n, (a, b) in enumerate(zip(ledger, recorded_ledger, strict=False))
                    if a != b
                ),
                min(len(ledger), len(recorded_ledger)),
            )
            problems.append(f"ledger entries differ from entry {first + 1} of the session on")
        trades: dict[UUID, TradeRecord] = {}
        for record in replayed:
            if isinstance(record, TradeRecord):
                trades[record.id] = record
        mine = [(t.id, t.status, t.net_pnl, t.exit_time) for _, t in sorted(trades.items())]
        if mine != await self.store.trade_states(self.run_id):
            problems.append("trades differ (ids, status, net P&L or exit time)")
        last_equity: dict[UUID, EquityRecord] = {}
        for record in replayed:
            if isinstance(record, EquityRecord):
                last_equity[record.account_id] = record
        for member in self.lab.members:
            for account in member.accounts:
                check = await self.store.account_check(account.account_id, self.run_id)
                label = f"{account.name}"
                if check.balance != account.balance:
                    problems.append(
                        f"{label}: ledger balance {check.balance}, replay {account.balance}"
                    )
                open_trades = sorted(
                    (
                        p.trade.id,
                        p.trade.instrument,
                        p.trade.direction.value,
                        p.trade.qty,
                        p.trade.entry_price,
                        p.trade.entry_time,
                    )
                    for p in account.positions.values()
                )
                if open_trades != sorted(check.open_trades):
                    problems.append(
                        f"{label}: {len(check.open_trades)} open trades recorded, replay has "
                        f"{len(open_trades)} (or they differ)"
                    )
                equity = last_equity.get(account.account_id)
                snapshot = None if equity is None else (equity.ts, equity.balance, equity.equity)
                if snapshot != check.last_equity:
                    problems.append(
                        f"{label}: latest equity {check.last_equity}, replay {snapshot}"
                    )
        return problems


# ── helpers ──────────────────────────────────────────────────────────────────
async def _open_dedicated(lab: Lab, store: PostgresForwardStore) -> dict[str, AccountOpening]:
    openings: dict[str, AccountOpening] = {}
    for instance_id, account in await lab.provision_dedicated():
        if await store.open_trade_count(account.account_id):
            raise ForwardSessionError(
                f"account {account.name} still has open trades from an earlier session; "
                "end that session first (kterminal paper start --new-session)"
            )
        balance = await store.ledger_balance(account.account_id)
        if balance is None:  # pragma: no cover - provisioning books the deposit
            raise ForwardSessionError(f"account {account.name} has no ledger")
        balance = Decimal(balance)
        mark = await store.high_water_mark(account.account_id)
        openings[instance_id] = AccountOpening(
            account_id=account.account_id,
            config_version_id=account.config_version_id,
            name=account.name,
            balance=balance,
            high_water_mark=max(balance, mark) if mark is not None else balance,
        )
    return openings


def _instance_settings(config: LabConfig) -> dict[str, str]:
    return {i.id: instance_settings_hash(config, i) for i in config.enabled_instances}


def _mismatches(
    plan: SessionPlan, config: LabConfig, catalog: InstrumentCatalog, lab: Lab
) -> list[str]:
    problems = []
    if lab_config_hash(config) != plan.lab_config_hash:
        problems.append(
            "the lab configuration changed (base timeframe, equity snapshot cadence or "
            "external strategies)"
        )
    if catalog.fingerprint != plan.catalog_fingerprint:
        problems.append(
            f"the instrument catalog changed (fingerprint {plan.catalog_fingerprint[:12]} → "
            f"{catalog.fingerprint[:12]})"
        )
    versions = {m.resolved.id: m.resolved.config_hash for m in lab.members}
    settings = _instance_settings(config)
    for instance in sorted(set(versions) | set(plan.versions)):
        old, new = plan.versions.get(instance), versions.get(instance)
        if old is None:
            problems.append(f"instance {instance} was added")
        elif new is None:
            problems.append(f"instance {instance} was removed or disabled")
        elif old != new:
            problems.append(
                f"instance {instance} has a new strategy version ({old[:12]} → {new[:12]})"
            )
        elif plan.instance_settings.get(instance) != settings.get(instance):
            problems.append(
                f"instance {instance} changed its lab settings (account, instruments or timeframes)"
            )
    return problems


async def _assemble_warmup(
    lab: Lab,
    store: PostgresForwardStore,
    providers: Mapping[str, MarketDataProvider],
    live_start: datetime,
    cap_start: datetime,
) -> tuple[list[Bar], dict[str, list[InputSegment]]]:
    bars: list[Bar] = []
    inputs: dict[str, list[InputSegment]] = {}
    for symbol, need in sorted(warmup_need(lab).items()):
        provider = providers.get(symbol)
        if provider is None or not provider.supports(symbol):
            inputs[symbol] = []
            _log.warning("paper.no_provider", instrument=symbol)
            continue
        warm = await _warmup_bars(store, provider, symbol, need, live_start, cap_start)
        segments = []
        if warm:
            segments.append(
                InputSegment(
                    source=provider.name, start=warm[0].open_time, end=live_start, phase="warmup"
                )
            )
        segments.append(InputSegment(source=provider.name, start=live_start, phase="live"))
        inputs[symbol] = segments
        bars.extend(warm)
        _log.info("paper.warmup", instrument=symbol, bars=len(warm), needed=need)
        if len(warm) < need:
            # The cap (warmup_days) or the provider's history was too short: indicators
            # of the instances on this instrument start less primed than they asked for.
            _log.warning(
                "paper.warmup_short",
                instrument=symbol,
                bars=len(warm),
                needed=need,
                reaches_back_to=cap_start.isoformat(),
            )
    bars.sort(key=lambda b: (b.open_time, b.instrument))
    return bars, inputs


async def _warmup_bars(
    store: PostgresForwardStore,
    provider: MarketDataProvider,
    symbol: str,
    need: int,
    live_start: datetime,
    cap_start: datetime,
) -> list[Bar]:
    """The last ``need`` base bars before ``live_start`` (not before ``cap_start``):
    stored candles of the provider's source first, the rest from its history."""
    source = provider.name
    if need <= 0 or cap_start >= live_start:
        return []
    stored = [
        as_input(b, source)
        for b in await store.load_candles(symbol, source=source, start=cap_start, end=live_start)
    ]
    fetched: list[Bar] = []
    tail_from = (
        stored[-1].open_time + MINUTE if stored else max(cap_start, live_start - need * MINUTE)
    )
    bars = list(stored)
    try:
        if tail_from < live_start:
            fetched += _usable(
                await provider.history(symbol, tail_from, live_start), symbol, source
            )
            bars += [b for b in fetched if tail_from <= b.open_time < live_start]
        earliest = bars[0].open_time if bars else tail_from
        span = need * MINUTE
        while len(bars) < need and earliest > cap_start:
            start = max(cap_start, earliest - span)
            older = [
                b
                for b in _usable(await provider.history(symbol, start, earliest), symbol, source)
                if start <= b.open_time < earliest
            ]
            fetched += older
            bars = older + bars
            earliest, span = start, span * 2
    except Exception as exc:  # warm up on what there is; the session records exactly that
        _log.warning(
            "paper.warmup_history_failed",
            instrument=symbol,
            provider=source,
            error=f"{type(exc).__name__}: {exc}"[:500],
        )
    if fetched:
        await store.insert_candles(fetched)
    unique = {b.open_time: b for b in bars}
    return [unique[t] for t in sorted(unique)][-need:]


def _usable(bars: Iterable[Bar], symbol: str, source: str) -> list[Bar]:
    return [
        as_input(b, source)
        for b in bars
        if b.instrument == symbol and b.timeframe == M1 and M1.is_aligned(b.open_time)
    ]


async def _load_inputs(
    store: PostgresForwardStore,
    inputs: Mapping[str, Sequence[InputSegment]],
    phase: str,
    end: datetime,
) -> list[Bar]:
    bars: list[Bar] = []
    for symbol, segments in sorted(inputs.items()):
        for segment in segments:
            if segment.phase != phase:
                continue
            stop = end if segment.end is None else min(segment.end, end)
            if stop <= segment.start:
                continue
            loaded = await store.load_candles(
                symbol, source=segment.source, start=segment.start, end=stop
            )
            bars.extend(as_input(b, segment.source) for b in loaded)
    bars.sort(key=lambda b: (b.open_time, b.instrument))
    return bars


def _reconcile_sources(
    progress: SessionProgress,
    providers: Mapping[str, MarketDataProvider],
    instruments: Sequence[str],
) -> SessionProgress:
    """Start a new live segment for an instrument whose provider changed since the
    session last ran (the replay then reads each period from its own source)."""
    inputs = dict(progress.inputs)
    at = progress.processed_through
    for symbol in instruments:
        provider = providers.get(symbol)
        current = provider.name if provider is not None and provider.supports(symbol) else None
        segments = list(inputs.get(symbol, ()))
        open_live = [s for s in segments if s.phase == "live" and s.end is None]
        live = open_live[0] if open_live else None
        if live is not None and live.source == current:
            continue
        if live is not None:
            segments[segments.index(live)] = live.model_copy(update={"end": at})
        if current is not None:
            segments.append(InputSegment(source=current, start=at, phase="live"))
        if live is not None or current is not None:
            _log.warning(
                "paper.source_changed",
                instrument=symbol,
                before=None if live is None else live.source,
                now=current,
            )
        inputs[symbol] = tuple(segments)
    return progress.model_copy(update={"inputs": inputs})


def _record_counts(records: Sequence[Record]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    orders: set[UUID] = set()
    trades: set[UUID] = set()
    for record in records:
        if isinstance(record, SignalRecord):
            counts["signals"] += 1
        elif isinstance(record, DecisionRecord):
            counts["risk_decisions"] += 1
        elif isinstance(record, OrderRecord):
            orders.add(record.id)
        elif isinstance(record, FillRecord):
            counts["fills"] += 1
        elif isinstance(record, TradeRecord):
            trades.add(record.id)
        elif isinstance(record, LedgerRecord):
            counts["account_ledger"] += 1
        elif isinstance(record, TradeEventRecord):
            counts["trade_events"] += 1
    counts["orders"] = len(orders)
    counts["trades"] = len(trades)
    return dict(counts)


# ── ending a session without replaying it ────────────────────────────────────
async def close_session(
    store: PostgresForwardStore, stored: StoredSession, *, reason: str = "replaced"
) -> int:
    """End an open session: close its open positions at their instrument's last processed
    price (recorded like any exit, reason ``RUN_END``) and mark the run COMPLETED.

    Works from the recorded rows alone, so it also ends a session that can no longer be
    replayed (changed configuration, catalog or strategy code). Returns the number of
    positions closed.
    """
    plan = SessionPlan.model_validate(stored.config["plan"])
    progress = SessionProgress.model_validate(stored.progress)
    at = progress.processed_through
    store.attach(stored)
    open_trades = await store.open_trades(stored.run_id)
    if open_trades:
        if stored.catalog_snapshot_id is None:  # pragma: no cover - sessions always have one
            raise ForwardSessionError(f"session {stored.run_id} has no catalog snapshot")
        catalog = InstrumentCatalog.from_document(
            await store.catalog_document(stored.catalog_snapshot_id)
        )
        config = LabConfig.model_validate(stored.config["lab"])
        instances = {i.id: i for i in config.instances}
        records: list[Record] = []
        for instance_id, group in itertools.groupby(
            sorted(open_trades, key=lambda t: t.trade.instance_id),
            key=lambda t: t.trade.instance_id,
        ):
            trades = list(group)
            account_plan = plan.accounts[instance_id]
            settings = config.account_settings(instances[instance_id])
            markets: dict[str, InstrumentSetup] = {}
            for symbol in instances[instance_id].instruments:
                listing = catalog.execution_listing(settings.venue_profile, symbol)
                markets[symbol] = InstrumentSetup(
                    instrument=catalog.instrument(symbol),
                    listing=listing,
                    costs=catalog.cost_calculator(listing),
                    calendar=catalog.calendar_for(listing),
                )
            account = PaperAccount(
                account_id=account_plan.account_id,
                name=account_plan.name,
                instance_id=instance_id,
                settings=settings,
                config_version_id=account_plan.config_version_id,
                markets=markets,
                timeframe=trades[0].trade.timeframe,
                trading_day_rule=catalog.sessions.trading_day_rule(settings.trading_day),
                classify=catalog.sessions.classify,
            )
            balance = Decimal(await store.ledger_balance(account_plan.account_id))
            mark = await store.high_water_mark(account_plan.account_id)
            account.open_with(balance, max(balance, mark) if mark is not None else balance)
            for open_trade in trades:
                trade = open_trade.trade
                history = await _load_inputs(
                    store,
                    {trade.instrument: progress.inputs.get(trade.instrument, ())},
                    "live",
                    at,
                )
                since_entry = [b for b in history if b.open_time >= trade.entry_time]
                last = history[-1] if history else None
                long = trade.direction.value == "LONG"
                lows = [b.low for b in since_entry] or [trade.entry_price]
                highs = [b.high for b in since_entry] or [trade.entry_price]
                account.restore_position(
                    trade,
                    accrued_until=max(trade.entry_time, last.close_time)
                    if last
                    else trade.entry_time,
                    commission=open_trade.entry_commission,
                    swap=open_trade.swap,
                    funding=open_trade.funding,
                    spread_cost=open_trade.spread_cost,
                    worst=min(min(lows), trade.entry_price)
                    if long
                    else max(max(highs), trade.entry_price),
                    best=max(max(highs), trade.entry_price)
                    if long
                    else min(min(lows), trade.entry_price),
                    mark=last.close if last else trade.entry_price,
                )
            account.close_all(at, "RUN_END")
            account.mark(at)
            records.extend(account.drain())
        await store.write(records, run_id=stored.run_id)
    await store.finish_session(
        stored.run_id,
        status="COMPLETED",
        summary={
            "ended": reason,
            "processed_through": at.isoformat(),
            "minutes": progress.minutes,
            "positions_closed": len(open_trades),
        },
        finished_at=at,
    )
    _log.info(
        "paper.session_ended",
        run_id=str(stored.run_id),
        reason=reason,
        positions_closed=len(open_trades),
    )
    return len(open_trades)


__all__ = [
    "DEFAULT_WARMUP_DAYS",
    "NEW_SESSION_HINT",
    "AccountPlan",
    "ForwardSession",
    "ForwardSessionError",
    "InputSegment",
    "SessionMismatchError",
    "SessionPlan",
    "SessionProgress",
    "SessionVerificationError",
    "as_input",
    "bars_text",
    "chain_hash",
    "close_session",
    "instance_settings_hash",
    "lab_config_hash",
    "period_levels_used",
    "warmup_need",
]
