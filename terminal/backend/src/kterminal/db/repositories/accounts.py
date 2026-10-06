"""Dedicated lab accounts: one virtual account per strategy instance.

Every strategy instance trades on its **own** account (``accounts.
strategy_instance_id`` is unique), so instances can never influence each
other's balance, positions or risk limits, and each one is measured on its own
ledger. :func:`provision_dedicated_account` creates that account on first use
and is idempotent afterwards:

* the account gets a ``DEPOSIT`` ledger entry for its starting balance
  (default $50,000), an allocation to its instance, and configuration version 1;
* re-provisioning with a changed configuration adds a configuration version
  (or re-activates an older one with the same hash) and makes it current —
  risk decisions and trades keep pointing at the version they were made under;
* the starting balance or currency may only change while the account has no
  trades (the change is booked as a ``RESET`` ledger entry); afterwards a new
  balance would rewrite history, so it is refused;
* ``LIVE`` accounts are refused outright: real-money execution does not exist
  in this phase, and enabling it later requires a named user (``live_enabled_by``).

Balances only ever change through ``account_ledger``. Repositories never
commit; the caller owns the transaction.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, NamedTuple
from uuid import UUID

from sqlalchemy import exists, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from kterminal.core.clock import ensure_utc
from kterminal.core.enums import TradingMode
from kterminal.core.errors import KTerminalError, LiveTradingNotPermittedError
from kterminal.core.ids import uuid7
from kterminal.db.audit import hash_document, json_safe
from kterminal.db.locks import lock_key
from kterminal.db.models import (
    AccountAllocationRow,
    AccountConfigVersionRow,
    AccountLedgerRow,
    AccountRow,
    StrategyInstanceRow,
    TradeRow,
    table_of,
)
from kterminal.domain.accounts import DEFAULT_STARTING_BALANCE
from kterminal.observability.logging import get_logger

_log = get_logger(__name__)

_accounts = table_of(AccountRow)
_versions = table_of(AccountConfigVersionRow)
_ledger = table_of(AccountLedgerRow)
_trades = table_of(TradeRow)


class AccountProvisioningError(KTerminalError, ValueError):
    """The account cannot be (re-)provisioned as requested."""


class AccountNotFoundError(KTerminalError, LookupError):
    pass


class ProvisionedAccount(NamedTuple):
    account_id: UUID
    config_version_id: UUID
    created: bool


@dataclass(frozen=True, slots=True)
class AccountState:
    account_id: UUID
    name: str
    mode: TradingMode
    broker: str
    status: str
    currency: str
    starting_balance: Decimal
    balance: Decimal  # balance_after of the latest ledger entry
    ledger_total: Decimal  # Σ ledger amounts; equals balance when the ledger is consistent
    high_water_mark: Decimal
    strategy_instance_id: str | None
    venue_profile_id: str
    config_version_id: UUID | None
    config_version: int | None
    config: dict[str, Any] | None
    open_trades: int
    closed_trades: int
    realized_pnl: Decimal  # Σ net P&L of closed trades, from the recorded trades

    @property
    def ledger_consistent(self) -> bool:
        return self.balance == self.ledger_total


def dedicated_account_name(instance_id: str, starting_balance: Decimal, mode: str = "PAPER") -> str:
    """``Paper 50K · <instance id>`` — the conventional name of a lab account."""
    amount = Decimal(starting_balance)
    label = f"{amount / 1000:.0f}K" if amount >= 1000 and amount % 1000 == 0 else f"{amount:,.2f}"
    return f"{TradingMode(mode).value.title()} {label} · {instance_id}"


async def _latest_balance(session: AsyncSession, account_id: UUID) -> Decimal | None:
    value = (
        await session.execute(
            select(_ledger.c.balance_after)
            .where(_ledger.c.account_id == account_id)
            .order_by(_ledger.c.seq.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return None if value is None else Decimal(value)


async def _has_trades(session: AsyncSession, account_id: UUID) -> bool:
    return bool(
        (
            await session.execute(select(exists().where(_trades.c.account_id == account_id)))
        ).scalar_one()
    )


async def _activate_config(
    session: AsyncSession, account_id: UUID, config: dict[str, Any], config_hash: str
) -> UUID:
    """The version with ``config_hash`` (re-used or created), made current."""
    version_id = (
        await session.execute(
            select(_versions.c.id).where(
                _versions.c.account_id == account_id, _versions.c.config_hash == config_hash
            )
        )
    ).scalar_one_or_none()
    if version_id is None:
        latest = (
            await session.execute(
                select(func.max(_versions.c.version)).where(_versions.c.account_id == account_id)
            )
        ).scalar_one()
        version_id = uuid7()
        await session.execute(
            insert(_versions).values(
                id=version_id,
                account_id=account_id,
                version=(latest or 0) + 1,
                config=config,
                config_hash=config_hash,
            )
        )
    await session.execute(
        update(_accounts)
        .where(
            _accounts.c.id == account_id,
            _accounts.c.current_config_version_id.is_distinct_from(version_id),
        )
        .values(current_config_version_id=version_id)
    )
    return version_id


async def provision_dedicated_account(
    session: AsyncSession,
    *,
    instance_id: str,
    name: str,
    mode: TradingMode | str = TradingMode.PAPER,
    broker: str = "paper",
    currency: str = "USD",
    starting_balance: Decimal = DEFAULT_STARTING_BALANCE,
    venue_profile_id: str,
    config: Mapping[str, Any],
    ts: datetime | None = None,
) -> ProvisionedAccount:
    """Create (or bring up to date) the dedicated account of ``instance_id``.

    ``ts`` is the time of the opening ``DEPOSIT`` (or ``RESET``) entry; the
    database clock is used when omitted.
    """
    mode = TradingMode(mode)
    if mode is TradingMode.LIVE:
        raise LiveTradingNotPermittedError(
            f"refusing to provision a LIVE account for {instance_id!r}: LIVE execution is not "
            "available, and LIVE accounts require explicit enablement by a named user"
        )
    starting_balance = Decimal(starting_balance)
    if not starting_balance.is_finite() or starting_balance <= 0:
        raise AccountProvisioningError(f"starting balance must be positive, got {starting_balance}")
    entry_ts: Any = func.now() if ts is None else ensure_utc(ts)
    document = json_safe(dict(config))
    config_hash = hash_document(document)

    # Serialise provisioning per instance (the unique constraint would reject the
    # second of two concurrent creations; the lock makes the second one a no-op).
    await session.execute(
        select(func.pg_advisory_xact_lock(lock_key(f"kterminal.accounts.provision:{instance_id}")))
    )
    instances = table_of(StrategyInstanceRow)
    if (
        await session.execute(select(instances.c.id).where(instances.c.id == instance_id))
    ).scalar_one_or_none() is None:
        raise AccountProvisioningError(f"unknown strategy instance {instance_id!r}")
    taken = (
        await session.execute(
            select(_accounts.c.strategy_instance_id).where(
                _accounts.c.name == name,
                _accounts.c.strategy_instance_id.is_distinct_from(instance_id),
            )
        )
    ).first()
    if taken is not None:
        raise AccountProvisioningError(f"account name {name!r} is already used by another account")

    account = (
        await session.execute(
            select(_accounts)
            .where(_accounts.c.strategy_instance_id == instance_id)
            .with_for_update()
        )
    ).one_or_none()

    if account is None:
        account_id, version_id = uuid7(), uuid7()
        await session.execute(
            insert(_accounts).values(
                id=account_id,
                name=name,
                mode=mode.value,
                broker=broker,
                venue_profile_id=venue_profile_id,
                currency=currency,
                starting_balance=starting_balance,
                strategy_instance_id=instance_id,
                high_water_mark=starting_balance,
            )
        )
        await session.execute(
            insert(_versions).values(
                id=version_id,
                account_id=account_id,
                version=1,
                config=document,
                config_hash=config_hash,
            )
        )
        await session.execute(
            update(_accounts)
            .where(_accounts.c.id == account_id)
            .values(current_config_version_id=version_id)
        )
        await _allocate(session, account_id, instance_id)
        await session.execute(
            insert(_ledger).values(
                id=uuid7(),
                account_id=account_id,
                ts=entry_ts,
                kind="DEPOSIT",
                amount=starting_balance,
                balance_after=starting_balance,
                note=f"starting balance of {name}",
            )
        )
        _log.info(
            "account.provisioned",
            account_id=str(account_id),
            instance_id=instance_id,
            mode=mode.value,
            starting_balance=str(starting_balance),
        )
        return ProvisionedAccount(account_id, version_id, True)

    account_id = account.id
    if account.mode != mode.value:
        raise AccountProvisioningError(
            f"account {account.name!r} is a {account.mode} account; its mode cannot change "
            f"to {mode.value} (retire it and create a new instance)"
        )
    balance_changed = Decimal(account.starting_balance) != starting_balance
    currency_changed = account.currency != currency
    if (balance_changed or currency_changed) and await _has_trades(session, account_id):
        raise AccountProvisioningError(
            f"account {account.name!r} already has trades: its starting balance and currency "
            "can no longer change (that would rewrite its history) — create a new instance"
        )
    changes: dict[str, Any] = {}
    if balance_changed:
        current = await _latest_balance(session, account_id) or Decimal(0)
        await session.execute(
            insert(_ledger).values(
                id=uuid7(),
                account_id=account_id,
                ts=entry_ts,
                kind="RESET",
                amount=starting_balance - current,
                balance_after=starting_balance,
                note=f"starting balance {account.starting_balance} -> {starting_balance}",
            )
        )
        changes |= {"starting_balance": starting_balance, "high_water_mark": starting_balance}
    if currency_changed:
        changes["currency"] = currency
    for column, value in (
        ("name", name),
        ("broker", broker),
        ("venue_profile_id", venue_profile_id),
    ):
        if getattr(account, column) != value:
            changes[column] = value
    if changes:
        await session.execute(
            update(_accounts).where(_accounts.c.id == account_id).values(**changes)
        )
    version_id = await _activate_config(session, account_id, document, config_hash)
    await _allocate(session, account_id, instance_id)
    return ProvisionedAccount(account_id, version_id, False)


async def _allocate(session: AsyncSession, account_id: UUID, instance_id: str) -> None:
    await session.execute(
        pg_insert(table_of(AccountAllocationRow))
        .values(account_id=account_id, instance_id=instance_id)
        .on_conflict_do_nothing(index_elements=["account_id", "instance_id"])
    )


async def dedicated_account_id(session: AsyncSession, instance_id: str) -> UUID | None:
    return (
        await session.execute(
            select(_accounts.c.id).where(_accounts.c.strategy_instance_id == instance_id)
        )
    ).scalar_one_or_none()


async def get_account_state(session: AsyncSession, account_id: UUID) -> AccountState:
    """Balance from the ledger and trade statistics from the recorded trades."""
    account = (
        await session.execute(select(_accounts).where(_accounts.c.id == account_id))
    ).one_or_none()
    if account is None:
        raise AccountNotFoundError(f"unknown account {account_id}")
    ledger_total = (
        await session.execute(
            select(func.coalesce(func.sum(_ledger.c.amount), 0)).where(
                _ledger.c.account_id == account_id
            )
        )
    ).scalar_one()
    balance = await _latest_balance(session, account_id)
    version = None
    if account.current_config_version_id is not None:
        version = (
            await session.execute(
                select(_versions.c.version, _versions.c.config).where(
                    _versions.c.id == account.current_config_version_id
                )
            )
        ).one()
    trades = (
        await session.execute(
            select(
                func.count().filter(_trades.c.status == "OPEN"),
                func.count().filter(_trades.c.status == "CLOSED"),
                func.coalesce(func.sum(_trades.c.net_pnl).filter(_trades.c.status == "CLOSED"), 0),
            ).where(_trades.c.account_id == account_id)
        )
    ).one()
    return AccountState(
        account_id=account.id,
        name=account.name,
        mode=TradingMode(account.mode),
        broker=account.broker,
        status=account.status,
        currency=account.currency,
        starting_balance=Decimal(account.starting_balance),
        balance=Decimal(0) if balance is None else balance,
        ledger_total=Decimal(ledger_total),
        high_water_mark=Decimal(account.high_water_mark),
        strategy_instance_id=account.strategy_instance_id,
        venue_profile_id=account.venue_profile_id,
        config_version_id=account.current_config_version_id,
        config_version=None if version is None else version.version,
        config=None if version is None else version.config,
        open_trades=int(trades[0]),
        closed_trades=int(trades[1]),
        realized_pnl=Decimal(trades[2]),
    )
