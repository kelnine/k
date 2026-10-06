"""SQLAlchemy 2.0 models — the production PostgreSQL 16 schema (Phase 2).

The authoritative description is ``terminal/docs/04-database-schema.md``; this
module is its executable form and the Alembic migration in
``kterminal/db/migrations`` is generated from (and checked against) it.

Conventions, and why:

* **UUIDv7 primary keys generated in Python** (:func:`kterminal.core.ids.uuid7`):
  the application knows a row's id before it is written, so a whole audit
  chain (signal → decision → order → fill → trade → ledger) can be built in
  memory and flushed in one transaction; time-ordered ids keep B-trees compact.
  Configuration objects (venues, instruments, strategy definitions and
  instances, experiments) are keyed by their human-readable slug instead.
* **timestamptz everywhere**, bound through :class:`UTCDateTime`, which rejects
  naive datetimes and always returns UTC.
* **NUMERIC, never float**: prices and quantities ``NUMERIC(24,10)``, money
  ``NUMERIC(20,4)`` in the account currency, percentages ``NUMERIC(8,4)``.
* **Enumerations are ``text`` + ``CHECK``** with the values of the Python enums
  (``kterminal.core.enums``, ``kterminal.domain.instruments``) — easier to
  evolve than PostgreSQL ``ENUM`` types.
* **``jsonb`` holds snapshots** (the exact configuration a decision used),
  never data that must be queried relationally.
* **Stable constraint names** come from :data:`NAMING_CONVENTION`, so later
  migrations can address every constraint by name.
* **Integrity of the lab** is enforced by the database, not only by the code:
  a signal's or trade's strategy version must belong to *its* instance, and a
  risk decision's or trade's account-configuration version must belong to
  *its* account (composite foreign keys onto ``UNIQUE (owner_id, id)``).
* **High-volume tables are range-partitioned by month** (see
  :data:`PARTITION_KEYS` and :mod:`kterminal.db.partitions`); their primary keys
  include the partition key and no foreign key points *at* them.
"""

import re
import uuid
from datetime import UTC, date, datetime, time
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Final

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Dialect,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    Numeric,
    Table,
    Text,
    Time,
    TypeDecorator,
    UniqueConstraint,
    event,
    false,
    func,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.engine import Connection
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from kterminal.core.clock import ensure_utc
from kterminal.core.enums import (
    Direction,
    OrderSide,
    OrderType,
    SignalAction,
    SignalSource,
    StrategyKind,
    StrategyStatus,
    TradingMode,
)
from kterminal.core.ids import uuid7
from kterminal.domain.costs import Liquidity
from kterminal.domain.instruments import (
    AssetClass,
    ContractType,
    Platform,
    PnlModel,
    QuantityUnit,
    VenueKind,
)

# ── naming ───────────────────────────────────────────────────────────────────
NAMING_CONVENTION: Final[dict[str, str]] = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s",
    "pk": "pk_%(table_name)s",
}
"""Constraint/index names are derived from table and column names, never generated
randomly, so every environment has identical names and migrations can refer to them."""

# ── partitioning ─────────────────────────────────────────────────────────────
PARTITION_KEYS: Final[dict[str, str]] = {
    "webhook_events": "received_at",
    "equity_snapshots": "ts",
    "order_events": "ts",
    "candles": "ts",
    "audit_log": "ts",
}
"""Monthly range-partitioned tables and their partition-key column."""

AUDIT_GUARD_FUNCTION: Final = "kt_audit_log_append_only"
"""Trigger function that rejects UPDATE, DELETE and TRUNCATE of the audit log."""

# ── enumerations stored as text + CHECK ──────────────────────────────────────
# Values that have no Python enum in a layer this module may import are listed
# here; tests assert they match their owners (e.g. ``kterminal.brokers.base``).
ORDER_STATUSES: Final = (
    "PENDING_SUBMIT",
    "SUBMITTED",
    "ACCEPTED",
    "PARTIALLY_FILLED",
    "FILLED",
    "CANCELLED",
    "REJECTED",
    "EXPIRED",
    "FAILED",
)
TIME_IN_FORCE: Final = ("GTC", "DAY", "IOC", "FOK")
ORDER_PURPOSES: Final = ("ENTRY", "STOP_LOSS", "TAKE_PROFIT", "EXIT", "FLATTEN")
ACCOUNT_STATUSES: Final = ("ACTIVE", "LOCKED_FOR_DAY", "BREACHED", "PASSED", "PAUSED", "CLOSED")
LEDGER_KINDS: Final = (
    "DEPOSIT",
    "REALIZED_PNL",
    "COMMISSION",
    "SWAP",
    "FUNDING",
    "ADJUSTMENT",
    "RESET",
)
SIGNAL_STATUSES: Final = ("RECEIVED", "ROUTED", "IGNORED", "INVALID", "EXPIRED")
WEBHOOK_STATUSES: Final = ("ACCEPTED", "DUPLICATE", "REJECTED", "TEST")
RUN_KINDS: Final = ("BACKTEST", "LAB_SIMULATION", "FORWARD", "SIGNAL_REPLAY")
RUN_STATUSES: Final = ("QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED")
EXPERIMENT_STATUSES: Final = ("DRAFT", "RUNNING", "COMPLETED", "ARCHIVED")
TRADE_STATUSES: Final = ("OPEN", "CLOSED")
EXIT_REASONS: Final = (
    "TAKE_PROFIT",
    "STOP_LOSS",
    "BREAKEVEN_STOP",
    "TRAILING_STOP",
    "SIGNAL_EXIT",
    "REVERSAL",
    "MANUAL",
    "KILL_SWITCH",
    "RISK_FLATTEN",
    "SESSION_CLOSE",
    "BROKER_LIQUIDATION",
    "RUN_END",
)
TRADE_EVENT_KINDS: Final = ("STOP_MOVED", "BREAKEVEN", "TARGET_MOVED", "PARTIAL_CLOSE", "NOTE")
RISK_SEVERITIES: Final = ("INFO", "WARNING", "CRITICAL")
KILL_SWITCH_SCOPES: Final = ("GLOBAL", "ACCOUNT", "STRATEGY")
METRIC_SCOPES: Final = (
    "STRATEGY_INSTANCE",
    "STRATEGY_VERSION",
    "ACCOUNT",
    "RUN",
    "EXPERIMENT",
)
METRIC_DIMENSIONS: Final = (
    "ALL",
    "SYMBOL",
    "TIMEFRAME",
    "SESSION",
    "DAY",
    "WEEK",
    "MONTH",
    "DIRECTION",
)
NOTIFICATION_STATUSES: Final = ("PENDING", "SENT", "FAILED", "SUPPRESSED")
REPORT_STATUSES: Final = ("PENDING", "SENT", "FAILED", "SKIPPED")
ERROR_SEVERITIES: Final = ("WARNING", "ERROR", "CRITICAL")
USER_ROLES: Final = ("VIEWER", "OPERATOR", "ADMIN")
WEEKDAY_NAMES: Final = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")

