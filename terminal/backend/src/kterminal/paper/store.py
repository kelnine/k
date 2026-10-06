"""Where the lab persists what happens.

``LabStore`` is the persistence boundary of the lab: strategy registration,
account provisioning, runs, and the record stream. ``InMemoryLabStore`` backs
unit tests; ``kterminal.paper.pg_store.PostgresLabStore`` writes the
production schema.
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

from kterminal.core.canonical import hash_data
from kterminal.core.ids import uuid7
from kterminal.domain.accounts import AccountSettings
from kterminal.paper.records import (
    DecisionRecord,
    EquityRecord,
    FaultRecord,
    FillRecord,
    LedgerRecord,
    OrderRecord,
    Record,
    SignalRecord,
    TradeEventRecord,
    TradeRecord,
)
from kterminal.strategy_engine.instances import ResolvedInstance

if TYPE_CHECKING:
    from kterminal.paper.demo import IsolationCheck


@dataclass(frozen=True, slots=True)
class ProvisionedAccount:
    account_id: UUID
    config_version_id: UUID
    name: str
    created: bool


class LabStore(Protocol):
    async def apply_catalog(
        self, *, document: dict[str, Any], fingerprint: str, applied_by: str
    ) -> None:
        """Make the catalog (venue profiles, listings, cost profiles) referenceable.
        Idempotent per fingerprint; ``start_run`` applies the run's catalog itself."""
        ...

    async def start_run(
        self,
        *,
        kind: str,
        name: str,
        config: dict[str, Any],
        catalog_document: dict[str, Any],
        catalog_fingerprint: str,
        started_at: datetime,
    ) -> UUID: ...

    async def register_instance(self, resolved: ResolvedInstance) -> UUID:
        """Upsert definition + instance; return the strategy version id for its config hash."""
        ...

    async def provision_account(
        self,
        *,
        instance_id: str,
        name: str,
        settings: AccountSettings,
        run_id: UUID | None = None,
        opened_at: datetime | None = None,
    ) -> ProvisionedAccount:
        """The account an instance trades in. With ``run_id`` (simulations) a fresh
        run-scoped account; without it, the instance's persistent dedicated account."""
        ...

    async def write(self, records: Sequence[Record], *, run_id: UUID) -> None: ...

    async def finish_run(
        self, run_id: UUID, *, status: str, summary: dict[str, Any], finished_at: datetime
    ) -> None: ...

    async def closed_trades(self, account_id: UUID) -> list[TradeRecord]:
        """Trades as recorded (the source of every metric)."""
        ...

    async def ledger_balance(self, account_id: UUID) -> Any: ...

    async def isolation_checks(self, run_id: UUID) -> list["IsolationCheck"]:
        """Per-account audit computed from the recorded rows of ``run_id``."""
        ...


