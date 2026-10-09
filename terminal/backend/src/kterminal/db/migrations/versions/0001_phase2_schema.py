"""Phase 2 schema: catalog, strategy lab, accounts, signals, risk, execution, audit.

Revision ID: 0001
Revises:
Create Date: 2026-10-06

Generated with Alembic autogenerate from ``kterminal.db.models`` and then
hand-reviewed and edited:

* tables are grouped by area and ordered by dependency;
* the two reference cycles (``strategy_instances.current_version_id`` and
  ``accounts.current_config_version_id``) are added with
  ``op.create_foreign_key`` once both tables exist;
* every range-partitioned table gets a ``DEFAULT`` partition, so no row is
  ever rejected for want of a monthly partition (those are created at run time
  by ``kterminal.db.partitions.ensure_monthly_partitions``);
* the audit log gets its append-only guard: a trigger function that rejects
  ``UPDATE``/``DELETE`` (row trigger, cloned to every partition) and
  ``TRUNCATE`` (statement trigger on the table and on each partition).

The application's own timestamp type (``UTCDateTime``) is rendered as plain
``sa.DateTime(timezone=True)`` so this file never imports application code:
a migration is frozen history and must keep working when the models change.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PARTITIONED_TABLES = ("webhook_events", "equity_snapshots", "order_events", "candles", "audit_log")
AUDIT_GUARD_FUNCTION = "kt_audit_log_append_only"


def upgrade() -> None:
    # ── Users (referenced by promotions and LIVE enablement) ────────────────────
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("totp_secret_enc", sa.LargeBinary(), nullable=True),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("disabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("role IN ('VIEWER', 'OPERATOR', 'ADMIN')", name=op.f("ck_users_role")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("username", name=op.f("uq_users_username")),
    )

    # ── Reference data: the instrument catalog (docs/11) ────────────────────────
    op.create_table(
        "catalog_snapshots",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("fingerprint", sa.Text(), nullable=False),
        sa.Column("document", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "applied_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("applied_by", sa.Text(), nullable=False),
        sa.Column(
            "last_applied_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_catalog_snapshots")),
        sa.UniqueConstraint("fingerprint", name=op.f("uq_catalog_snapshots_fingerprint")),
    )

    op.create_table(
        "trading_day_rules",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("timezone", sa.Text(), nullable=False),
        sa.Column("rollover", sa.Time(), nullable=False),
        sa.Column("description", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trading_day_rules")),
    )

    op.create_table(
        "trading_calendars",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("timezone", sa.Text(), nullable=False),
        sa.Column("definition", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("description", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trading_calendars")),
    )

    op.create_table(
        "session_windows",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("timezone", sa.Text(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("days", sa.ARRAY(sa.Text()), nullable=False),
        sa.Column("description", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("classification_rank", sa.Integer(), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "cardinality(days) > 0 AND days <@ ARRAY['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', "
            "'SUN']::text[]",
            name=op.f("ck_session_windows_days"),
        ),
        sa.CheckConstraint(
            "classification_rank >= 0", name=op.f("ck_session_windows_classification_rank")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_session_windows")),
    )

    op.create_table(
        "cost_profiles",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("definition", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cost_profiles")),
    )

    op.create_table(
        "venues",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("platform", sa.Text(), nullable=True),
        sa.Column("timezone", sa.Text(), server_default=sa.text("'UTC'"), nullable=False),
        sa.Column(
            "symbol_suffixes",
            sa.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('EXCHANGE', 'BROKER', 'PROP_FIRM', 'DATA_FEED', 'SIGNAL_SOURCE', "
            "'SIMULATOR')",
            name=op.f("ck_venues_kind"),
        ),
        sa.CheckConstraint(
            "platform IN ('MT5', 'MT4', 'TRADELOCKER', 'CTRADER', 'DXTRADE', 'MATCH_TRADER', "
            "'TRADOVATE', 'RITHMIC', 'PROJECTX', 'NINJATRADER', 'INTERACTIVE_BROKERS', "
            "'OANDA_V20', 'CME_GLOBEX', 'BINANCE', 'BYBIT', 'OKX', 'HYPERLIQUID', 'COINBASE', "
            "'TRADINGVIEW', 'INTERNAL')",
            name=op.f("ck_venues_platform"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_venues")),
    )

    op.create_table(
        "instruments",
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("asset_class", sa.Text(), nullable=False),
        sa.Column("base", sa.Text(), nullable=False),
        sa.Column("quote_currency", sa.Text(), nullable=False),
        sa.Column("tick_size", sa.Numeric(precision=24, scale=10), nullable=False),
        sa.Column("trading_hours", sa.Text(), nullable=False),
        sa.Column("trading_day", sa.Text(), nullable=False),
        sa.Column("underlying", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("futures", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("description", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column(
            "tags", sa.ARRAY(sa.Text()), server_default=sa.text("'{}'::text[]"), nullable=False
        ),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "asset_class IN ('FX', 'METAL', 'INDEX', 'EQUITY', 'COMMODITY', 'CRYPTO', 'RATES')",
            name=op.f("ck_instruments_asset_class"),
        ),
        sa.CheckConstraint("tick_size > 0", name=op.f("ck_instruments_tick_size_positive")),
        sa.ForeignKeyConstraint(
            ["trading_day"], ["trading_day_rules.id"], name=op.f("fk_instruments_trading_day")
        ),
        sa.ForeignKeyConstraint(
            ["trading_hours"], ["trading_calendars.id"], name=op.f("fk_instruments_trading_hours")
        ),
        sa.PrimaryKeyConstraint("symbol", name=op.f("pk_instruments")),
    )

    op.create_table(
        "instrument_listings",
        sa.Column("venue", sa.Text(), nullable=False),
        sa.Column("instrument", sa.Text(), nullable=False),
        sa.Column("venue_symbol", sa.Text(), nullable=False),
        sa.Column("contract_type", sa.Text(), nullable=False),
        sa.Column("tick_size", sa.Numeric(precision=24, scale=10), nullable=False),
        sa.Column("contract_size", sa.Numeric(precision=24, scale=10), nullable=False),
        sa.Column("quantity_unit", sa.Text(), nullable=False),
        sa.Column("min_qty", sa.Numeric(precision=24, scale=10), nullable=False),
        sa.Column("qty_step", sa.Numeric(precision=24, scale=10), nullable=False),
        sa.Column("max_qty", sa.Numeric(precision=24, scale=10), nullable=True),
        sa.Column("min_notional", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("quote_currency", sa.Text(), nullable=False),
        sa.Column("pnl_model", sa.Text(), server_default=sa.text("'LINEAR'"), nullable=False),
        sa.Column("trading_hours", sa.Text(), nullable=True),
        sa.Column("cost_profile", sa.Text(), nullable=True),
        sa.Column("symbol_format", sa.Text(), nullable=True),
        sa.Column("tradable", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "aliases", sa.ARRAY(sa.Text()), server_default=sa.text("'{}'::text[]"), nullable=False
        ),
        sa.Column("verified_on", sa.Date(), nullable=True),
        sa.Column("source", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("notes", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "contract_type IN ('SPOT', 'CFD', 'FUTURE', 'PERPETUAL', 'INDEX_DATA')",
            name=op.f("ck_instrument_listings_contract_type"),
        ),
        sa.CheckConstraint(
            "pnl_model IN ('LINEAR', 'INVERSE')", name=op.f("ck_instrument_listings_pnl_model")
        ),
        sa.CheckConstraint(
            "quantity_unit IN ('LOTS', 'CONTRACTS', 'BASE_UNITS')",
            name=op.f("ck_instrument_listings_quantity_unit"),
        ),
        sa.CheckConstraint(
            "max_qty IS NULL OR max_qty >= min_qty", name=op.f("ck_instrument_listings_max_qty")
        ),
        sa.CheckConstraint(
            "min_notional IS NULL OR min_notional >= 0",
            name=op.f("ck_instrument_listings_min_notional"),
        ),
        sa.CheckConstraint(
            "tick_size > 0 AND contract_size > 0 AND min_qty > 0 AND qty_step > 0",
            name=op.f("ck_instrument_listings_spec_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["cost_profile"], ["cost_profiles.id"], name=op.f("fk_instrument_listings_cost_profile")
        ),
        sa.ForeignKeyConstraint(
            ["instrument"], ["instruments.symbol"], name=op.f("fk_instrument_listings_instrument")
        ),
        sa.ForeignKeyConstraint(
            ["trading_hours"],
            ["trading_calendars.id"],
            name=op.f("fk_instrument_listings_trading_hours"),
        ),
        sa.ForeignKeyConstraint(
            ["venue"], ["venues.id"], name=op.f("fk_instrument_listings_venue")
        ),
        sa.PrimaryKeyConstraint("venue", "instrument", name=op.f("pk_instrument_listings")),
        sa.UniqueConstraint(
            "venue", "venue_symbol", name=op.f("uq_instrument_listings_venue_venue_symbol")
        ),
    )

    op.create_table(
        "symbol_aliases",
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("alias", sa.Text(), nullable=False),
        sa.Column("instrument", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["instrument"], ["instruments.symbol"], name=op.f("fk_symbol_aliases_instrument")
        ),
        sa.PrimaryKeyConstraint("source", "alias", name=op.f("pk_symbol_aliases")),
    )
    op.create_index(
        op.f("ix_symbol_aliases_instrument"), "symbol_aliases", ["instrument"], unique=False
    )

    op.create_table(
        "venue_profiles",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_venue_profiles")),
    )

    op.create_table(
        "venue_profile_entries",
        sa.Column("venue_profile_id", sa.Text(), nullable=False),
        sa.Column("instrument", sa.Text(), nullable=False),
        sa.Column("execution_venue", sa.Text(), nullable=False),
        sa.Column("data_venue", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["data_venue", "instrument"],
            ["instrument_listings.venue", "instrument_listings.instrument"],
            name=op.f("fk_venue_profile_entries_data_venue_instrument"),
        ),
        sa.ForeignKeyConstraint(
            ["execution_venue", "instrument"],
            ["instrument_listings.venue", "instrument_listings.instrument"],
            name=op.f("fk_venue_profile_entries_execution_venue_instrument"),
        ),
        sa.ForeignKeyConstraint(
            ["instrument"], ["instruments.symbol"], name=op.f("fk_venue_profile_entries_instrument")
        ),
        sa.ForeignKeyConstraint(
            ["venue_profile_id"],
            ["venue_profiles.id"],
            name=op.f("fk_venue_profile_entries_venue_profile_id"),
        ),
        sa.PrimaryKeyConstraint(
            "venue_profile_id", "instrument", name=op.f("pk_venue_profile_entries")
        ),
    )

    # ── Strategies (docs/12): definitions -> instances -> versions ──────────────
    op.create_table(
        "strategy_definitions",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("latest_version", sa.Text(), nullable=False),
        sa.Column("module", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column(
            "meta",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('INTERNAL', 'EXTERNAL')", name=op.f("ck_strategy_definitions_kind")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_strategy_definitions")),
    )

    op.create_table(
        "strategy_instances",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("definition_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'DRAFT'"), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("current_version_id", sa.UUID(), nullable=True),
        sa.Column(
            "tags", sa.ARRAY(sa.Text()), server_default=sa.text("'{}'::text[]"), nullable=False
        ),
        sa.Column(
            "webhook_secret_hashes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'BACKTESTED', 'PAPER', 'DEMO', 'LIVE_APPROVED', 'RETIRED')",
            name=op.f("ck_strategy_instances_status"),
        ),
        sa.ForeignKeyConstraint(
            ["definition_id"],
            ["strategy_definitions.id"],
            name=op.f("fk_strategy_instances_definition_id"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_strategy_instances")),
        sa.UniqueConstraint(
            "id", "definition_id", name=op.f("uq_strategy_instances_id_definition_id")
        ),
    )
    op.create_index(
        op.f("ix_strategy_instances_definition_id"),
        "strategy_instances",
        ["definition_id"],
        unique=False,
    )

    op.create_table(
        "strategy_versions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("instance_id", sa.Text(), nullable=False),
        sa.Column("definition_id", sa.Text(), nullable=False),
        sa.Column("definition_version", sa.Text(), nullable=False),
        sa.Column("code_hash", sa.Text(), nullable=True),
        sa.Column(
            "params",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("params_hash", sa.Text(), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("config_hash", sa.Text(), nullable=False),
        sa.Column("framework_fingerprint", sa.Text(), nullable=True),
        sa.Column("kterminal_version", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["definition_id"],
            ["strategy_definitions.id"],
            name=op.f("fk_strategy_versions_definition_id"),
        ),
        sa.ForeignKeyConstraint(
            ["instance_id", "definition_id"],
            ["strategy_instances.id", "strategy_instances.definition_id"],
            name=op.f("fk_strategy_versions_instance_id_definition_id"),
        ),
        sa.ForeignKeyConstraint(
            ["instance_id"],
            ["strategy_instances.id"],
            name=op.f("fk_strategy_versions_instance_id"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_strategy_versions")),
        sa.UniqueConstraint(
            "instance_id", "config_hash", name=op.f("uq_strategy_versions_instance_id_config_hash")
        ),
        sa.UniqueConstraint("instance_id", "id", name=op.f("uq_strategy_versions_instance_id_id")),
    )

    # strategy_instances <-> strategy_versions reference each other: the current
    # version (which must belong to the same instance) is added once both exist.
    op.create_foreign_key(
        op.f("fk_strategy_instances_id_current_version_id"),
        "strategy_instances",
        "strategy_versions",
        ["id", "current_version_id"],
        ["instance_id", "id"],
    )

    op.create_table(
        "strategy_promotions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("instance_id", sa.Text(), nullable=False),
        sa.Column("strategy_version_id", sa.UUID(), nullable=True),
        sa.Column("from_status", sa.Text(), nullable=False),
        sa.Column("to_status", sa.Text(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("approved_by", sa.UUID(), nullable=True),
        sa.Column("note", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "from_status IN ('DRAFT', 'BACKTESTED', 'PAPER', 'DEMO', 'LIVE_APPROVED', 'RETIRED')",
            name=op.f("ck_strategy_promotions_from_status"),
        ),
        sa.CheckConstraint(
            "to_status IN ('DRAFT', 'BACKTESTED', 'PAPER', 'DEMO', 'LIVE_APPROVED', 'RETIRED')",
            name=op.f("ck_strategy_promotions_to_status"),
        ),
        sa.ForeignKeyConstraint(
            ["approved_by"], ["users.id"], name=op.f("fk_strategy_promotions_approved_by")
        ),
        sa.ForeignKeyConstraint(
            ["instance_id"],
            ["strategy_instances.id"],
            name=op.f("fk_strategy_promotions_instance_id"),
        ),
        sa.ForeignKeyConstraint(
            ["strategy_version_id"],
            ["strategy_versions.id"],
            name=op.f("fk_strategy_promotions_strategy_version_id"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_strategy_promotions")),
    )
    op.create_index(
        op.f("ix_strategy_promotions_instance_id"),
        "strategy_promotions",
        ["instance_id"],
        unique=False,
    )

    op.create_table(
        "experiments",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'DRAFT'"), nullable=False),
        sa.Column(
            "conditions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'RUNNING', 'COMPLETED', 'ARCHIVED')",
            name=op.f("ck_experiments_status"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_experiments")),
    )

    op.create_table(
        "experiment_members",
        sa.Column("experiment_id", sa.Text(), nullable=False),
        sa.Column("instance_id", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["experiment_id"], ["experiments.id"], name=op.f("fk_experiment_members_experiment_id")
        ),
        sa.ForeignKeyConstraint(
            ["instance_id"],
            ["strategy_instances.id"],
            name=op.f("fk_experiment_members_instance_id"),
        ),
        sa.PrimaryKeyConstraint("experiment_id", "instance_id", name=op.f("pk_experiment_members")),
        sa.UniqueConstraint(
            "experiment_id", "label", name=op.f("uq_experiment_members_experiment_id_label")
        ),
    )
    op.create_index(
        op.f("ix_experiment_members_instance_id"),
        "experiment_members",
        ["instance_id"],
        unique=False,
    )

    # ── Runs ────────────────────────────────────────────────────────────────────
    op.create_table(
        "runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("experiment_id", sa.Text(), nullable=True),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "data_fingerprint",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("catalog_snapshot_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'QUEUED'"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "kind IN ('BACKTEST', 'LAB_SIMULATION', 'FORWARD', 'SIGNAL_REPLAY')",
            name=op.f("ck_runs_kind"),
        ),
        sa.CheckConstraint(
            "status IN ('QUEUED', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED')",
            name=op.f("ck_runs_status"),
        ),
        sa.CheckConstraint(
            "finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at",
            name=op.f("ck_runs_finished_after_started"),
        ),
        sa.ForeignKeyConstraint(
            ["catalog_snapshot_id"],
            ["catalog_snapshots.id"],
            name=op.f("fk_runs_catalog_snapshot_id"),
        ),
        sa.ForeignKeyConstraint(
            ["experiment_id"], ["experiments.id"], name=op.f("fk_runs_experiment_id")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_runs")),
    )
    op.create_index(op.f("ix_runs_experiment_id"), "runs", ["experiment_id"], unique=False)

    # ── Accounts ────────────────────────────────────────────────────────────────
    op.create_table(
        "risk_profiles",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_risk_profiles_version_positive")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_risk_profiles")),
        sa.UniqueConstraint("name", "version", name=op.f("uq_risk_profiles_name_version")),
    )

    op.create_table(
        "accounts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("broker", sa.Text(), nullable=False),
        sa.Column("venue_profile_id", sa.Text(), nullable=False),
        sa.Column("risk_profile_id", sa.UUID(), nullable=True),
        sa.Column("currency", sa.Text(), server_default=sa.text("'USD'"), nullable=False),
        sa.Column("starting_balance", sa.Numeric(precision=20, scale=4), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'ACTIVE'"), nullable=False),
        sa.Column("strategy_instance_id", sa.Text(), nullable=True),
        sa.Column("current_config_version_id", sa.UUID(), nullable=True),
        sa.Column("high_water_mark", sa.Numeric(precision=20, scale=4), nullable=False),
        sa.Column("broker_account_ref", sa.Text(), nullable=True),
        sa.Column("live_enabled_by", sa.UUID(), nullable=True),
        sa.Column("live_enabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "mode <> 'LIVE' OR live_enabled_by IS NOT NULL", name=op.f("ck_accounts_live_enabled")
        ),
        sa.CheckConstraint(
            "mode IN ('BACKTEST', 'PAPER', 'DEMO', 'LIVE')", name=op.f("ck_accounts_mode")
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'LOCKED_FOR_DAY', 'BREACHED', 'PASSED', 'PAUSED', 'CLOSED')",
            name=op.f("ck_accounts_status"),
        ),
        sa.CheckConstraint(
            "live_enabled_by IS NULL OR live_enabled_at IS NOT NULL",
            name=op.f("ck_accounts_live_enabled_at"),
        ),
        sa.CheckConstraint(
            "starting_balance > 0", name=op.f("ck_accounts_starting_balance_positive")
        ),
        sa.ForeignKeyConstraint(
            ["live_enabled_by"], ["users.id"], name=op.f("fk_accounts_live_enabled_by")
        ),
        sa.ForeignKeyConstraint(
            ["risk_profile_id"], ["risk_profiles.id"], name=op.f("fk_accounts_risk_profile_id")
        ),
        sa.ForeignKeyConstraint(
            ["strategy_instance_id"],
            ["strategy_instances.id"],
            name=op.f("fk_accounts_strategy_instance_id"),
        ),
        sa.ForeignKeyConstraint(
            ["venue_profile_id"], ["venue_profiles.id"], name=op.f("fk_accounts_venue_profile_id")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_accounts")),
        sa.UniqueConstraint("name", name=op.f("uq_accounts_name")),
        sa.UniqueConstraint("strategy_instance_id", name=op.f("uq_accounts_strategy_instance_id")),
    )

    op.create_table(
        "account_config_versions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("account_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("config_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "version >= 1", name=op.f("ck_account_config_versions_version_positive")
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"], name=op.f("fk_account_config_versions_account_id")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_account_config_versions")),
        sa.UniqueConstraint(
            "account_id",
            "config_hash",
            name=op.f("uq_account_config_versions_account_id_config_hash"),
        ),
        sa.UniqueConstraint(
            "account_id", "id", name=op.f("uq_account_config_versions_account_id_id")
        ),
        sa.UniqueConstraint(
            "account_id", "version", name=op.f("uq_account_config_versions_account_id_version")
        ),
    )

    # accounts <-> account_config_versions: same pattern as strategy instances.
    op.create_foreign_key(
        op.f("fk_accounts_id_current_config_version_id"),
        "accounts",
        "account_config_versions",
        ["id", "current_config_version_id"],
        ["account_id", "id"],
    )

    op.create_table(
        "account_allocations",
        sa.Column("account_id", sa.UUID(), nullable=False),
        sa.Column("instance_id", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "risk_multiplier",
            sa.Numeric(precision=6, scale=4),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "risk_multiplier > 0 AND risk_multiplier <= 1",
            name=op.f("ck_account_allocations_risk_multiplier_range"),
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"], name=op.f("fk_account_allocations_account_id")
        ),
        sa.ForeignKeyConstraint(
            ["instance_id"],
            ["strategy_instances.id"],
            name=op.f("fk_account_allocations_instance_id"),
        ),
        sa.PrimaryKeyConstraint("account_id", "instance_id", name=op.f("pk_account_allocations")),
    )
    op.create_index(
        op.f("ix_account_allocations_instance_id"),
        "account_allocations",
        ["instance_id"],
        unique=False,
    )

    # ── Signals & webhooks ──────────────────────────────────────────────────────
    op.create_table(
        "webhook_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_ip", postgresql.INET(), nullable=False),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("content_type", sa.Text(), nullable=True),
        sa.Column("body_redacted", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("body_sha256", sa.Text(), nullable=False),
        sa.Column("strategy_instance_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("reject_code", sa.Text(), nullable=True),
        sa.Column("reject_detail", sa.Text(), nullable=True),
        sa.Column("signal_id", sa.UUID(), nullable=True),
        sa.Column("processing_ms", sa.Integer(), nullable=False),
        sa.Column("correlation_id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "status IN ('ACCEPTED', 'DUPLICATE', 'REJECTED', 'TEST')",
            name=op.f("ck_webhook_events_status"),
        ),
        sa.CheckConstraint("processing_ms >= 0", name=op.f("ck_webhook_events_processing_ms")),
        sa.PrimaryKeyConstraint("id", "received_at", name=op.f("pk_webhook_events")),
        postgresql_partition_by="RANGE (received_at)",
    )
    op.create_index(
        op.f("ix_webhook_events_signal_id"),
        "webhook_events",
        ["signal_id"],
        unique=False,
        postgresql_where=sa.text("signal_id IS NOT NULL"),
    )
    op.create_index(
        op.f("ix_webhook_events_strategy_instance_id_received_at"),
        "webhook_events",
        ["strategy_instance_id", "received_at"],
        unique=False,
    )

    op.create_table(
        "signals",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("strategy_instance_id", sa.Text(), nullable=False),
        sa.Column("strategy_version_id", sa.UUID(), nullable=True),
        sa.Column("definition_id", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=True),
        sa.Column("instrument", sa.Text(), nullable=True),
        sa.Column("raw_symbol", sa.Text(), nullable=True),
        sa.Column("timeframe", sa.Text(), nullable=True),
        sa.Column("bar_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("signal_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("action", sa.Text(), nullable=True),
        sa.Column("order_type", sa.Text(), server_default=sa.text("'MARKET'"), nullable=False),
        sa.Column("entry", sa.Numeric(precision=24, scale=10), nullable=True),
        sa.Column("stop_loss", sa.Numeric(precision=24, scale=10), nullable=True),
        sa.Column("take_profit", sa.Numeric(precision=24, scale=10), nullable=True),
        sa.Column("risk_pct", sa.Numeric(precision=8, scale=4), nullable=True),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "market_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "raw_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'RECEIVED'"), nullable=False),
        sa.Column("reject_code", sa.Text(), nullable=True),
        sa.Column("reject_detail", sa.Text(), nullable=True),
        sa.Column("catalog_snapshot_id", sa.UUID(), nullable=True),
        sa.Column("correlation_id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "action IN ('LONG', 'SHORT', 'EXIT_LONG', 'EXIT_SHORT', 'MOVE_SL', 'NO_TRADE')",
            name=op.f("ck_signals_action"),
        ),
        sa.CheckConstraint(
            "order_type IN ('MARKET', 'LIMIT', 'STOP')", name=op.f("ck_signals_order_type")
        ),
        sa.CheckConstraint(
            "source IN ('INTERNAL', 'TRADINGVIEW', 'MANUAL', 'REPLAY')",
            name=op.f("ck_signals_source"),
        ),
        sa.CheckConstraint(
            "status = 'INVALID' OR (strategy_version_id IS NOT NULL AND instrument IS NOT NULL "
            "AND timeframe IS NOT NULL AND action IS NOT NULL)",
            name=op.f("ck_signals_valid_signal_complete"),
        ),
        sa.CheckConstraint(
            "status IN ('RECEIVED', 'ROUTED', 'IGNORED', 'INVALID', 'EXPIRED')",
            name=op.f("ck_signals_status"),
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name=op.f("ck_signals_confidence_range")
        ),
        sa.CheckConstraint(
            "risk_pct > 0 AND risk_pct <= 100", name=op.f("ck_signals_risk_pct_range")
        ),
        sa.ForeignKeyConstraint(
            ["catalog_snapshot_id"],
            ["catalog_snapshots.id"],
            name=op.f("fk_signals_catalog_snapshot_id"),
        ),
        sa.ForeignKeyConstraint(
            ["definition_id"], ["strategy_definitions.id"], name=op.f("fk_signals_definition_id")
        ),
        sa.ForeignKeyConstraint(
            ["instrument"], ["instruments.symbol"], name=op.f("fk_signals_instrument")
        ),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], name=op.f("fk_signals_run_id")),
        sa.ForeignKeyConstraint(
            ["strategy_instance_id", "definition_id"],
            ["strategy_instances.id", "strategy_instances.definition_id"],
            name=op.f("fk_signals_strategy_instance_id_definition_id"),
        ),
        sa.ForeignKeyConstraint(
            ["strategy_instance_id", "strategy_version_id"],
            ["strategy_versions.instance_id", "strategy_versions.id"],
            name=op.f("fk_signals_strategy_instance_id_strategy_version_id"),
        ),
        sa.ForeignKeyConstraint(
            ["strategy_instance_id"],
            ["strategy_instances.id"],
            name=op.f("fk_signals_strategy_instance_id"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_signals")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_signals_idempotency_key")),
    )
    op.create_index(
        op.f("ix_signals_run_id"),
        "signals",
        ["run_id"],
        unique=False,
        postgresql_where=sa.text("run_id IS NOT NULL"),
    )
    op.create_index(
        op.f("ix_signals_strategy_instance_id_signal_time"),
        "signals",
        ["strategy_instance_id", "signal_time"],
        unique=False,
    )
    op.create_index(
        op.f("ix_signals_strategy_version_id"), "signals", ["strategy_version_id"], unique=False
    )

    # ── Risk ────────────────────────────────────────────────────────────────────
    op.create_table(
        "risk_decisions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("signal_id", sa.UUID(), nullable=False),
        sa.Column("account_id", sa.UUID(), nullable=False),
        sa.Column("account_config_version_id", sa.UUID(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved", sa.Boolean(), nullable=False),
        sa.Column("primary_reason", sa.Text(), nullable=True),
        sa.Column("rule_results", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("account_state", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("risk_profile_id", sa.UUID(), nullable=True),
        sa.Column(
            "quote",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("requested_qty", sa.Numeric(precision=24, scale=10), nullable=True),
        sa.Column("approved_qty", sa.Numeric(precision=24, scale=10), nullable=True),
        sa.Column("risk_amount", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("risk_pct", sa.Numeric(precision=8, scale=4), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("catalog_snapshot_id", sa.UUID(), nullable=True),
        sa.Column("run_id", sa.UUID(), nullable=True),
        sa.Column("correlation_id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "approved OR primary_reason IS NOT NULL",
            name=op.f("ck_risk_decisions_rejection_has_reason"),
        ),
        sa.ForeignKeyConstraint(
            ["account_id", "account_config_version_id"],
            ["account_config_versions.account_id", "account_config_versions.id"],
            name=op.f("fk_risk_decisions_account_id_account_config_version_id"),
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"], name=op.f("fk_risk_decisions_account_id")
        ),
        sa.ForeignKeyConstraint(
            ["catalog_snapshot_id"],
            ["catalog_snapshots.id"],
            name=op.f("fk_risk_decisions_catalog_snapshot_id"),
        ),
        sa.ForeignKeyConstraint(
            ["risk_profile_id"],
            ["risk_profiles.id"],
            name=op.f("fk_risk_decisions_risk_profile_id"),
        ),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], name=op.f("fk_risk_decisions_run_id")),
        sa.ForeignKeyConstraint(
            ["signal_id"], ["signals.id"], name=op.f("fk_risk_decisions_signal_id")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_risk_decisions")),
        sa.UniqueConstraint(
            "signal_id", "account_id", name=op.f("uq_risk_decisions_signal_id_account_id")
        ),
    )
    op.create_index(
        op.f("ix_risk_decisions_account_id_decided_at"),
        "risk_decisions",
        ["account_id", "decided_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_risk_decisions_run_id"),
        "risk_decisions",
        ["run_id"],
        unique=False,
        postgresql_where=sa.text("run_id IS NOT NULL"),
    )

    op.create_table(
        "risk_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("account_id", sa.UUID(), nullable=True),
        sa.Column("strategy_instance_id", sa.Text(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("threshold", sa.Numeric(precision=8, scale=4), nullable=True),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("run_id", sa.UUID(), nullable=True),
        sa.Column("correlation_id", sa.UUID(), nullable=True),
        sa.CheckConstraint(
            "severity IN ('INFO', 'WARNING', 'CRITICAL')", name=op.f("ck_risk_events_severity")
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"], name=op.f("fk_risk_events_account_id")
        ),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], name=op.f("fk_risk_events_run_id")),
        sa.ForeignKeyConstraint(
            ["strategy_instance_id"],
            ["strategy_instances.id"],
            name=op.f("fk_risk_events_strategy_instance_id"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_risk_events")),
    )
    op.create_index(
        op.f("ix_risk_events_account_id_ts"), "risk_events", ["account_id", "ts"], unique=False
    )

    op.create_table(
        "kill_switches",
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("scope_id", sa.Text(), server_default=sa.text("'*'"), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("close_positions", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("cancel_orders", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("changed_by", sa.Text(), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "scope IN ('GLOBAL', 'ACCOUNT', 'STRATEGY')", name=op.f("ck_kill_switches_scope")
        ),
        sa.PrimaryKeyConstraint("scope", "scope_id", name=op.f("pk_kill_switches")),
    )

    # ── Trades, orders & fills ──────────────────────────────────────────────────
    op.create_table(
        "trades",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("account_id", sa.UUID(), nullable=False),
        sa.Column("account_config_version_id", sa.UUID(), nullable=False),
        sa.Column("strategy_instance_id", sa.Text(), nullable=False),
        sa.Column("strategy_version_id", sa.UUID(), nullable=False),
        sa.Column("entry_signal_id", sa.UUID(), nullable=False),
        sa.Column("exit_signal_id", sa.UUID(), nullable=True),
        sa.Column("run_id", sa.UUID(), nullable=True),
        sa.Column("catalog_snapshot_id", sa.UUID(), nullable=True),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("instrument", sa.Text(), nullable=False),
        sa.Column("venue", sa.Text(), nullable=False),
        sa.Column("venue_symbol", sa.Text(), nullable=False),
        sa.Column("timeframe", sa.Text(), nullable=False),
        sa.Column("direction", sa.Text(), nullable=False),
        sa.Column("qty", sa.Numeric(precision=24, scale=10), nullable=False),
        sa.Column("entry_requested", sa.Numeric(precision=24, scale=10), nullable=False),
        sa.Column("entry_price", sa.Numeric(precision=24, scale=10), nullable=False),
        sa.Column("entry_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("initial_stop", sa.Numeric(precision=24, scale=10), nullable=False),
        sa.Column("initial_target", sa.Numeric(precision=24, scale=10), nullable=True),
        sa.Column("current_stop", sa.Numeric(precision=24, scale=10), nullable=True),
        sa.Column("current_target", sa.Numeric(precision=24, scale=10), nullable=True),
        sa.Column("exit_price", sa.Numeric(precision=24, scale=10), nullable=True),
        sa.Column("exit_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exit_reason", sa.Text(), nullable=True),
        sa.Column("initial_risk", sa.Numeric(precision=20, scale=4), nullable=False),
        sa.Column("gross_pnl", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column(
            "commission",
            sa.Numeric(precision=20, scale=4),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "swap", sa.Numeric(precision=20, scale=4), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "funding",
            sa.Numeric(precision=20, scale=4),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "spread_cost",
            sa.Numeric(precision=20, scale=4),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("net_pnl", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("r_multiple", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("entry_slippage", sa.Numeric(precision=24, scale=10), nullable=True),
        sa.Column("exit_slippage", sa.Numeric(precision=24, scale=10), nullable=True),
        sa.Column("mae", sa.Numeric(precision=24, scale=10), nullable=True),
        sa.Column("mfe", sa.Numeric(precision=24, scale=10), nullable=True),
        sa.Column("session", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("correlation_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("direction IN ('LONG', 'SHORT')", name=op.f("ck_trades_direction")),
        sa.CheckConstraint(
            "exit_reason IN ('TAKE_PROFIT', 'STOP_LOSS', 'BREAKEVEN_STOP', 'TRAILING_STOP', "
            "'SIGNAL_EXIT', 'REVERSAL', 'MANUAL', 'KILL_SWITCH', 'RISK_FLATTEN', "
            "'SESSION_CLOSE', 'BROKER_LIQUIDATION', 'RUN_END')",
            name=op.f("ck_trades_exit_reason"),
        ),
        sa.CheckConstraint(
            "mode IN ('BACKTEST', 'PAPER', 'DEMO', 'LIVE')", name=op.f("ck_trades_mode")
        ),
        sa.CheckConstraint(
            "status = 'OPEN' OR (exit_price IS NOT NULL AND exit_time IS NOT NULL AND "
            "exit_reason IS NOT NULL AND net_pnl IS NOT NULL)",
            name=op.f("ck_trades_closed_trade_complete"),
        ),
        sa.CheckConstraint("status IN ('OPEN', 'CLOSED')", name=op.f("ck_trades_status")),
        sa.CheckConstraint(
            "exit_time IS NULL OR exit_time >= entry_time", name=op.f("ck_trades_exit_after_entry")
        ),
        sa.CheckConstraint("qty > 0", name=op.f("ck_trades_qty_positive")),
        sa.ForeignKeyConstraint(
            ["account_id", "account_config_version_id"],
            ["account_config_versions.account_id", "account_config_versions.id"],
            name=op.f("fk_trades_account_id_account_config_version_id"),
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], name=op.f("fk_trades_account_id")),
        sa.ForeignKeyConstraint(
            ["catalog_snapshot_id"],
            ["catalog_snapshots.id"],
            name=op.f("fk_trades_catalog_snapshot_id"),
        ),
        sa.ForeignKeyConstraint(
            ["entry_signal_id"], ["signals.id"], name=op.f("fk_trades_entry_signal_id")
        ),
        sa.ForeignKeyConstraint(
            ["exit_signal_id"], ["signals.id"], name=op.f("fk_trades_exit_signal_id")
        ),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], name=op.f("fk_trades_run_id")),
        sa.ForeignKeyConstraint(
            ["strategy_instance_id", "strategy_version_id"],
            ["strategy_versions.instance_id", "strategy_versions.id"],
            name=op.f("fk_trades_strategy_instance_id_strategy_version_id"),
        ),
        sa.ForeignKeyConstraint(
            ["strategy_instance_id"],
            ["strategy_instances.id"],
            name=op.f("fk_trades_strategy_instance_id"),
        ),
        sa.ForeignKeyConstraint(
            ["venue", "instrument"],
            ["instrument_listings.venue", "instrument_listings.instrument"],
            name=op.f("fk_trades_venue_instrument"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trades")),
    )
    op.create_index(
        op.f("ix_trades_account_id_status"), "trades", ["account_id", "status"], unique=False
    )
    op.create_index(
        op.f("ix_trades_run_id"),
        "trades",
        ["run_id"],
        unique=False,
        postgresql_where=sa.text("run_id IS NOT NULL"),
    )
    op.create_index(
        op.f("ix_trades_strategy_instance_id_exit_time"),
        "trades",
        ["strategy_instance_id", "exit_time"],
        unique=False,
    )
    op.create_index(
        op.f("ix_trades_strategy_version_id"), "trades", ["strategy_version_id"], unique=False
    )

    op.create_table(
        "orders",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("client_order_id", sa.Text(), nullable=False),
        sa.Column("broker_order_id", sa.Text(), nullable=True),
        sa.Column("account_id", sa.UUID(), nullable=False),
        sa.Column("strategy_instance_id", sa.Text(), nullable=True),
        sa.Column("trade_id", sa.UUID(), nullable=True),
        sa.Column("signal_id", sa.UUID(), nullable=True),
        sa.Column("risk_decision_id", sa.UUID(), nullable=True),
        sa.Column("parent_order_id", sa.UUID(), nullable=True),
        sa.Column("run_id", sa.UUID(), nullable=True),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("venue", sa.Text(), nullable=False),
        sa.Column("instrument", sa.Text(), nullable=False),
        sa.Column("venue_symbol", sa.Text(), nullable=False),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("order_type", sa.Text(), nullable=False),
        sa.Column("qty", sa.Numeric(precision=24, scale=10), nullable=False),
        sa.Column("requested_price", sa.Numeric(precision=24, scale=10), nullable=True),
        sa.Column("time_in_force", sa.Text(), server_default=sa.text("'GTC'"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "filled_qty",
            sa.Numeric(precision=24, scale=10),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("avg_fill_price", sa.Numeric(precision=24, scale=10), nullable=True),
        sa.Column("slippage", sa.Numeric(precision=24, scale=10), nullable=True),
        sa.Column(
            "commission",
            sa.Numeric(precision=20, scale=4),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("reject_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("correlation_id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "mode IN ('BACKTEST', 'PAPER', 'DEMO', 'LIVE')", name=op.f("ck_orders_mode")
        ),
        sa.CheckConstraint(
            "order_type IN ('MARKET', 'LIMIT', 'STOP')", name=op.f("ck_orders_order_type")
        ),
        sa.CheckConstraint(
            "purpose <> 'ENTRY' OR risk_decision_id IS NOT NULL",
            name=op.f("ck_orders_entry_has_risk_decision"),
        ),
        sa.CheckConstraint(
            "purpose IN ('ENTRY', 'STOP_LOSS', 'TAKE_PROFIT', 'EXIT', 'FLATTEN')",
            name=op.f("ck_orders_purpose"),
        ),
        sa.CheckConstraint("side IN ('BUY', 'SELL')", name=op.f("ck_orders_side")),
        sa.CheckConstraint(
            "status IN ('PENDING_SUBMIT', 'SUBMITTED', 'ACCEPTED', 'PARTIALLY_FILLED', 'FILLED', "
            "'CANCELLED', 'REJECTED', 'EXPIRED', 'FAILED')",
            name=op.f("ck_orders_status"),
        ),
        sa.CheckConstraint(
            "time_in_force IN ('GTC', 'DAY', 'IOC', 'FOK')", name=op.f("ck_orders_time_in_force")
        ),
        sa.CheckConstraint(
            "filled_qty >= 0 AND filled_qty <= qty", name=op.f("ck_orders_filled_qty_range")
        ),
        sa.CheckConstraint("qty > 0", name=op.f("ck_orders_qty_positive")),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], name=op.f("fk_orders_account_id")),
        sa.ForeignKeyConstraint(
            ["parent_order_id"], ["orders.id"], name=op.f("fk_orders_parent_order_id")
        ),
        sa.ForeignKeyConstraint(
            ["risk_decision_id"], ["risk_decisions.id"], name=op.f("fk_orders_risk_decision_id")
        ),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], name=op.f("fk_orders_run_id")),
        sa.ForeignKeyConstraint(["signal_id"], ["signals.id"], name=op.f("fk_orders_signal_id")),
        sa.ForeignKeyConstraint(
            ["strategy_instance_id"],
            ["strategy_instances.id"],
            name=op.f("fk_orders_strategy_instance_id"),
        ),
        sa.ForeignKeyConstraint(["trade_id"], ["trades.id"], name=op.f("fk_orders_trade_id")),
        sa.ForeignKeyConstraint(
            ["venue", "instrument"],
            ["instrument_listings.venue", "instrument_listings.instrument"],
            name=op.f("fk_orders_venue_instrument"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_orders")),
        sa.UniqueConstraint("client_order_id", name=op.f("uq_orders_client_order_id")),
    )
    op.create_index(
        op.f("ix_orders_account_id_status"), "orders", ["account_id", "status"], unique=False
    )
    op.create_index(
        op.f("ix_orders_run_id"),
        "orders",
        ["run_id"],
        unique=False,
        postgresql_where=sa.text("run_id IS NOT NULL"),
    )
    op.create_index(
        op.f("ix_orders_signal_id"),
        "orders",
        ["signal_id"],
        unique=False,
        postgresql_where=sa.text("signal_id IS NOT NULL"),
    )
    op.create_index(
        op.f("ix_orders_trade_id"),
        "orders",
        ["trade_id"],
        unique=False,
        postgresql_where=sa.text("trade_id IS NOT NULL"),
    )

    op.create_table(
        "order_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("order_id", sa.UUID(), nullable=False),
        sa.Column("from_status", sa.Text(), nullable=True),
        sa.Column("to_status", sa.Text(), nullable=False),
        sa.Column("broker_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], name=op.f("fk_order_events_order_id")),
        sa.PrimaryKeyConstraint("id", "ts", name=op.f("pk_order_events")),
        postgresql_partition_by="RANGE (ts)",
    )
    op.create_index(
        op.f("ix_order_events_order_id_ts"), "order_events", ["order_id", "ts"], unique=False
    )

    op.create_table(
        "fills",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("order_id", sa.UUID(), nullable=False),
        sa.Column("account_id", sa.UUID(), nullable=False),
        sa.Column("broker_fill_id", sa.Text(), nullable=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("qty", sa.Numeric(precision=24, scale=10), nullable=False),
        sa.Column("price", sa.Numeric(precision=24, scale=10), nullable=False),
        sa.Column(
            "commission",
            sa.Numeric(precision=20, scale=4),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("liquidity", sa.Text(), nullable=True),
        sa.Column(
            "spread_cost",
            sa.Numeric(precision=20, scale=4),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "slippage",
            sa.Numeric(precision=24, scale=10),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("run_id", sa.UUID(), nullable=True),
        sa.CheckConstraint("liquidity IN ('MAKER', 'TAKER')", name=op.f("ck_fills_liquidity")),
        sa.CheckConstraint("qty > 0 AND price > 0", name=op.f("ck_fills_qty_price_positive")),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], name=op.f("fk_fills_account_id")),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], name=op.f("fk_fills_order_id")),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], name=op.f("fk_fills_run_id")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fills")),
        sa.UniqueConstraint(
            "order_id", "broker_fill_id", name=op.f("uq_fills_order_id_broker_fill_id")
        ),
    )
    op.create_index(op.f("ix_fills_account_id_ts"), "fills", ["account_id", "ts"], unique=False)
    op.create_index(
        op.f("ix_fills_run_id"),
        "fills",
        ["run_id"],
        unique=False,
        postgresql_where=sa.text("run_id IS NOT NULL"),
    )

    op.create_table(
        "trade_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("trade_id", sa.UUID(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("old_value", sa.Numeric(precision=24, scale=10), nullable=True),
        sa.Column("new_value", sa.Numeric(precision=24, scale=10), nullable=True),
        sa.Column("signal_id", sa.UUID(), nullable=True),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('STOP_MOVED', 'BREAKEVEN', 'TARGET_MOVED', 'PARTIAL_CLOSE', 'NOTE')",
            name=op.f("ck_trade_events_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["signal_id"], ["signals.id"], name=op.f("fk_trade_events_signal_id")
        ),
        sa.ForeignKeyConstraint(["trade_id"], ["trades.id"], name=op.f("fk_trade_events_trade_id")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trade_events")),
    )
    op.create_index(
        op.f("ix_trade_events_trade_id_ts"), "trade_events", ["trade_id", "ts"], unique=False
    )

    op.create_table(
        "account_ledger",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("account_id", sa.UUID(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=20, scale=4), nullable=False),
        sa.Column("balance_after", sa.Numeric(precision=20, scale=4), nullable=False),
        sa.Column("trade_id", sa.UUID(), nullable=True),
        sa.Column("fill_id", sa.UUID(), nullable=True),
        sa.Column("run_id", sa.UUID(), nullable=True),
        sa.Column("note", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.CheckConstraint(
            "kind IN ('DEPOSIT', 'REALIZED_PNL', 'COMMISSION', 'SWAP', 'FUNDING', 'ADJUSTMENT', "
            "'RESET')",
            name=op.f("ck_account_ledger_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"], name=op.f("fk_account_ledger_account_id")
        ),
        sa.ForeignKeyConstraint(["fill_id"], ["fills.id"], name=op.f("fk_account_ledger_fill_id")),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], name=op.f("fk_account_ledger_run_id")),
        sa.ForeignKeyConstraint(
            ["trade_id"], ["trades.id"], name=op.f("fk_account_ledger_trade_id")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_account_ledger")),
        sa.UniqueConstraint("seq", name=op.f("uq_account_ledger_seq")),
    )
    op.create_index(
        op.f("ix_account_ledger_account_id_seq"),
        "account_ledger",
        ["account_id", "seq"],
        unique=False,
    )
    op.create_index(
        op.f("ix_account_ledger_run_id"),
        "account_ledger",
        ["run_id"],
        unique=False,
        postgresql_where=sa.text("run_id IS NOT NULL"),
    )
    op.create_index(
        op.f("ix_account_ledger_trade_id"),
        "account_ledger",
        ["trade_id"],
        unique=False,
        postgresql_where=sa.text("trade_id IS NOT NULL"),
    )

    op.create_table(
        "equity_snapshots",
        sa.Column("account_id", sa.UUID(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("balance", sa.Numeric(precision=20, scale=4), nullable=False),
        sa.Column("equity", sa.Numeric(precision=20, scale=4), nullable=False),
        sa.Column("open_pnl", sa.Numeric(precision=20, scale=4), nullable=False),
        sa.Column("open_risk", sa.Numeric(precision=20, scale=4), nullable=False),
        sa.Column("daily_pnl", sa.Numeric(precision=20, scale=4), nullable=False),
        sa.Column("drawdown", sa.Numeric(precision=20, scale=4), nullable=False),
        sa.Column("high_water_mark", sa.Numeric(precision=20, scale=4), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"], name=op.f("fk_equity_snapshots_account_id")
        ),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], name=op.f("fk_equity_snapshots_run_id")),
        sa.PrimaryKeyConstraint("account_id", "ts", name=op.f("pk_equity_snapshots")),
        postgresql_partition_by="RANGE (ts)",
    )
    op.create_index(
        op.f("ix_equity_snapshots_run_id"),
        "equity_snapshots",
        ["run_id"],
        unique=False,
        postgresql_where=sa.text("run_id IS NOT NULL"),
    )

    # ── Analytics & market data ─────────────────────────────────────────────────
    op.create_table(
        "performance_metrics",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("scope_id", sa.Text(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("dimension", sa.Text(), nullable=False),
        sa.Column("bucket", sa.Text(), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("trade_count", sa.Integer(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "dimension IN ('ALL', 'SYMBOL', 'TIMEFRAME', 'SESSION', 'DAY', 'WEEK', 'MONTH', "
            "'DIRECTION')",
            name=op.f("ck_performance_metrics_dimension"),
        ),
        sa.CheckConstraint(
            "mode IN ('BACKTEST', 'PAPER', 'DEMO', 'LIVE')",
            name=op.f("ck_performance_metrics_mode"),
        ),
        sa.CheckConstraint(
            "scope IN ('STRATEGY_INSTANCE', 'STRATEGY_VERSION', 'ACCOUNT', 'RUN', 'EXPERIMENT')",
            name=op.f("ck_performance_metrics_scope"),
        ),
        sa.CheckConstraint("trade_count >= 0", name=op.f("ck_performance_metrics_trade_count")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_performance_metrics")),
        sa.UniqueConstraint(
            "scope",
            "scope_id",
            "mode",
            "dimension",
            "bucket",
            name=op.f("uq_performance_metrics_scope_scope_id_mode_dimension_bucket"),
        ),
    )

    op.create_table(
        "candles",
        sa.Column("instrument", sa.Text(), nullable=False),
        sa.Column("timeframe", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Numeric(precision=24, scale=10), nullable=False),
        sa.Column("high", sa.Numeric(precision=24, scale=10), nullable=False),
        sa.Column("low", sa.Numeric(precision=24, scale=10), nullable=False),
        sa.Column("close", sa.Numeric(precision=24, scale=10), nullable=False),
        sa.Column("volume", sa.Numeric(precision=24, scale=10), nullable=True),
        sa.CheckConstraint(
            "low <= open AND low <= close AND high >= open AND high >= close AND low <= high",
            name=op.f("ck_candles_ohlc_consistent"),
        ),
        sa.CheckConstraint("volume IS NULL OR volume >= 0", name=op.f("ck_candles_volume")),
        sa.PrimaryKeyConstraint("instrument", "timeframe", "source", "ts", name=op.f("pk_candles")),
        postgresql_partition_by="RANGE (ts)",
    )

    # ── Notifications, system & audit ───────────────────────────────────────────
    op.create_table(
        "outbox",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("correlation_id", sa.UUID(), nullable=True),
        sa.CheckConstraint("attempts >= 0", name=op.f("ck_outbox_attempts")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_outbox")),
    )
    op.create_index(
        op.f("ix_outbox_topic_available_at"),
        "outbox",
        ["topic", "available_at"],
        unique=False,
        postgresql_where=sa.text("processed_at IS NULL"),
    )

    op.create_table(
        "notifications",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("channel", sa.Text(), server_default=sa.text("'telegram'"), nullable=False),
        sa.Column("destination", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("dedupe_key", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("rendered_text", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("provider_message_id", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("correlation_id", sa.UUID(), nullable=True),
        sa.CheckConstraint(
            "status IN ('PENDING', 'SENT', 'FAILED', 'SUPPRESSED')",
            name=op.f("ck_notifications_status"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
        sa.UniqueConstraint(
            "channel", "dedupe_key", name=op.f("uq_notifications_channel_dedupe_key")
        ),
    )

    op.create_table(
        "report_runs",
        sa.Column("report", sa.Text(), nullable=False),
        sa.Column("period_key", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('PENDING', 'SENT', 'FAILED', 'SKIPPED')", name=op.f("ck_report_runs_status")
        ),
        sa.PrimaryKeyConstraint("report", "period_key", name=op.f("pk_report_runs")),
    )

    op.create_table(
        "system_errors",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("component", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("exception", sa.Text(), nullable=True),
        sa.Column(
            "context",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("strategy_instance_id", sa.Text(), nullable=True),
        sa.Column("run_id", sa.UUID(), nullable=True),
        sa.Column("correlation_id", sa.UUID(), nullable=True),
        sa.CheckConstraint(
            "severity IN ('WARNING', 'ERROR', 'CRITICAL')", name=op.f("ck_system_errors_severity")
        ),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], name=op.f("fk_system_errors_run_id")),
        sa.ForeignKeyConstraint(
            ["strategy_instance_id"],
            ["strategy_instances.id"],
            name=op.f("fk_system_errors_strategy_instance_id"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_system_errors")),
    )
    op.create_index(
        op.f("ix_system_errors_strategy_instance_id_ts"),
        "system_errors",
        ["strategy_instance_id", "ts"],
        unique=False,
        postgresql_where=sa.text("strategy_instance_id IS NOT NULL"),
    )
    op.create_index(op.f("ix_system_errors_ts"), "system_errors", ["ts"], unique=False)

    op.create_table(
        "system_state",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_system_state")),
    )

    op.create_table(
        "audit_log",
        sa.Column("seq", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Text(), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("correlation_id", sa.UUID(), nullable=True),
        sa.Column("prev_hash", sa.Text(), nullable=False),
        sa.Column("hash", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("seq", "ts", name=op.f("pk_audit_log")),
        postgresql_partition_by="RANGE (ts)",
    )
    op.create_index(
        op.f("ix_audit_log_entity_type_entity_id"),
        "audit_log",
        ["entity_type", "entity_id"],
        unique=False,
    )

    # ── Partitions and the append-only audit guard ────────────────────────────
    for table in PARTITIONED_TABLES:
        op.execute(f"CREATE TABLE {table}_default PARTITION OF {table} DEFAULT")

    op.execute(
        f"""
        CREATE FUNCTION {AUDIT_GUARD_FUNCTION}() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'audit_log is append-only: % is not allowed', TG_OP
                USING HINT = 'The audit trail can only be appended to (kterminal.db.audit.append).';
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER audit_log_append_only BEFORE UPDATE OR DELETE ON audit_log "
        f"FOR EACH ROW EXECUTE FUNCTION {AUDIT_GUARD_FUNCTION}()"
    )
    for table in ("audit_log", "audit_log_default"):
        op.execute(
            f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} "
            f"FOR EACH STATEMENT EXECUTE FUNCTION {AUDIT_GUARD_FUNCTION}()"
        )