_ENUM_VALUE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def enum_values(enum: type[StrEnum]) -> tuple[str, ...]:
    return tuple(member.value for member in enum)


def _quoted(values: tuple[str, ...]) -> str:
    for value in values:
        if not _ENUM_VALUE.fullmatch(value):  # DDL is built from these: keep them inert
            raise ValueError(f"enumeration value {value!r} is not an upper-case identifier")
    return ", ".join(f"'{value}'" for value in values)


def one_of(column: str, values: tuple[str, ...], name: str | None = None) -> CheckConstraint:
    """``CHECK (column IN (...))``, named ``ck_<table>_<name or column>``.

    NULL passes a CHECK, so nullability is decided by the column itself.
    """
    return CheckConstraint(f"{column} IN ({_quoted(values)})", name=name or column)


# ── column types ─────────────────────────────────────────────────────────────
class UTCDateTime(TypeDecorator[datetime]):
    """``timestamptz`` that refuses naive datetimes and always yields UTC."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        return None if value is None else ensure_utc(value)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        return None if value is None else value.astimezone(UTC)


type Json = dict[str, Any]

Price = Annotated[Decimal, mapped_column(Numeric(24, 10))]
"""Prices and quantities."""
Money = Annotated[Decimal, mapped_column(Numeric(20, 4))]
"""Money in the account (or listing quote) currency."""
Pct = Annotated[Decimal, mapped_column(Numeric(8, 4))]
"""Percentages and ratios."""
UuidPK = Annotated[uuid.UUID, mapped_column(primary_key=True, default=uuid7)]
CreatedAt = Annotated[datetime, mapped_column(server_default=func.now())]
UpdatedAt = Annotated[datetime, mapped_column(server_default=func.now(), onupdate=func.now())]

EMPTY_JSON = text("'{}'::jsonb")
EMPTY_JSON_ARRAY = text("'[]'::jsonb")
EMPTY_TEXT_ARRAY = text("'{}'::text[]")
EMPTY_TEXT = text("''")
ZERO = text("0")


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {  # noqa: RUF012 - SQLAlchemy's declarative configuration hook
        datetime: UTCDateTime(),
        Decimal: Numeric(24, 10),
        str: Text(),
        int: Integer(),
        bool: Boolean(),
        bytes: LargeBinary(),
        date: Date(),
        time: Time(),
        uuid.UUID: UUID(as_uuid=True),
        dict[str, Any]: JSONB(),
        list[str]: ARRAY(Text()),
    }


# ════════════════════════════════════════════════════════════════════════════
# Users (referenced by promotions and LIVE enablement)
# ════════════════════════════════════════════════════════════════════════════
class UserRow(Base):
    __tablename__ = "users"
    __table_args__ = (one_of("role", USER_ROLES),)

    id: Mapped[UuidPK]
    username: Mapped[str] = mapped_column(unique=True)
    password_hash: Mapped[str]  # argon2id
    totp_secret_enc: Mapped[bytes | None]  # encrypted with the app master key
    role: Mapped[str]
    disabled: Mapped[bool] = mapped_column(server_default=false())
    created_at: Mapped[CreatedAt]


# ════════════════════════════════════════════════════════════════════════════
# Reference data: the instrument catalog (docs/11)
# ════════════════════════════════════════════════════════════════════════════
class CatalogSnapshotRow(Base):
    """Every distinct catalog document ever applied, keyed by its fingerprint."""

    __tablename__ = "catalog_snapshots"

    id: Mapped[UuidPK]
    fingerprint: Mapped[str] = mapped_column(unique=True)
    document: Mapped[Json]
    applied_at: Mapped[CreatedAt]  # first time this fingerprint was applied
    applied_by: Mapped[str]
    last_applied_at: Mapped[CreatedAt]  # most recent application (re-applies update it)


class TradingDayRuleRow(Base):
    __tablename__ = "trading_day_rules"

    id: Mapped[str] = mapped_column(primary_key=True)
    timezone: Mapped[str]
    rollover: Mapped[time]  # local wall-clock time in ``timezone``
    description: Mapped[str] = mapped_column(server_default=EMPTY_TEXT)
    enabled: Mapped[bool] = mapped_column(server_default=true())
    updated_at: Mapped[UpdatedAt]


class TradingCalendarRow(Base):
    __tablename__ = "trading_calendars"

    id: Mapped[str] = mapped_column(primary_key=True)
    timezone: Mapped[str]
    definition: Mapped[Json]  # TradingCalendar.to_dict(): weekly intervals, holidays, …
    description: Mapped[str] = mapped_column(server_default=EMPTY_TEXT)
    enabled: Mapped[bool] = mapped_column(server_default=true())
    updated_at: Mapped[UpdatedAt]


class SessionWindowRow(Base):
    __tablename__ = "session_windows"
    __table_args__ = (
        CheckConstraint(
            f"cardinality(days) > 0 AND days <@ ARRAY[{_quoted(WEEKDAY_NAMES)}]::text[]",
            name="days",
        ),
        CheckConstraint("classification_rank >= 0", name="classification_rank"),
    )

    id: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str]
    timezone: Mapped[str]
    start_time: Mapped[time]  # local wall-clock times in ``timezone``
    end_time: Mapped[time]  # end <= start: the window crosses local midnight
    days: Mapped[list[str]]  # local weekdays on which the window starts
    description: Mapped[str] = mapped_column(server_default=EMPTY_TEXT)
    classification_rank: Mapped[int | None]  # position in session_classification, if any
    enabled: Mapped[bool] = mapped_column(server_default=true())
    updated_at: Mapped[UpdatedAt]


class CostProfileRow(Base):
    __tablename__ = "cost_profiles"

    id: Mapped[str] = mapped_column(primary_key=True)
    description: Mapped[str] = mapped_column(server_default=EMPTY_TEXT)
    definition: Mapped[Json]  # spread / commission / slippage / funding / swap models
    enabled: Mapped[bool] = mapped_column(server_default=true())
    updated_at: Mapped[UpdatedAt]


class VenueRow(Base):
    __tablename__ = "venues"
    __table_args__ = (
        one_of("kind", enum_values(VenueKind)),
        one_of("platform", enum_values(Platform)),
    )

    id: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str]
    kind: Mapped[str]
    platform: Mapped[str | None]
    timezone: Mapped[str] = mapped_column(server_default=text("'UTC'"))
    symbol_suffixes: Mapped[list[str]] = mapped_column(server_default=EMPTY_TEXT_ARRAY)
    description: Mapped[str] = mapped_column(server_default=EMPTY_TEXT)
    enabled: Mapped[bool] = mapped_column(server_default=true())
    updated_at: Mapped[UpdatedAt]


class InstrumentRow(Base):
    __tablename__ = "instruments"
    __table_args__ = (
        one_of("asset_class", enum_values(AssetClass)),
        CheckConstraint("tick_size > 0", name="tick_size_positive"),
    )

    symbol: Mapped[str] = mapped_column(primary_key=True)  # canonical, e.g. XAUUSD, MNQ
    name: Mapped[str]
    asset_class: Mapped[str]
    base: Mapped[str]
    quote_currency: Mapped[str]
    tick_size: Mapped[Price]  # canonical rounding of strategy prices
    trading_hours: Mapped[str] = mapped_column(ForeignKey("trading_calendars.id"))
    trading_day: Mapped[str] = mapped_column(ForeignKey("trading_day_rules.id"))
    underlying: Mapped[str] = mapped_column(server_default=EMPTY_TEXT)
    futures: Mapped[Json | None]  # contract cycle for exchange-traded futures
    description: Mapped[str] = mapped_column(server_default=EMPTY_TEXT)
    tags: Mapped[list[str]] = mapped_column(server_default=EMPTY_TEXT_ARRAY)
    enabled: Mapped[bool] = mapped_column(server_default=true())
    updated_at: Mapped[UpdatedAt]


class InstrumentListingRow(Base):
    """One instrument as specified by one venue: its symbol and contract specification."""

    __tablename__ = "instrument_listings"
    __table_args__ = (
        UniqueConstraint("venue", "venue_symbol"),
        one_of("contract_type", enum_values(ContractType)),
        one_of("quantity_unit", enum_values(QuantityUnit)),
        one_of("pnl_model", enum_values(PnlModel)),
        CheckConstraint(
            "tick_size > 0 AND contract_size > 0 AND min_qty > 0 AND qty_step > 0",
            name="spec_positive",
        ),
        CheckConstraint("max_qty IS NULL OR max_qty >= min_qty", name="max_qty"),
        CheckConstraint("min_notional IS NULL OR min_notional >= 0", name="min_notional"),
    )

    venue: Mapped[str] = mapped_column(ForeignKey("venues.id"), primary_key=True)
    instrument: Mapped[str] = mapped_column(ForeignKey("instruments.symbol"), primary_key=True)
    venue_symbol: Mapped[str]
    contract_type: Mapped[str]
    tick_size: Mapped[Price]
    contract_size: Mapped[Price]  # quote-ccy value of a 1.0 price move for 1.0 quantity
    quantity_unit: Mapped[str]
    min_qty: Mapped[Price]
    qty_step: Mapped[Price]
    max_qty: Mapped[Price | None]
    min_notional: Mapped[Money | None]
    quote_currency: Mapped[str]
    pnl_model: Mapped[str] = mapped_column(server_default=text("'LINEAR'"))
    trading_hours: Mapped[str | None] = mapped_column(ForeignKey("trading_calendars.id"))
    cost_profile: Mapped[str | None] = mapped_column(ForeignKey("cost_profiles.id"))
    symbol_format: Mapped[str | None]  # futures: dated-symbol template, e.g. {root}{code}{y1}
    tradable: Mapped[bool] = mapped_column(server_default=true())
    enabled: Mapped[bool] = mapped_column(server_default=true())
    aliases: Mapped[list[str]] = mapped_column(server_default=EMPTY_TEXT_ARRAY)
    verified_on: Mapped[date | None]
    source: Mapped[str] = mapped_column(server_default=EMPTY_TEXT)
    notes: Mapped[str] = mapped_column(server_default=EMPTY_TEXT)
    updated_at: Mapped[UpdatedAt]


class SymbolAliasRow(Base):
    """``(source, alias) → instrument``; source ``*`` is a global alias."""

    __tablename__ = "symbol_aliases"

    source: Mapped[str] = mapped_column(primary_key=True)
    alias: Mapped[str] = mapped_column(primary_key=True)
    instrument: Mapped[str] = mapped_column(ForeignKey("instruments.symbol"), index=True)


class VenueProfileRow(Base):
    __tablename__ = "venue_profiles"

    id: Mapped[str] = mapped_column(primary_key=True)
    description: Mapped[str] = mapped_column(server_default=EMPTY_TEXT)
    enabled: Mapped[bool] = mapped_column(server_default=true())
    updated_at: Mapped[UpdatedAt]


class VenueProfileEntryRow(Base):
    """Which listing an account on this profile executes (and optionally sources data) on."""

    __tablename__ = "venue_profile_entries"
    __table_args__ = (
        ForeignKeyConstraint(
            ["execution_venue", "instrument"],
            ["instrument_listings.venue", "instrument_listings.instrument"],
        ),
        ForeignKeyConstraint(
            ["data_venue", "instrument"],
            ["instrument_listings.venue", "instrument_listings.instrument"],
        ),
    )

    venue_profile_id: Mapped[str] = mapped_column(ForeignKey("venue_profiles.id"), primary_key=True)
    instrument: Mapped[str] = mapped_column(ForeignKey("instruments.symbol"), primary_key=True)
    execution_venue: Mapped[str]
    data_venue: Mapped[str | None]


# ════════════════════════════════════════════════════════════════════════════
# Strategies (docs/12): definitions → instances → versions
# ════════════════════════════════════════════════════════════════════════════
class StrategyDefinitionRow(Base):
    __tablename__ = "strategy_definitions"
    __table_args__ = (one_of("kind", enum_values(StrategyKind)),)

    id: Mapped[str] = mapped_column(primary_key=True)  # definition slug, e.g. ema_cross
    name: Mapped[str]
    kind: Mapped[str]
    latest_version: Mapped[str]  # semantic version declared by the plug-in / script
    module: Mapped[str | None]  # Python module of an INTERNAL plug-in
    description: Mapped[str] = mapped_column(server_default=EMPTY_TEXT)
    meta: Mapped[Json] = mapped_column(server_default=EMPTY_JSON)
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]


class StrategyInstanceRow(Base):
    """A configured, independently measured lab subject (``strategy_id``)."""

    __tablename__ = "strategy_instances"
    __table_args__ = (
        one_of("status", enum_values(StrategyStatus)),
        UniqueConstraint("id", "definition_id"),  # target of composite FKs
        # The current version must be one of *this* instance's versions.
        ForeignKeyConstraint(
            ["id", "current_version_id"],
            ["strategy_versions.instance_id", "strategy_versions.id"],
            use_alter=True,
        ),
    )

    id: Mapped[str] = mapped_column(primary_key=True)  # instance slug, immutable
    definition_id: Mapped[str] = mapped_column(ForeignKey("strategy_definitions.id"), index=True)
    name: Mapped[str]
    description: Mapped[str] = mapped_column(server_default=EMPTY_TEXT)
    status: Mapped[str] = mapped_column(server_default=text("'DRAFT'"))
    enabled: Mapped[bool] = mapped_column(server_default=true())
    current_version_id: Mapped[uuid.UUID | None]
    tags: Mapped[list[str]] = mapped_column(server_default=EMPTY_TEXT_ARRAY)
    webhook_secret_hashes: Mapped[list[Any]] = mapped_column(
        JSONB, server_default=EMPTY_JSON_ARRAY
    )  # [{hash, created_at, expires_at}] — rotation for EXTERNAL (TradingView) instances
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]


class StrategyVersionRow(Base):
    """Immutable snapshot of everything that determines an instance's signals."""

    __tablename__ = "strategy_versions"
    __table_args__ = (
        UniqueConstraint("instance_id", "config_hash"),
        UniqueConstraint("instance_id", "id"),  # target of composite FKs
        ForeignKeyConstraint(
            ["instance_id", "definition_id"],
            ["strategy_instances.id", "strategy_instances.definition_id"],
        ),
    )

    id: Mapped[UuidPK]
    instance_id: Mapped[str] = mapped_column(ForeignKey("strategy_instances.id"))
    definition_id: Mapped[str] = mapped_column(ForeignKey("strategy_definitions.id"))
    definition_version: Mapped[str]
    code_hash: Mapped[str | None]  # sha256 of the plug-in source / Pine script
    params: Mapped[Json] = mapped_column(server_default=EMPTY_JSON)
    params_hash: Mapped[str]
    config: Mapped[Json]  # the full version document (params, instruments, timeframes, …)
    config_hash: Mapped[str]  # stamped on every signal as ``strategy_version``
    framework_fingerprint: Mapped[str | None]
    kterminal_version: Mapped[str | None]
    created_at: Mapped[CreatedAt]


