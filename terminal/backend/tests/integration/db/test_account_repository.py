"""Dedicated lab accounts: one per instance, versioned configuration, ledger-only balances."""

from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from kterminal.core.enums import TradingMode
from kterminal.core.errors import LiveTradingNotPermittedError
from kterminal.core.ids import uuid7
from kterminal.db.models import (
    AccountAllocationRow,
    AccountConfigVersionRow,
    AccountLedgerRow,
    AccountRow,
)
from kterminal.db.repositories.accounts import (
    AccountNotFoundError,
    AccountProvisioningError,
    ProvisionedAccount,
    dedicated_account_id,
    dedicated_account_name,
    get_account_state,
    provision_dedicated_account,
)
from tests.integration.db.helpers import (
    T0,
    insert_closed_trade,
    seed_catalog,
    seed_instance,
    seed_lab_subject,
)

pytestmark = pytest.mark.integration

CONFIG = {"starting_balance": Decimal(50_000), "risk_per_trade_pct": Decimal("0.5")}


async def _provision(
    session: AsyncSession, instance_id: str = "demo_sma_fast", **kw: Any
) -> ProvisionedAccount:
    values: dict[str, Any] = {
        "instance_id": instance_id,
        "name": dedicated_account_name(instance_id, Decimal(50_000)),
        "venue_profile_id": "lab_default",
        "config": CONFIG,
        "ts": T0,
    }
    values.update(kw)
    return await provision_dedicated_account(session, **values)


async def _ledger(session: AsyncSession, account_id: UUID) -> list[tuple[Any, ...]]:
    rows = await session.execute(
        select(AccountLedgerRow.kind, AccountLedgerRow.amount, AccountLedgerRow.balance_after)
        .where(AccountLedgerRow.account_id == account_id)
        .order_by(AccountLedgerRow.seq)
    )
    return [tuple(r) for r in rows]


@pytest.fixture
async def lab(session: AsyncSession) -> AsyncSession:
    await seed_catalog(session)
    await seed_instance(session, "demo_sma_fast", params={"fast": 9, "slow": 21})
    await seed_instance(session, "demo_sma_slow", params={"fast": 20, "slow": 50})
    return session


async def test_provisioning_creates_a_paper_50k_account(lab: AsyncSession) -> None:
    account_id, version_id, created = await _provision(lab)
    assert created
    assert await dedicated_account_id(lab, "demo_sma_fast") == account_id

    state = await get_account_state(lab, account_id)
    assert state.name == "Paper 50K · demo_sma_fast"
    assert (state.mode, state.broker, state.currency) == (TradingMode.PAPER, "paper", "USD")
    assert state.starting_balance == state.balance == state.high_water_mark == Decimal(50_000)
    assert state.ledger_consistent
    assert (state.config_version_id, state.config_version) == (version_id, 1)
    assert state.config == {"risk_per_trade_pct": "0.5", "starting_balance": "50000"}
    assert (state.open_trades, state.closed_trades, state.realized_pnl) == (0, 0, Decimal(0))
    assert await _ledger(lab, account_id) == [("DEPOSIT", Decimal(50_000), Decimal(50_000))]
    allocation = await lab.get(AccountAllocationRow, (account_id, "demo_sma_fast"))
    assert allocation is not None and allocation.enabled


async def test_provisioning_is_idempotent(lab: AsyncSession) -> None:
    first = await _provision(lab)
    again = await _provision(lab)
    assert (again.account_id, again.config_version_id, again.created) == (
        first.account_id,
        first.config_version_id,
        False,
    )
    assert len(await _ledger(lab, first.account_id)) == 1  # no second deposit


async def test_configuration_changes_are_versioned(lab: AsyncSession) -> None:
    first = await _provision(lab)
    riskier = {**CONFIG, "risk_per_trade_pct": Decimal("1.0")}
    second = await _provision(lab, config=riskier)
    assert second.account_id == first.account_id
    assert second.config_version_id != first.config_version_id
    assert (await get_account_state(lab, first.account_id)).config_version == 2

    # Returning to an earlier configuration re-activates its version.
    back = await _provision(lab, config=CONFIG)
    assert back.config_version_id == first.config_version_id
    versions = (
        await lab.execute(
            select(func.count()).where(AccountConfigVersionRow.account_id == first.account_id)
        )
    ).scalar_one()
    assert versions == 2
    assert (await get_account_state(lab, first.account_id)).config_version == 1


