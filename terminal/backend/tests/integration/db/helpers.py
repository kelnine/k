"""Test data for the schema tests: a small normalised catalog and row factories."""

import copy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from kterminal.core.enums import StrategyKind
from kterminal.core.ids import new_correlation_id, uuid7
from kterminal.db.audit import hash_document
from kterminal.db.models import SignalRow, TradeRow
from kterminal.db.repositories.accounts import ProvisionedAccount, provision_dedicated_account
from kterminal.db.repositories.catalog import apply_catalog
from kterminal.db.repositories.strategies import (
    DefinitionRecord,
    InstanceRecord,
    VersionRecord,
    get_or_create_version,
    upsert_definition,
    upsert_instance,
)

T0 = datetime(2026, 10, 5, 13, 30, tzinfo=UTC)  # 09:30 New York (EDT)

_CATALOG: dict[str, Any] = {
    "trading_day_rules": [
        {"id": "ny_1700", "timezone": "America/New_York", "rollover": "17:00"},
        {"id": "utc_midnight", "timezone": "UTC", "rollover": "00:00"},
    ],
    "calendars": [
        {
            "id": "metals_otc",
            "timezone": "America/New_York",
            "always_open": False,
            "weekly": ["SUN 18:00 - MON 17:00", "MON 18:00 - TUE 17:00"],
            "holiday_rule": "calendar_date",
            "holidays": [],
            "early_closes": {},
            "description": "Spot metals",
        },
        {
            "id": "cme_globex_equity",
            "timezone": "America/Chicago",
            "always_open": False,
            "weekly": ["SUN 17:00 - MON 16:00"],
            "holiday_rule": "trade_date",
            "holidays": ["2026-12-25"],
            "early_closes": {"2026-11-27": "12:15"},
            "description": "CME Globex equity index",
        },
        {
            "id": "crypto_24x7",
            "timezone": "UTC",
            "always_open": True,
            "weekly": [],
            "holiday_rule": "calendar_date",
            "holidays": [],
            "early_closes": {},
            "description": "",
        },
    ],
    "session_windows": [
        {
            "id": "ny_orb_15",
            "name": "New York ORB 15m",
            "timezone": "America/New_York",
            "start": "09:30",
            "end": "09:45",
            "days": ["MON", "TUE", "WED", "THU", "FRI"],
            "description": "",
        },
        {
            "id": "london",
            "name": "London session",
            "timezone": "Europe/London",
            "start": "08:00",
            "end": "16:30",
            "days": ["MON", "TUE", "WED", "THU", "FRI"],
            "description": "",
        },
        {
            "id": "asia",
            "name": "Asia",
            "timezone": "America/New_York",
            "start": "19:00",
            "end": "03:00",
            "days": ["SUN", "MON", "TUE", "WED", "THU"],
            "description": "crosses midnight",
        },
    ],
    "session_classification": ["asia", "london"],
    "cost_profiles": [
        {
            "id": "zero_cost",
            "description": "Frictionless",
            "spread": {"model": "none"},
            "commission": {"model": "none"},
            "slippage": {"model": "none"},
            "funding": {"model": "none"},
            "swap": {"model": "none"},
        },
        {
            "id": "binance_usdm_taker",
            "description": "USD-M taker",
            "spread": {"model": "fixed_ticks", "ticks": "1"},
            "commission": {"model": "notional", "maker_rate": "0.0002", "taker_rate": "0.0005"},
            "slippage": {"model": "fixed_ticks", "ticks": "1"},
            "funding": {
                "model": "constant",
                "rate_per_interval": "0.0001",
                "interval_hours": 8,
                "anchor_hours_utc": [0, 8, 16],
            },
            "swap": {"model": "none"},
        },
    ],
    "venues": [
        {
            "id": "generic_mt5_cfd",
            "name": "Generic MT5 CFD server",
            "kind": "PROP_FIRM",
            "platform": "MT5",
            "timezone": "Etc/GMT-2",
            "symbol_suffixes": [".r", "m"],
            "description": "",
        },
        {
            "id": "binance_usdm",
            "name": "Binance USD-M",
            "kind": "EXCHANGE",
            "platform": "BINANCE",
            "timezone": "UTC",
            "symbol_suffixes": [],
            "description": "",
        },
        {
            "id": "cme",
            "name": "CME Globex",
            "kind": "EXCHANGE",
            "platform": "CME_GLOBEX",
            "timezone": "America/Chicago",
            "symbol_suffixes": [],
            "description": "",
        },
        {
            "id": "tradingview",
            "name": "TradingView",
            "kind": "DATA_FEED",
            "platform": "TRADINGVIEW",
            "timezone": "UTC",
            "symbol_suffixes": [],
            "description": "",
        },
    ],
    "instruments": [
        {
            "symbol": "XAUUSD",
            "name": "Gold / US Dollar",
            "asset_class": "METAL",
            "base": "XAU",
            "quote_currency": "USD",
            "tick_size": "0.01",
            "trading_hours": "metals_otc",
            "trading_day": "ny_1700",
            "underlying": "GOLD",
            "futures": None,
            "description": "",
            "tags": ["metals"],
        },
        {
            "symbol": "NEARUSD",
            "name": "NEAR / US Dollar",
            "asset_class": "CRYPTO",
            "base": "NEAR",
            "quote_currency": "USD",
            "tick_size": "0.001",
            "trading_hours": "crypto_24x7",
            "trading_day": "utc_midnight",
            "underlying": "NEAR",
            "futures": None,
            "description": "",
            "tags": ["crypto"],
        },
        {
            "symbol": "MNQ",
            "name": "Micro E-mini Nasdaq-100",
            "asset_class": "INDEX",
            "base": "NDX",
            "quote_currency": "USD",
            "tick_size": "0.25",
            "trading_hours": "cme_globex_equity",
            "trading_day": "ny_1700",
            "underlying": "NASDAQ100",
            "futures": {
                "root": "MNQ",
                "contract_months": "HMUZ",
                "expiry_rule": "third_friday",
                "roll_days_before_expiry": 8,
            },
            "description": "",
            "tags": ["futures"],
        },
    ],
    "listings": [
        {
            "venue": "generic_mt5_cfd",
            "instrument": "XAUUSD",
            "venue_symbol": "XAUUSD",
            "contract_type": "CFD",
            "tick_size": "0.01",
            "contract_size": "100",
            "quantity_unit": "LOTS",
            "min_qty": "0.01",
            "qty_step": "0.01",
            "quote_currency": "USD",
            "max_qty": "50",
            "min_notional": None,
            "pnl_model": "LINEAR",
            "trading_hours": None,
            "cost_profile": "zero_cost",
            "symbol_format": None,
            "tradable": True,
            "verified_on": "2026-10-01",
            "source": "broker contract specs",
            "notes": "",
            "aliases": ["GOLD"],
        },
        {
            "venue": "binance_usdm",
            "instrument": "NEARUSD",
            "venue_symbol": "NEARUSDT",
            "contract_type": "PERPETUAL",
            "tick_size": "0.001",
            "contract_size": "1",
            "quantity_unit": "BASE_UNITS",
            "min_qty": "1",
            "qty_step": "1",
            "quote_currency": "USDT",
            "max_qty": None,
            "min_notional": "5",
            "pnl_model": "LINEAR",
            "trading_hours": None,
            "cost_profile": "binance_usdm_taker",
            "symbol_format": None,
            "tradable": True,
            "verified_on": None,
            "source": "",
            "notes": "",
            "aliases": [],
        },
        {
            "venue": "cme",
            "instrument": "MNQ",
            "venue_symbol": "MNQ",
            "contract_type": "FUTURE",
            "tick_size": "0.25",
            "contract_size": "2",
            "quantity_unit": "CONTRACTS",
            "min_qty": "1",
            "qty_step": "1",
            "quote_currency": "USD",
            "max_qty": None,
            "min_notional": None,
            "pnl_model": "LINEAR",
            "trading_hours": "cme_globex_equity",
            "cost_profile": "zero_cost",
            "symbol_format": "{root}{code}{y1}",
            "tradable": True,
            "verified_on": None,
            "source": "",
            "notes": "",
            "aliases": [],
        },
        {
            "venue": "tradingview",
            "instrument": "MNQ",
            "venue_symbol": "CME_MINI:MNQ1!",
            "contract_type": "INDEX_DATA",
            "tick_size": "0.25",
            "contract_size": "2",
            "quantity_unit": "CONTRACTS",
            "min_qty": "1",
            "qty_step": "1",
            "quote_currency": "USD",
            "max_qty": None,
            "min_notional": None,
            "pnl_model": "LINEAR",
            "trading_hours": None,
            "cost_profile": None,
            "symbol_format": None,
            "tradable": False,
            "verified_on": None,
            "source": "",
            "notes": "",
            "aliases": [],
        },
    ],
    "aliases": [
        {"source": "*", "alias": "GOLD", "instrument": "XAUUSD"},
        {"source": "*", "alias": "NEAR", "instrument": "NEARUSD"},
        {"source": "tradingview", "alias": "CME_MINI:MNQ1!", "instrument": "MNQ"},
        {"source": "tradingview", "alias": "BINANCE:NEARUSDT.P", "instrument": "NEARUSD"},
    ],
    "venue_profiles": [
        {
            "id": "lab_default",
            "description": "Shared simulated conditions for lab paper accounts",
            "execution": {
                "XAUUSD": "generic_mt5_cfd:XAUUSD",
                "NEARUSD": "binance_usdm:NEARUSD",
                "MNQ": "cme:MNQ",
            },
            "data": {"MNQ": "tradingview:MNQ"},
        }
    ],
}