class StrategyPromotionRow(Base):
    """Audit of lifecycle changes (DRAFT → BACKTESTED → PAPER → …) with gate evidence."""

    __tablename__ = "strategy_promotions"
    __table_args__ = (
        one_of("from_status", enum_values(StrategyStatus)),
        one_of("to_status", enum_values(StrategyStatus)),
    )

    id: Mapped[UuidPK]
    instance_id: Mapped[str] = mapped_column(ForeignKey("strategy_instances.id"), index=True)
    strategy_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("strategy_versions.id")
    )
    from_status: Mapped[str]
    to_status: Mapped[str]
    evidence: Mapped[Json]  # metrics that satisfied the gate
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    note: Mapped[str] = mapped_column(server_default=EMPTY_TEXT)
    created_at: Mapped[CreatedAt]


class ExperimentRow(Base):
    __tablename__ = "experiments"
    __table_args__ = (one_of("status", EXPERIMENT_STATUSES),)

    id: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str]
    description: Mapped[str] = mapped_column(server_default=EMPTY_TEXT)
    status: Mapped[str] = mapped_column(server_default=text("'DRAFT'"))
    conditions: Mapped[Json] = mapped_column(server_default=EMPTY_JSON)  # template, data window
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]


class ExperimentMemberRow(Base):
    __tablename__ = "experiment_members"
    __table_args__ = (UniqueConstraint("experiment_id", "label"),)

    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id"), primary_key=True)
    instance_id: Mapped[str] = mapped_column(
        ForeignKey("strategy_instances.id"), primary_key=True, index=True
    )
    label: Mapped[str]  # 'A', 'A+EMA', 'A+B+LIQ'