@dataclass
class InMemoryLabStore:
    runs: dict[UUID, dict[str, Any]] = field(default_factory=dict)
    versions: dict[tuple[str, str], UUID] = field(default_factory=dict)
    accounts: dict[str, ProvisionedAccount] = field(default_factory=dict)
    account_configs: dict[UUID, list[tuple[UUID, str]]] = field(default_factory=dict)
    records: dict[type, list[Any]] = field(default_factory=lambda: defaultdict(list))
    trades: dict[UUID, TradeRecord] = field(default_factory=dict)
    starting_balances: dict[UUID, Decimal] = field(default_factory=dict)
    catalogs: set[str] = field(default_factory=set)

    async def apply_catalog(
        self, *, document: dict[str, Any], fingerprint: str, applied_by: str
    ) -> None:
        self.catalogs.add(fingerprint)

    async def start_run(
        self,
        *,
        kind: str,
        name: str,
        config: dict[str, Any],
        catalog_document: dict[str, Any],
        catalog_fingerprint: str,
        started_at: datetime,
    ) -> UUID:
        run_id = uuid7()
        self.catalogs.add(catalog_fingerprint)
        self.runs[run_id] = {
            "kind": kind,
            "name": name,
            "config": config,
            "status": "RUNNING",
            "catalog_fingerprint": catalog_fingerprint,
            "started_at": started_at,
        }
        return run_id

    async def register_instance(self, resolved: ResolvedInstance) -> UUID:
        key = (resolved.id, resolved.config_hash)
        if key not in self.versions:
            self.versions[key] = uuid7()
        return self.versions[key]

    async def provision_account(
        self,
        *,
        instance_id: str,
        name: str,
        settings: AccountSettings,
        run_id: UUID | None = None,
        opened_at: datetime | None = None,
    ) -> ProvisionedAccount:
        config_hash = hash_data(settings.document())
        existing = self.accounts.get(instance_id)
        if existing is not None:
            history = self.account_configs[existing.account_id]
            for version_id, known_hash in history:
                if known_hash == config_hash:
                    return ProvisionedAccount(existing.account_id, version_id, existing.name, False)
            version_id = uuid7()
            history.append((version_id, config_hash))
            updated = ProvisionedAccount(existing.account_id, version_id, existing.name, False)
            self.accounts[instance_id] = updated
            return updated
        account = ProvisionedAccount(uuid7(), uuid7(), name, True)
        self.accounts[instance_id] = account
        self.starting_balances[account.account_id] = settings.starting_balance
        self.account_configs[account.account_id] = [(account.config_version_id, config_hash)]
        return account

    async def write(self, records: Sequence[Record], *, run_id: UUID) -> None:
        for record in records:
            self.records[type(record)].append(record)
            if isinstance(record, TradeRecord):
                self.trades[record.id] = record

    async def finish_run(
        self, run_id: UUID, *, status: str, summary: dict[str, Any], finished_at: datetime
    ) -> None:
        self.runs[run_id].update(status=status, summary=summary, finished_at=finished_at)

    async def closed_trades(self, account_id: UUID) -> list[TradeRecord]:
        return sorted(
            (
                t
                for t in self.trades.values()
                if t.account_id == account_id and t.status == "CLOSED"
            ),
            key=lambda t: (t.exit_time or t.entry_time, t.id),
        )

    async def ledger_balance(self, account_id: UUID) -> Any:
        entries = [r for r in self.records[LedgerRecord] if r.account_id == account_id]
        return entries[-1].balance_after if entries else None

    async def isolation_checks(self, run_id: UUID) -> list["IsolationCheck"]:
        from kterminal.paper.demo import IsolationCheck

        signal_owner = {s.id: s.instance_id for s in self.records[SignalRecord]}
        checks = []
        for instance_id, account in sorted(self.accounts.items()):
            decisions = [
                d for d in self.records[DecisionRecord] if d.account_id == account.account_id
            ]
            trades = [t for t in self.trades.values() if t.account_id == account.account_id]
            ledger = [e for e in self.records[LedgerRecord] if e.account_id == account.account_id]
            start = self.starting_balances.get(account.account_id, Decimal(0))
            balance = ledger[-1].balance_after if ledger else start
            checks.append(
                IsolationCheck(
                    instance_id=instance_id,
                    account_id=str(account.account_id),
                    decisions=len(decisions),
                    decisions_on_foreign_signals=sum(
                        1 for d in decisions if signal_owner.get(d.signal_id) != instance_id
                    ),
                    trades=len(trades),
                    trades_of_other_instances=sum(
                        1 for t in trades if t.instance_id != instance_id
                    ),
                    ledger_entries=len(ledger),
                    balance_matches_ledger=balance == start + sum(e.amount for e in ledger),
                )
            )
        return checks

    # convenience for tests
    def of(self, kind: type) -> list[Any]:
        return list(self.records.get(kind, []))


__all__ = [
    "DecisionRecord",
    "EquityRecord",
    "FaultRecord",
    "FillRecord",
    "InMemoryLabStore",
    "LabStore",
    "LedgerRecord",
    "OrderRecord",
    "ProvisionedAccount",
    "SignalRecord",
    "TradeEventRecord",
]