def downgrade() -> None:
    # Dropping a partitioned table drops all of its partitions and their triggers.
    op.drop_constraint(
        op.f("fk_accounts_id_current_config_version_id"), "accounts", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_strategy_instances_id_current_version_id"),
        "strategy_instances",
        type_="foreignkey",
    )
    for table in reversed(_TABLES):
        op.drop_table(table)
    op.execute(f"DROP FUNCTION {AUDIT_GUARD_FUNCTION}()")


_TABLES = (
    "users",
    "catalog_snapshots",
    "trading_day_rules",
    "trading_calendars",
    "session_windows",
    "cost_profiles",
    "venues",
    "instruments",
    "instrument_listings",
    "symbol_aliases",
    "venue_profiles",
    "venue_profile_entries",
    "strategy_definitions",
    "strategy_instances",
    "strategy_versions",
    "strategy_promotions",
    "experiments",
    "experiment_members",
    "runs",
    "risk_profiles",
    "accounts",
    "account_config_versions",
    "account_allocations",
    "webhook_events",
    "signals",
    "risk_decisions",
    "risk_events",
    "kill_switches",
    "trades",
    "orders",
    "order_events",
    "fills",
    "trade_events",
    "account_ledger",
    "equity_snapshots",
    "performance_metrics",
    "candles",
    "outbox",
    "notifications",
    "report_runs",
    "system_errors",
    "system_state",
    "audit_log",
)
"""Every table in creation order (dropped in reverse)."""