# ════════════════════════════════════════════════════════════════════════════
# Runs: backtests, lab simulations, forward tests, signal replays
# ════════════════════════════════════════════════════════════════════════════
class RunRow(Base):
    __tablename__ = "runs"
    __table_args__ = (
        one_of("kind", RUN_KINDS),
        one_of("status", RUN_STATUSES),
        CheckConstraint(
            "finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at",
            name="finished_after_started",
        ),
    )

    id: Mapped[UuidPK]
    kind: Mapped[str]
    name: Mapped[str] = mapped_column(server_default=EMPTY_TEXT)
    experiment_id: Mapped[str | None] = mapped_column(ForeignKey("experiments.id"), index=True)
    config: Mapped[Json]  # instruments, timeframes, range, fill model, account template …
    data_fingerprint: Mapped[Json] = mapped_column(server_default=EMPTY_JSON)
    catalog_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("catalog_snapshots.id")
    )
    status: Mapped[str] = mapped_column(server_default=text("'QUEUED'"))
    created_at: Mapped[CreatedAt]
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    summary: Mapped[Json | None]  # headline metrics (trades stay the source of truth)
    error: Mapped[str | None]


# ════════════════════════════════════════════════════════════════════════════
# Accounts
# ════════════════════════════════════════════════════════════════════════════
class RiskProfileRow(Base):
    """Immutable versions of a rule set (e.g. a prop-firm challenge); edits add a row."""

    __tablename__ = "risk_profiles"
    __table_args__ = (
        UniqueConstraint("name", "version"),
        CheckConstraint("version >= 1", name="version_positive"),
    )

    id: Mapped[UuidPK]
    name: Mapped[str]
    version: Mapped[int]
    config: Mapped[Json]
    created_at: Mapped[CreatedAt]


class AccountRow(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        one_of("mode", enum_values(TradingMode)),
        one_of("status", ACCOUNT_STATUSES),
        CheckConstraint("starting_balance > 0", name="starting_balance_positive"),
        CheckConstraint("mode <> 'LIVE' OR live_enabled_by IS NOT NULL", name="live_enabled"),
        CheckConstraint(
            "live_enabled_by IS NULL OR live_enabled_at IS NOT NULL", name="live_enabled_at"
        ),
        UniqueConstraint("strategy_instance_id"),  # one dedicated lab account per instance
        # The current configuration must be one of *this* account's versions.
        ForeignKeyConstraint(
            ["id", "current_config_version_id"],
            ["account_config_versions.account_id", "account_config_versions.id"],
            use_alter=True,
        ),
    )

    id: Mapped[UuidPK]
    name: Mapped[str] = mapped_column(unique=True)  # 'Paper 50K · ema_cross_9_21_xau'
    mode: Mapped[str]
    broker: Mapped[str]  # registered adapter name: 'paper', 'mt5_bridge', 'tradelocker', …
    venue_profile_id: Mapped[str] = mapped_column(ForeignKey("venue_profiles.id"))
    risk_profile_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("risk_profiles.id"))
    currency: Mapped[str] = mapped_column(server_default=text("'USD'"))
    starting_balance: Mapped[Money]
    status: Mapped[str] = mapped_column(server_default=text("'ACTIVE'"))
    strategy_instance_id: Mapped[str | None] = mapped_column(ForeignKey("strategy_instances.id"))
    current_config_version_id: Mapped[uuid.UUID | None]
    high_water_mark: Mapped[Money]
    broker_account_ref: Mapped[str | None]  # external account id (masked in UI/logs)
    live_enabled_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    live_enabled_at: Mapped[datetime | None]
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]