def catalog_document() -> dict[str, Any]:
    return copy.deepcopy(_CATALOG)


async def seed_catalog(session: AsyncSession, fingerprint: str = "fp-base") -> UUID:
    return (await apply_catalog(session, catalog_document(), fingerprint, applied_by="test")).id


async def seed_instance(
    session: AsyncSession,
    instance_id: str,
    *,
    definition_id: str = "demo_sma_cross",
    params: dict[str, Any] | None = None,
) -> UUID:
    """A definition, an instance of it and its current version; returns the version id."""
    params = params if params is not None else {"fast": 9, "slow": 21}
    await upsert_definition(
        session,
        DefinitionRecord(
            id=definition_id,
            name=definition_id.replace("_", " ").title(),
            kind=StrategyKind.INTERNAL,
            latest_version="1.0.0",
            module=f"kterminal.strategies.{definition_id}",
        ),
    )
    await upsert_instance(
        session,
        InstanceRecord(id=instance_id, definition_id=definition_id, name=instance_id),
    )
    config = {"definition": definition_id, "params": params, "instruments": ["XAUUSD"]}
    return await get_or_create_version(
        session,
        VersionRecord(
            instance_id=instance_id,
            definition_id=definition_id,
            definition_version="1.0.0",
            code_hash="c0de",
            params=params,
            params_hash=hash_document(params),
            config=config,
            config_hash=hash_document(config),
        ),
    )