async def test_live_accounts_are_refused(lab: AsyncSession) -> None:
    with pytest.raises(LiveTradingNotPermittedError, match="LIVE"):
        await _provision(lab, mode="LIVE")
    with pytest.raises(LiveTradingNotPermittedError):
        await _provision(lab, mode=TradingMode.LIVE)
    assert await dedicated_account_id(lab, "demo_sma_fast") is None


async def test_one_dedicated_account_per_instance(lab: AsyncSession) -> None:
    fast = await _provision(lab)
    slow = await _provision(lab, "demo_sma_slow")
    assert fast.account_id != slow.account_id

    with pytest.raises(IntegrityError, match="uq_accounts_strategy_instance_id"):
        async with lab.begin_nested():
            await lab.execute(
                insert(AccountRow).values(
                    id=uuid7(),
                    name="a second account for the same instance",
                    mode="PAPER",
                    broker="paper",
                    venue_profile_id="lab_default",
                    starting_balance=Decimal(50_000),
                    high_water_mark=Decimal(50_000),
                    strategy_instance_id="demo_sma_fast",
                )
            )
    with pytest.raises(AccountProvisioningError, match="already used"):
        await _provision(lab, "demo_sma_slow", name="Paper 50K · demo_sma_fast")


async def test_accounts_are_isolated(lab: AsyncSession) -> None:
    """A trade on one instance's account changes nothing on another's."""
    fast_version, fast = await seed_lab_subject(lab, "demo_sma_fast", fast=9, slow=21)
    _, slow = await seed_lab_subject(lab, "demo_sma_slow", fast=20, slow=50)
    await insert_closed_trade(
        lab,
        instance_id="demo_sma_fast",
        version_id=fast_version,
        account=fast,
        net_pnl=Decimal("496.25"),
    )
    fast_state = await get_account_state(lab, fast.account_id)
    slow_state = await get_account_state(lab, slow.account_id)
    assert (fast_state.closed_trades, fast_state.realized_pnl) == (1, Decimal("496.25"))
    assert (slow_state.closed_trades, slow_state.realized_pnl) == (0, Decimal(0))
    assert slow_state.balance == Decimal(50_000)


async def test_starting_balance_changes_only_before_trading(lab: AsyncSession) -> None:
    first = await _provision(lab)
    bigger = await _provision(lab, starting_balance=Decimal(100_000), config=CONFIG)
    assert bigger.account_id == first.account_id
    state = await get_account_state(lab, first.account_id)
    assert state.starting_balance == state.balance == state.high_water_mark == Decimal(100_000)
    assert state.ledger_consistent
    assert await _ledger(lab, first.account_id) == [
        ("DEPOSIT", Decimal(50_000), Decimal(50_000)),
        ("RESET", Decimal(50_000), Decimal(100_000)),
    ]

    version_id = await seed_instance(lab, "demo_sma_fast", params={"fast": 9, "slow": 21})
    await insert_closed_trade(
        lab, instance_id="demo_sma_fast", version_id=version_id, account=bigger, net_pnl=Decimal(1)
    )
    with pytest.raises(AccountProvisioningError, match="already has trades"):
        await _provision(lab, starting_balance=Decimal(50_000))
    with pytest.raises(AccountProvisioningError, match="already has trades"):
        await _provision(lab, starting_balance=Decimal(100_000), currency="EUR")
    # Other settings may still evolve as new configuration versions.
    later = await _provision(
        lab, starting_balance=Decimal(100_000), config={**CONFIG, "max_open_positions": 2}
    )
    assert later.config_version_id != bigger.config_version_id


async def test_invalid_provisioning_requests(lab: AsyncSession) -> None:
    with pytest.raises(AccountProvisioningError, match="positive"):
        await _provision(lab, starting_balance=Decimal(0))
    with pytest.raises(AccountProvisioningError, match="unknown strategy instance"):
        await _provision(lab, "ghost")
    await _provision(lab)
    with pytest.raises(AccountProvisioningError, match="mode cannot change"):
        await _provision(lab, mode="BACKTEST")
    with pytest.raises(AccountNotFoundError):
        await get_account_state(lab, uuid7())


def test_dedicated_account_names() -> None:
    assert dedicated_account_name("orb_ny_15_mnq", Decimal(50_000)) == "Paper 50K · orb_ny_15_mnq"
    assert dedicated_account_name("x", Decimal("25000.50")) == "Paper 25,000.50 · x"