class AccountConfigVersionRow(Base):
    """Immutable account settings (balance, risk %, limits, venue profile) a decision used."""

    __tablename__ = "account_config_versions"
    __table_args__ = (
        UniqueConstraint("account_id", "version"),
        UniqueConstraint("account_id", "config_hash"),
        UniqueConstraint("account_id", "id"),  # target of composite FKs
        CheckConstraint("version >= 1", name="version_positive"),
    )

    id: Mapped[UuidPK]
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    version: Mapped[int]
    config: Mapped[Json]
    config_hash: Mapped[str]
    created_at: Mapped[CreatedAt]


class AccountAllocationRow(Base):
    """Which strategy instances may trade on which account."""

    __tablename__ = "account_allocations"
    __table_args__ = (
        CheckConstraint(
            "risk_multiplier > 0 AND risk_multiplier <= 1", name="risk_multiplier_range"
        ),
    )

    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), primary_key=True)
    instance_id: Mapped[str] = mapped_column(
        ForeignKey("strategy_instances.id"), primary_key=True, index=True
    )
    enabled: Mapped[bool] = mapped_column(server_default=true())
    risk_multiplier: Mapped[Decimal] = mapped_column(Numeric(6, 4), server_default=text("1"))
    created_at: Mapped[CreatedAt]


class AccountLedgerRow(Base):
    """The ONLY way balances change. ``seq`` orders entries that share a timestamp."""

    __tablename__ = "account_ledger"
    __table_args__ = (
        one_of("kind", LEDGER_KINDS),
        Index(None, "account_id", "seq"),
        Index(None, "trade_id", postgresql_where=text("trade_id IS NOT NULL")),
        Index(None, "run_id", postgresql_where=text("run_id IS NOT NULL")),
    )

    id: Mapped[UuidPK]
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), unique=True)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    ts: Mapped[datetime]
    kind: Mapped[str]
    amount: Mapped[Money]  # signed change of the balance
    balance_after: Mapped[Money]
    trade_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("trades.id"))
    fill_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("fills.id"))
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runs.id"))
    note: Mapped[str] = mapped_column(server_default=EMPTY_TEXT)


class EquitySnapshotRow(Base):
    __tablename__ = "equity_snapshots"
    __table_args__ = (
        Index(None, "run_id", postgresql_where=text("run_id IS NOT NULL")),
        {"postgresql_partition_by": "RANGE (ts)"},
    )

    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), primary_key=True)
    ts: Mapped[datetime] = mapped_column(primary_key=True)
    balance: Mapped[Money]
    equity: Mapped[Money]
    open_pnl: Mapped[Money]
    open_risk: Mapped[Money]  # Σ distance-to-stop × size
    daily_pnl: Mapped[Money]  # vs. the trading-day start
    drawdown: Mapped[Money]  # vs. the high-water mark
    high_water_mark: Mapped[Money]
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runs.id"))


# ════════════════════════════════════════════════════════════════════════════
# Signals & webhooks
# ════════════════════════════════════════════════════════════════════════════
class WebhookEventRow(Base):
    """Every webhook request, accepted or not (secret removed before storage)."""

    __tablename__ = "webhook_events"
    __table_args__ = (
        one_of("status", WEBHOOK_STATUSES),
        CheckConstraint("processing_ms >= 0", name="processing_ms"),
        Index(None, "signal_id", postgresql_where=text("signal_id IS NOT NULL")),
        Index(None, "strategy_instance_id", "received_at"),
        {"postgresql_partition_by": "RANGE (received_at)"},
    )

    id: Mapped[UuidPK]
    received_at: Mapped[datetime] = mapped_column(primary_key=True)
    source_ip: Mapped[str] = mapped_column(INET)
    user_agent: Mapped[str | None]
    content_type: Mapped[str | None]
    body_redacted: Mapped[Json | None]
    body_sha256: Mapped[str]
    strategy_instance_id: Mapped[str | None]  # as claimed by the payload; unknown ids included
    status: Mapped[str]
    reject_code: Mapped[str | None]  # AUTH_FAILED, STALE_TIMESTAMP, UNKNOWN_SYMBOL, …
    reject_detail: Mapped[str | None]
    signal_id: Mapped[uuid.UUID | None]
    processing_ms: Mapped[int]
    correlation_id: Mapped[uuid.UUID]


class SignalRow(Base):
    __tablename__ = "signals"
    __table_args__ = (
        one_of("source", enum_values(SignalSource)),
        one_of("action", enum_values(SignalAction)),
        one_of("order_type", enum_values(OrderType)),
        one_of("status", SIGNAL_STATUSES),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        CheckConstraint("risk_pct > 0 AND risk_pct <= 100", name="risk_pct_range"),
        # Only a signal rejected as INVALID may lack a version, instrument, timeframe or action.
        CheckConstraint(
            "status = 'INVALID' OR (strategy_version_id IS NOT NULL AND instrument IS NOT NULL"
            " AND timeframe IS NOT NULL AND action IS NOT NULL)",
            name="valid_signal_complete",
        ),
        ForeignKeyConstraint(
            ["strategy_instance_id", "strategy_version_id"],
            ["strategy_versions.instance_id", "strategy_versions.id"],
        ),
        ForeignKeyConstraint(
            ["strategy_instance_id", "definition_id"],
            ["strategy_instances.id", "strategy_instances.definition_id"],
        ),
        Index(None, "strategy_instance_id", "signal_time"),
        Index(None, "strategy_version_id"),
        Index(None, "run_id", postgresql_where=text("run_id IS NOT NULL")),
    )

    id: Mapped[UuidPK]
    strategy_instance_id: Mapped[str] = mapped_column(ForeignKey("strategy_instances.id"))
    strategy_version_id: Mapped[uuid.UUID | None]
    definition_id: Mapped[str] = mapped_column(ForeignKey("strategy_definitions.id"))
    source: Mapped[str]
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runs.id"))
    instrument: Mapped[str | None] = mapped_column(ForeignKey("instruments.symbol"))
    raw_symbol: Mapped[str | None]  # as received (e.g. BINANCE:NEARUSDT.P)
    timeframe: Mapped[str | None]  # canonical: 1m, 5m, 15m, 1h, 1D
    bar_time: Mapped[datetime | None]  # open time of the evaluated bar
    signal_time: Mapped[datetime]  # decision time: close of the evaluated bar
    received_at: Mapped[datetime]  # when the terminal got it
    action: Mapped[str | None]
    order_type: Mapped[str] = mapped_column(server_default=text("'MARKET'"))
    entry: Mapped[Price | None]
    stop_loss: Mapped[Price | None]
    take_profit: Mapped[Price | None]
    risk_pct: Mapped[Pct | None]  # requested risk; capped by the account configuration
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    meta: Mapped[Json] = mapped_column("metadata", server_default=EMPTY_JSON)
    market_snapshot: Mapped[Json] = mapped_column(server_default=EMPTY_JSON)
    raw_payload: Mapped[Json] = mapped_column(server_default=EMPTY_JSON)  # INVALID: as received
    idempotency_key: Mapped[str] = mapped_column(unique=True)
    status: Mapped[str] = mapped_column(server_default=text("'RECEIVED'"))
    reject_code: Mapped[str | None]
    reject_detail: Mapped[str | None]
    catalog_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("catalog_snapshots.id")
    )
    correlation_id: Mapped[uuid.UUID]


