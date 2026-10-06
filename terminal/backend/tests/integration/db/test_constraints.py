"""The database itself enforces the safety and isolation rules (CHECKs and composite FKs)."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import insert, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from kterminal.core.ids import new_correlation_id, uuid7
from kterminal.db.models import AccountRow, InstrumentRow, OrderRow, TradeRow
from tests.integration.db.helpers import (
    insert_closed_trade,
    insert_signal,
    seed_catalog,
    seed_instance,
    seed_lab_subject,
)

pytestmark = pytest.mark.integration

T0 = datetime(2026, 10, 6, 14, 0, tzinfo=UTC)


async def _rejected(
    session: AsyncSession, action: Callable[[], Awaitable[Any]], constraint: str
) -> None:
    with pytest.raises(IntegrityError, match=constraint):
        async with session.begin_nested():
            await action()


def _account(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "id": uuid7(),
        "name": f"account {uuid7()}",
        "mode": "PAPER",
        "broker": "paper",
        "venue_profile_id": "lab_default",
        "starting_balance": Decimal(50_000),
        "high_water_mark": Decimal(50_000),
    }
    values.update(overrides)
    return values


def _order(account_id: Any, **overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "id": uuid7(),
        "client_order_id": f"kt-{uuid7()}",
        "account_id": account_id,
        "purpose": "ENTRY",
        "mode": "PAPER",
        "venue": "generic_mt5_cfd",
        "instrument": "XAUUSD",
        "venue_symbol": "XAUUSD",
        "side": "BUY",
        "order_type": "MARKET",
        "qty": Decimal("0.10"),
        "status": "PENDING_SUBMIT",
        "created_at": T0,
        "correlation_id": new_correlation_id(),
    }
    values.update(overrides)
    return values


async def test_live_account_requires_an_enabling_user(session: AsyncSession) -> None:
    await seed_catalog(session)
    await _rejected(
        session,
        lambda: session.execute(insert(AccountRow).values(**_account(mode="LIVE"))),
        "ck_accounts_live_enabled",
    )
    # A PAPER account can never be flipped to LIVE behind the system's back either.
    paper = _account()
    await session.execute(insert(AccountRow).values(**paper))
    await _rejected(
        session,
        lambda: session.execute(
            update(AccountRow).where(AccountRow.id == paper["id"]).values(mode="LIVE")
        ),
        "ck_accounts_live_enabled",
    )


async def test_entry_order_requires_a_risk_decision(session: AsyncSession) -> None:
    await seed_catalog(session)
    account = _account()
    await session.execute(insert(AccountRow).values(**account))
    await _rejected(
        session,
        lambda: session.execute(insert(OrderRow).values(**_order(account["id"]))),
        "ck_orders_entry_has_risk_decision",
    )
    # Risk-reducing orders do not need one.
    await session.execute(insert(OrderRow).values(**_order(account["id"], purpose="EXIT")))


@pytest.mark.parametrize(
    ("column", "value", "constraint"),
    [
        ("mode", "REAL_MONEY", "ck_accounts_mode"),
        ("status", "HAPPY", "ck_accounts_status"),
        ("starting_balance", Decimal(0), "ck_accounts_starting_balance_positive"),
    ],
)
async def test_invalid_account_values_are_rejected(
    session: AsyncSession, column: str, value: Any, constraint: str
) -> None:
    await seed_catalog(session)
    await _rejected(
        session,
        lambda: session.execute(insert(AccountRow).values(**_account(**{column: value}))),
        constraint,
    )


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"action": "BUY"}, "ck_signals_action"),
        ({"source": "TELEGRAM"}, "ck_signals_source"),
        ({"order_type": "ICEBERG"}, "ck_signals_order_type"),
        ({"status": "LOST"}, "ck_signals_status"),
        ({"confidence": Decimal("1.5")}, "ck_signals_confidence_range"),
        ({"risk_pct": Decimal(0)}, "ck_signals_risk_pct_range"),
    ],
)
async def test_invalid_signal_values_are_rejected(
    session: AsyncSession, overrides: dict[str, Any], constraint: str
) -> None:
    await seed_catalog(session)
    version_id = await seed_instance(session, "demo_sma_fast")
    await _rejected(
        session,
        lambda: insert_signal(
            session, instance_id="demo_sma_fast", version_id=version_id, **overrides
        ),
        constraint,
    )


async def test_invalid_instrument_values_are_rejected(session: AsyncSession) -> None:
    await seed_catalog(session)
    await _rejected(
        session,
        lambda: session.execute(
            update(InstrumentRow)
            .where(InstrumentRow.symbol == "XAUUSD")
            .values(asset_class="STOCK")
        ),
        "ck_instruments_asset_class",
    )


async def test_only_invalid_signals_may_lack_a_version(session: AsyncSession) -> None:
    await seed_catalog(session)
    await seed_instance(session, "tv_breakout")
    # A malformed webhook payload is still recorded, for diagnosis …
    await insert_signal(
        session,
        instance_id="tv_breakout",
        version_id=None,
        status="INVALID",
        instrument=None,
        action=None,
        source="TRADINGVIEW",
        raw_symbol="BINANCE:WHATEVER",
        reject_code="UNKNOWN_SYMBOL",
    )
    # … but anything routed must name the exact strategy version that produced it.
    await _rejected(
        session,
        lambda: insert_signal(session, instance_id="tv_breakout", version_id=None),
        "ck_signals_valid_signal_complete",
    )


async def test_a_signal_cannot_borrow_another_instances_version(session: AsyncSession) -> None:
    """Isolation at the storage level: version and definition must match the instance."""
    await seed_catalog(session)
    fast = await seed_instance(session, "demo_sma_fast", params={"fast": 9, "slow": 21})
    await seed_instance(session, "demo_sma_slow", params={"fast": 20, "slow": 50})
    await seed_instance(session, "orb_ny_15_mnq", definition_id="orb")
    await _rejected(
        session,
        lambda: insert_signal(session, instance_id="demo_sma_slow", version_id=fast),
        "fk_signals_strategy_instance_id_strategy_version_id",
    )
    await _rejected(
        session,
        lambda: insert_signal(
            session,
            instance_id="orb_ny_15_mnq",
            version_id=None,
            status="INVALID",
            definition_id="demo_sma_cross",
        ),
        "fk_signals_strategy_instance_id_definition_id",
    )


async def test_a_trade_cannot_use_another_accounts_configuration(session: AsyncSession) -> None:
    await seed_catalog(session)
    fast_version, fast = await seed_lab_subject(session, "demo_sma_fast", fast=9, slow=21)
    _, slow = await seed_lab_subject(session, "demo_sma_slow", fast=20, slow=50)
    await _rejected(
        session,
        lambda: insert_closed_trade(
            session,
            instance_id="demo_sma_fast",
            version_id=fast_version,
            account=fast._replace(config_version_id=slow.config_version_id),
            net_pnl=Decimal(100),
        ),
        "fk_trades_account_id_account_config_version_id",
    )


async def test_closed_trades_must_be_complete(session: AsyncSession) -> None:
    await seed_catalog(session)
    version_id, account = await seed_lab_subject(session, "demo_sma_fast")
    await _rejected(
        session,
        lambda: insert_closed_trade(
            session,
            instance_id="demo_sma_fast",
            version_id=version_id,
            account=account,
            net_pnl=Decimal(1),
            exit_reason=None,
        ),
        "ck_trades_closed_trade_complete",
    )
    await _rejected(
        session,
        lambda: insert_closed_trade(
            session,
            instance_id="demo_sma_fast",
            version_id=version_id,
            account=account,
            net_pnl=Decimal(1),
            exit_reason="BECAUSE",
        ),
        "ck_trades_exit_reason",
    )


async def test_trades_must_reference_a_known_listing(session: AsyncSession) -> None:
    await seed_catalog(session)
    version_id, account = await seed_lab_subject(session, "demo_sma_fast")
    await _rejected(
        session,
        lambda: insert_closed_trade(
            session,
            instance_id="demo_sma_fast",
            version_id=version_id,
            account=account,
            net_pnl=Decimal(1),
            venue="binance_usdm",  # XAUUSD is not listed there
        ),
        "fk_trades_venue_instrument",
    )
    rows = (await session.execute(TradeRow.__table__.select())).all()
    assert rows == []