async def seed_lab_subject(
    session: AsyncSession, instance_id: str, **params: Any
) -> tuple[UUID, ProvisionedAccount]:
    """Instance + version + its dedicated Paper 50K account (catalog must be applied)."""
    version_id = await seed_instance(session, instance_id, params=params or None)
    account = await provision_dedicated_account(
        session,
        instance_id=instance_id,
        name=f"Paper 50K · {instance_id}",
        venue_profile_id="lab_default",
        config={"starting_balance": Decimal(50_000), "risk_per_trade_pct": Decimal("0.5")},
        ts=T0,
    )
    return version_id, account


async def insert_signal(
    session: AsyncSession,
    *,
    instance_id: str,
    version_id: UUID | None,
    definition_id: str = "demo_sma_cross",
    status: str = "ROUTED",
    instrument: str | None = "XAUUSD",
    action: str | None = "LONG",
    **overrides: Any,
) -> UUID:
    signal_id = uuid7()
    values: dict[str, Any] = {
        "id": signal_id,
        "strategy_instance_id": instance_id,
        "strategy_version_id": version_id,
        "definition_id": definition_id,
        "source": "INTERNAL",
        "instrument": instrument,
        "raw_symbol": instrument,
        "timeframe": "5m",
        "bar_time": T0 - timedelta(minutes=5),
        "signal_time": T0,
        "received_at": T0,
        "action": action,
        "entry": Decimal("2650.00"),
        "stop_loss": Decimal("2640.00"),
        "take_profit": Decimal("2670.00"),
        "idempotency_key": f"{instance_id}:{signal_id}",
        "status": status,
        "correlation_id": new_correlation_id(),
    }
    values.update(overrides)
    await session.execute(insert(SignalRow).values(**values))
    return signal_id


async def insert_closed_trade(
    session: AsyncSession,
    *,
    instance_id: str,
    version_id: UUID,
    account: ProvisionedAccount,
    net_pnl: Decimal,
    **overrides: Any,
) -> UUID:
    signal_id = await insert_signal(session, instance_id=instance_id, version_id=version_id)
    trade_id = uuid7()
    values: dict[str, Any] = {
        "id": trade_id,
        "account_id": account.account_id,
        "account_config_version_id": account.config_version_id,
        "strategy_instance_id": instance_id,
        "strategy_version_id": version_id,
        "entry_signal_id": signal_id,
        "mode": "PAPER",
        "instrument": "XAUUSD",
        "venue": "generic_mt5_cfd",
        "venue_symbol": "XAUUSD",
        "timeframe": "5m",
        "direction": "LONG",
        "qty": Decimal("0.25"),
        "entry_requested": Decimal("2650.00"),
        "entry_price": Decimal("2650.10"),
        "entry_time": T0,
        "initial_stop": Decimal("2640.00"),
        "initial_risk": Decimal("252.50"),
        "exit_price": Decimal("2670.00"),
        "exit_time": T0 + timedelta(hours=1),
        "exit_reason": "TAKE_PROFIT",
        "gross_pnl": net_pnl,
        "net_pnl": net_pnl,
        "status": "CLOSED",
        "correlation_id": new_correlation_id(),
    }
    values.update(overrides)
    await session.execute(insert(TradeRow).values(**values))
    return trade_id