# ════════════════════════════════════════════════════════════════════════════
# Risk
# ════════════════════════════════════════════════════════════════════════════
class RiskDecisionRow(Base):
    __tablename__ = "risk_decisions"
    __table_args__ = (
        UniqueConstraint("signal_id", "account_id"),
        CheckConstraint("approved OR primary_reason IS NOT NULL", name="rejection_has_reason"),
        ForeignKeyConstraint(
            ["account_id", "account_config_version_id"],
            ["account_config_versions.account_id", "account_config_versions.id"],
        ),
        Index(None, "account_id", "decided_at"),
        Index(None, "run_id", postgresql_where=text("run_id IS NOT NULL")),
    )

    id: Mapped[UuidPK]
    signal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("signals.id"))
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    account_config_version_id: Mapped[uuid.UUID]
    decided_at: Mapped[datetime]
    approved: Mapped[bool]
    primary_reason: Mapped[str | None]  # first failing rule code; NULL when approved
    rule_results: Mapped[list[Any]] = mapped_column(JSONB)  # every rule: passed, code, values
    account_state: Mapped[Json]  # balance, equity, daily P&L, DD, open positions
    risk_profile_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("risk_profiles.id"))
    quote: Mapped[Json] = mapped_column(server_default=EMPTY_JSON)  # bid/ask/ts used for sizing
    requested_qty: Mapped[Price | None]
    approved_qty: Mapped[Price | None]
    risk_amount: Mapped[Money | None]
    risk_pct: Mapped[Pct | None]
    expires_at: Mapped[datetime | None]
    catalog_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("catalog_snapshots.id")
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runs.id"))
    correlation_id: Mapped[uuid.UUID]


class RiskEventRow(Base):
    """Warnings, breaches and automatic actions (DAILY_LOSS_WARNING, AUTO_FLATTEN, …)."""

    __tablename__ = "risk_events"
    __table_args__ = (
        one_of("severity", RISK_SEVERITIES),
        Index(None, "account_id", "ts"),
    )

    id: Mapped[UuidPK]
    ts: Mapped[datetime]
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.id"))
    strategy_instance_id: Mapped[str | None] = mapped_column(ForeignKey("strategy_instances.id"))
    kind: Mapped[str]
    severity: Mapped[str]
    threshold: Mapped[Pct | None]  # e.g. 0.75 = 75 % of the limit consumed
    details: Mapped[Json] = mapped_column(server_default=EMPTY_JSON)
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runs.id"))
    correlation_id: Mapped[uuid.UUID | None]


class KillSwitchRow(Base):
    """Persisted kill switches; they survive restarts."""

    __tablename__ = "kill_switches"
    __table_args__ = (one_of("scope", KILL_SWITCH_SCOPES),)

    scope: Mapped[str] = mapped_column(primary_key=True)
    scope_id: Mapped[str] = mapped_column(primary_key=True, server_default=text("'*'"))
    active: Mapped[bool]
    close_positions: Mapped[bool] = mapped_column(server_default=false())
    cancel_orders: Mapped[bool] = mapped_column(server_default=true())
    reason: Mapped[str]
    changed_by: Mapped[str]  # user id, 'system:<rule>' or 'telegram:<user>'
    changed_at: Mapped[datetime]


# ════════════════════════════════════════════════════════════════════════════
# Trades, orders & fills
# ════════════════════════════════════════════════════════════════════════════
class TradeRow(Base):
    """One round trip (entry → final exit), the unit every metric is computed from."""

    __tablename__ = "trades"
    __table_args__ = (
        one_of("mode", enum_values(TradingMode)),
        one_of("direction", enum_values(Direction)),
        one_of("exit_reason", EXIT_REASONS),
        one_of("status", TRADE_STATUSES),
        CheckConstraint("qty > 0", name="qty_positive"),
        CheckConstraint("exit_time IS NULL OR exit_time >= entry_time", name="exit_after_entry"),
        CheckConstraint(
            "status = 'OPEN' OR (exit_price IS NOT NULL AND exit_time IS NOT NULL"
            " AND exit_reason IS NOT NULL AND net_pnl IS NOT NULL)",
            name="closed_trade_complete",
        ),
        ForeignKeyConstraint(
            ["strategy_instance_id", "strategy_version_id"],
            ["strategy_versions.instance_id", "strategy_versions.id"],
        ),
        ForeignKeyConstraint(
            ["account_id", "account_config_version_id"],
            ["account_config_versions.account_id", "account_config_versions.id"],
        ),
        ForeignKeyConstraint(
            ["venue", "instrument"],
            ["instrument_listings.venue", "instrument_listings.instrument"],
        ),
        Index(None, "strategy_instance_id", "exit_time"),
        Index(None, "strategy_version_id"),
        Index(None, "account_id", "status"),
        Index(None, "run_id", postgresql_where=text("run_id IS NOT NULL")),
    )

    id: Mapped[UuidPK]
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    account_config_version_id: Mapped[uuid.UUID]
    strategy_instance_id: Mapped[str] = mapped_column(ForeignKey("strategy_instances.id"))
    strategy_version_id: Mapped[uuid.UUID]
    entry_signal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("signals.id"))
    exit_signal_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("signals.id"))
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runs.id"))
    catalog_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("catalog_snapshots.id")
    )
    mode: Mapped[str]
    instrument: Mapped[str]
    venue: Mapped[str]
    venue_symbol: Mapped[str]
    timeframe: Mapped[str]
    direction: Mapped[str]
    qty: Mapped[Price]
    entry_requested: Mapped[Price]
    entry_price: Mapped[Price]  # average fill
    entry_time: Mapped[datetime]
    initial_stop: Mapped[Price]
    initial_target: Mapped[Price | None]
    current_stop: Mapped[Price | None]
    current_target: Mapped[Price | None]
    exit_price: Mapped[Price | None]
    exit_time: Mapped[datetime | None]
    exit_reason: Mapped[str | None]
    initial_risk: Mapped[Money]  # |entry_price − initial_stop| × qty × point value
    gross_pnl: Mapped[Money | None]
    commission: Mapped[Money] = mapped_column(server_default=ZERO)
    swap: Mapped[Money] = mapped_column(server_default=ZERO)
    funding: Mapped[Money] = mapped_column(server_default=ZERO)
    spread_cost: Mapped[Money] = mapped_column(server_default=ZERO)
    net_pnl: Mapped[Money | None]
    r_multiple: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))  # net_pnl / initial_risk
    entry_slippage: Mapped[Price | None]  # adverse-positive, price units
    exit_slippage: Mapped[Price | None]
    mae: Mapped[Price | None]  # max adverse excursion (price)
    mfe: Mapped[Price | None]  # max favourable excursion (price)
    session: Mapped[str | None]  # session classification at entry
    status: Mapped[str]
    correlation_id: Mapped[uuid.UUID]
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]


class OrderRow(Base):
    __tablename__ = "orders"
    __table_args__ = (
        one_of("purpose", ORDER_PURPOSES),
        one_of("mode", enum_values(TradingMode)),
        one_of("side", enum_values(OrderSide)),
        one_of("order_type", enum_values(OrderType)),
        one_of("time_in_force", TIME_IN_FORCE),
        one_of("status", ORDER_STATUSES),
        CheckConstraint("qty > 0", name="qty_positive"),
        CheckConstraint("filled_qty >= 0 AND filled_qty <= qty", name="filled_qty_range"),
        # Any risk-increasing order must have passed the risk engine.
        CheckConstraint(
            "purpose <> 'ENTRY' OR risk_decision_id IS NOT NULL", name="entry_has_risk_decision"
        ),
        ForeignKeyConstraint(
            ["venue", "instrument"],
            ["instrument_listings.venue", "instrument_listings.instrument"],
        ),
        Index(None, "account_id", "status"),
        Index(None, "trade_id", postgresql_where=text("trade_id IS NOT NULL")),
        Index(None, "signal_id", postgresql_where=text("signal_id IS NOT NULL")),
        Index(None, "run_id", postgresql_where=text("run_id IS NOT NULL")),
    )

    id: Mapped[UuidPK]
    client_order_id: Mapped[str] = mapped_column(unique=True)  # idempotent submission
    broker_order_id: Mapped[str | None]
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    strategy_instance_id: Mapped[str | None] = mapped_column(ForeignKey("strategy_instances.id"))
    trade_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("trades.id"))
    signal_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("signals.id"))
    risk_decision_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("risk_decisions.id"))
    parent_order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("orders.id"))
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runs.id"))
    purpose: Mapped[str]
    mode: Mapped[str]
    venue: Mapped[str]
    instrument: Mapped[str]
    venue_symbol: Mapped[str]
    side: Mapped[str]
    order_type: Mapped[str]
    qty: Mapped[Price]
    requested_price: Mapped[Price | None]  # reference / limit / stop price
    time_in_force: Mapped[str] = mapped_column(server_default=text("'GTC'"))
    status: Mapped[str]
    filled_qty: Mapped[Price] = mapped_column(server_default=ZERO)
    avg_fill_price: Mapped[Price | None]
    slippage: Mapped[Price | None]
    commission: Mapped[Money] = mapped_column(server_default=ZERO)
    reject_reason: Mapped[str | None]
    created_at: Mapped[datetime]
    submitted_at: Mapped[datetime | None]
    acknowledged_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]
    correlation_id: Mapped[uuid.UUID]


class OrderEventRow(Base):
    """Every order state transition with the raw broker payload (credentials never present)."""

    __tablename__ = "order_events"
    __table_args__ = (
        Index(None, "order_id", "ts"),
        {"postgresql_partition_by": "RANGE (ts)"},
    )

    id: Mapped[UuidPK]
    ts: Mapped[datetime] = mapped_column(primary_key=True)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"))
    from_status: Mapped[str | None]
    to_status: Mapped[str]
    broker_payload: Mapped[Json | None]


class FillRow(Base):
    __tablename__ = "fills"
    __table_args__ = (
        one_of("liquidity", enum_values(Liquidity)),
        UniqueConstraint("order_id", "broker_fill_id"),
        CheckConstraint("qty > 0 AND price > 0", name="qty_price_positive"),
        Index(None, "account_id", "ts"),
        Index(None, "run_id", postgresql_where=text("run_id IS NOT NULL")),
    )

    id: Mapped[UuidPK]
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"))
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    broker_fill_id: Mapped[str | None]
    ts: Mapped[datetime]
    qty: Mapped[Price]
    price: Mapped[Price]
    commission: Mapped[Money] = mapped_column(server_default=ZERO)
    liquidity: Mapped[str | None]
    spread_cost: Mapped[Money] = mapped_column(server_default=ZERO)
    slippage: Mapped[Price] = mapped_column(server_default=ZERO)  # adverse-positive, price units
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runs.id"))


class TradeEventRow(Base):
    """Stop moves, break-even, target changes, partial closes."""

    __tablename__ = "trade_events"
    __table_args__ = (
        one_of("kind", TRADE_EVENT_KINDS),
        Index(None, "trade_id", "ts"),
    )

    id: Mapped[UuidPK]
    trade_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("trades.id"))
    ts: Mapped[datetime]
    kind: Mapped[str]
    old_value: Mapped[Price | None]
    new_value: Mapped[Price | None]
    signal_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("signals.id"))
    details: Mapped[Json] = mapped_column(server_default=EMPTY_JSON)


# ════════════════════════════════════════════════════════════════════════════
# Analytics & market data
# ════════════════════════════════════════════════════════════════════════════
class PerformanceMetricRow(Base):
    """A cache of metrics recomputed from recorded trades — never the source of truth."""

    __tablename__ = "performance_metrics"
    __table_args__ = (
        one_of("scope", METRIC_SCOPES),
        one_of("mode", enum_values(TradingMode)),
        one_of("dimension", METRIC_DIMENSIONS),
        UniqueConstraint("scope", "scope_id", "mode", "dimension", "bucket"),
        CheckConstraint("trade_count >= 0", name="trade_count"),
    )

    id: Mapped[UuidPK]
    scope: Mapped[str]
    scope_id: Mapped[str]
    mode: Mapped[str]
    dimension: Mapped[str]
    bucket: Mapped[str]  # 'XAUUSD', '2026-W41', 'LONG', …
    period_start: Mapped[datetime | None]
    period_end: Mapped[datetime | None]
    metrics: Mapped[Json]  # appendix A definitions
    trade_count: Mapped[int]
    computed_at: Mapped[datetime]


class CandleRow(Base):
    """Bars that drove paper/live decisions (bar open time ``ts``)."""

    __tablename__ = "candles"
    __table_args__ = (
        CheckConstraint(
            "low <= open AND low <= close AND high >= open AND high >= close AND low <= high",
            name="ohlc_consistent",
        ),
        CheckConstraint("volume IS NULL OR volume >= 0", name="volume"),
        {"postgresql_partition_by": "RANGE (ts)"},
    )

    instrument: Mapped[str] = mapped_column(primary_key=True)  # canonical symbol
    timeframe: Mapped[str] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(primary_key=True)  # data venue / provider
    ts: Mapped[datetime] = mapped_column(primary_key=True)
    open: Mapped[Price]
    high: Mapped[Price]
    low: Mapped[Price]
    close: Mapped[Price]
    volume: Mapped[Price | None]


# ════════════════════════════════════════════════════════════════════════════
# Notifications, system & audit
# ════════════════════════════════════════════════════════════════════════════
class OutboxRow(Base):
    """Transactional outbox for cross-process events."""

    __tablename__ = "outbox"
    __table_args__ = (
        CheckConstraint("attempts >= 0", name="attempts"),
        Index(None, "topic", "available_at", postgresql_where=text("processed_at IS NULL")),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    topic: Mapped[str]  # 'signal.received', 'trade.opened', …
    payload: Mapped[Json]
    created_at: Mapped[CreatedAt]
    available_at: Mapped[CreatedAt]
    attempts: Mapped[int] = mapped_column(server_default=ZERO)
    processed_at: Mapped[datetime | None]
    last_error: Mapped[str | None]
    correlation_id: Mapped[uuid.UUID | None]


class NotificationRow(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        one_of("status", NOTIFICATION_STATUSES),
        UniqueConstraint("channel", "dedupe_key"),
    )

    id: Mapped[UuidPK]
    channel: Mapped[str] = mapped_column(server_default=text("'telegram'"))
    destination: Mapped[str]  # logical route ('trades', 'alerts', 'reports'), not a raw chat id
    event_type: Mapped[str]
    dedupe_key: Mapped[str | None]
    payload: Mapped[Json]
    rendered_text: Mapped[str]
    status: Mapped[str]
    attempts: Mapped[int] = mapped_column(server_default=ZERO)
    provider_message_id: Mapped[str | None]
    error: Mapped[str | None]
    created_at: Mapped[datetime]
    sent_at: Mapped[datetime | None]
    correlation_id: Mapped[uuid.UUID | None]


class ReportRunRow(Base):
    """Scheduled reports are sent exactly once per period."""

    __tablename__ = "report_runs"
    __table_args__ = (one_of("status", REPORT_STATUSES),)

    report: Mapped[str] = mapped_column(primary_key=True)  # 'DAILY', 'WEEKLY'
    period_key: Mapped[str] = mapped_column(primary_key=True)  # '2026-10-05', '2026-W41'
    status: Mapped[str]
    created_at: Mapped[datetime]


class SystemErrorRow(Base):
    __tablename__ = "system_errors"
    __table_args__ = (
        one_of("severity", ERROR_SEVERITIES),
        Index(None, "ts"),
        Index(
            None,
            "strategy_instance_id",
            "ts",
            postgresql_where=text("strategy_instance_id IS NOT NULL"),
        ),
    )

    id: Mapped[UuidPK]
    ts: Mapped[datetime]
    component: Mapped[str]  # 'engine.execution', 'strategy.host', 'broker.mt5_bridge', …
    severity: Mapped[str]
    message: Mapped[str]
    exception: Mapped[str | None]  # type + traceback (redacted)
    context: Mapped[Json] = mapped_column(server_default=EMPTY_JSON)
    strategy_instance_id: Mapped[str | None] = mapped_column(
        ForeignKey("strategy_instances.id")
    )  # strategy faults are attributed to their instance
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runs.id"))
    correlation_id: Mapped[uuid.UUID | None]


class SystemStateRow(Base):
    """Heartbeats, leader identity, feature flags."""

    __tablename__ = "system_state"

    key: Mapped[str] = mapped_column(primary_key=True)
    value: Mapped[Json]
    updated_at: Mapped[datetime]


class AuditLogRow(Base):
    """Append-only, hash-chained log; see :mod:`kterminal.db.audit`."""

    __tablename__ = "audit_log"
    __table_args__ = (
        Index(None, "entity_type", "entity_id"),
        {"postgresql_partition_by": "RANGE (ts)"},
    )

    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(primary_key=True)
    actor: Mapped[str]  # 'user:<id>', 'system:engine', 'strategy:<id>', 'webhook'
    action: Mapped[str]  # 'risk.decision', 'order.submit', 'killswitch.activate', …
    entity_type: Mapped[str]
    entity_id: Mapped[str]
    data: Mapped[Json]
    correlation_id: Mapped[uuid.UUID | None]
    prev_hash: Mapped[str]
    hash: Mapped[str]  # sha256(prev_hash || canonical_json(row))


# ── DDL that SQLAlchemy cannot express declaratively ─────────────────────────
AUDIT_GUARD_FUNCTION_DDL: Final = f"""
CREATE OR REPLACE FUNCTION {AUDIT_GUARD_FUNCTION}() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only: % is not allowed', TG_OP
        USING HINT = 'The audit trail can only be appended to (kterminal.db.audit.append).';
END
$$
"""


def audit_guard_triggers_ddl(table: str) -> list[str]:
    """Row-level UPDATE/DELETE guard (cloned to every partition) and a TRUNCATE guard.

    PostgreSQL fires a statement-level TRUNCATE trigger only on the table that is
    named, so every audit-log *partition* gets its own TRUNCATE guard as well.
    """
    statements = [
        f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} "
        f"FOR EACH STATEMENT EXECUTE FUNCTION {AUDIT_GUARD_FUNCTION}()"
    ]
    if table == AuditLogRow.__tablename__:
        statements.insert(
            0,
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION {AUDIT_GUARD_FUNCTION}()",
        )
    return statements


def default_partition_name(table: str) -> str:
    return f"{table}_default"


def _after_create_partitioned(target: Table, connection: Connection, **_: Any) -> None:
    """Support ``metadata.create_all`` (tests, tools): add the DEFAULT partition and guards.

    Production schemas are created by the Alembic migration, which does the same.
    """
    name = target.name
    connection.execute(
        text(f"CREATE TABLE {default_partition_name(name)} PARTITION OF {name} DEFAULT")
    )
    if name == AuditLogRow.__tablename__:
        connection.execute(text(AUDIT_GUARD_FUNCTION_DDL))
        for statement in audit_guard_triggers_ddl(name):
            connection.execute(text(statement))
        for statement in audit_guard_triggers_ddl(default_partition_name(name)):
            connection.execute(text(statement))


def _after_drop_audit_log(target: Table, connection: Connection, **_: Any) -> None:
    connection.execute(text(f"DROP FUNCTION IF EXISTS {AUDIT_GUARD_FUNCTION}()"))


for _table_name in PARTITION_KEYS:
    event.listen(Base.metadata.tables[_table_name], "after_create", _after_create_partitioned)
event.listen(Base.metadata.tables["audit_log"], "after_drop", _after_drop_audit_log)


def table_of(model: type[Base]) -> Table:
    """The Core :class:`~sqlalchemy.Table` of a mapped class, typed as such."""
    table = model.__table__
    if not isinstance(table, Table):  # pragma: no cover - every model here maps one table
        raise TypeError(f"{model.__name__} is not mapped to a single table")
    return table


TABLES: Final[dict[str, Table]] = dict(Base.metadata.tables)
"""Every table of the schema by name (Core access for bulk inserts and reports)."""
