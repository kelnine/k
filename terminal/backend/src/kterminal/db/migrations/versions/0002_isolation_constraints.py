"""Isolation in the schema, complete signals, retired venue symbols.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-08

From the adversarial review of the Phase 2 database layer:

* **Isolation is enforced by the database for every row that touches money.**
  A trade, an order and a risk decision must sit on an account allocated to
  their strategy instance; a trade is opened/closed and a decision is taken
  only on that instance's own signals (composite foreign keys onto
  ``account_allocations`` and onto the new ``UNIQUE (signals.id,
  signals.strategy_instance_id)``). ``risk_decisions`` gains the
  ``strategy_instance_id`` it needs for that, backfilled from its signal.
* **An ENTRY order must cite an approved decision of the same account**, not
  just any decision: ``orders.entry_approved`` (generated: TRUE for ENTRY,
  NULL otherwise) plus a foreign key onto ``UNIQUE (risk_decisions.id,
  account_id, approved)``.
* **Signals keep the strategy's reason and a resting entry's lifetime**
  (``signals.reason``, ``signals.expires_after_bars``).
* **A venue symbol names one *enabled* listing**, checked at commit: a
  retired listing that history still references keeps its symbol without
  reserving it, and symbols can move between listings in one catalog update.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ALLOCATIONS = ("account_allocations", ["account_id", "instance_id"])


def upgrade() -> None:
    # ── signals ──────────────────────────────────────────────────────────────
    op.add_column("signals", sa.Column("reason", sa.Text(), nullable=True))
    op.add_column("signals", sa.Column("expires_after_bars", sa.Integer(), nullable=True))
    op.create_check_constraint(
        op.f("ck_signals_expires_after_bars"),
        "signals",
        "expires_after_bars IS NULL OR expires_after_bars >= 1",
    )
    op.create_unique_constraint(
        op.f("uq_signals_id_strategy_instance_id"), "signals", ["id", "strategy_instance_id"]
    )

    # ── risk decisions ───────────────────────────────────────────────────────
    op.add_column("risk_decisions", sa.Column("strategy_instance_id", sa.Text(), nullable=True))
    op.execute(
        "UPDATE risk_decisions AS d SET strategy_instance_id = s.strategy_instance_id "
        "FROM signals AS s WHERE s.id = d.signal_id"
    )
    op.alter_column("risk_decisions", "strategy_instance_id", nullable=False)
    op.create_foreign_key(
        op.f("fk_risk_decisions_strategy_instance_id"),
        "risk_decisions",
        "strategy_instances",
        ["strategy_instance_id"],
        ["id"],
    )
    op.create_unique_constraint(
        op.f("uq_risk_decisions_id_account_id_approved"),
        "risk_decisions",
        ["id", "account_id", "approved"],
    )
    op.create_foreign_key(
        op.f("fk_risk_decisions_signal_id_strategy_instance_id"),
        "risk_decisions",
        "signals",
        ["signal_id", "strategy_instance_id"],
        ["id", "strategy_instance_id"],
    )
    op.create_foreign_key(
        op.f("fk_risk_decisions_account_id_strategy_instance_id"),
        "risk_decisions",
        ALLOCATIONS[0],
        ["account_id", "strategy_instance_id"],
        ALLOCATIONS[1],
    )

    # ── trades ───────────────────────────────────────────────────────────────
    op.create_foreign_key(
        op.f("fk_trades_account_id_strategy_instance_id"),
        "trades",
        ALLOCATIONS[0],
        ["account_id", "strategy_instance_id"],
        ALLOCATIONS[1],
    )
    for column in ("entry_signal_id", "exit_signal_id"):
        op.create_foreign_key(
            op.f(f"fk_trades_{column}_strategy_instance_id"),
            "trades",
            "signals",
            [column, "strategy_instance_id"],
            ["id", "strategy_instance_id"],
        )

    # ── orders ───────────────────────────────────────────────────────────────
    op.add_column(
        "orders",
        sa.Column(
            "entry_approved",
            sa.Boolean(),
            sa.Computed("CASE WHEN purpose = 'ENTRY' THEN true END", persisted=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        op.f("fk_orders_risk_decision_id_account_id_entry_approved"),
        "orders",
        "risk_decisions",
        ["risk_decision_id", "account_id", "entry_approved"],
        ["id", "account_id", "approved"],
    )
    op.create_foreign_key(
        op.f("fk_orders_account_id_strategy_instance_id"),
        "orders",
        ALLOCATIONS[0],
        ["account_id", "strategy_instance_id"],
        ALLOCATIONS[1],
    )

    # ── instrument listings ──────────────────────────────────────────────────
    op.drop_constraint(
        op.f("uq_instrument_listings_venue_venue_symbol"), "instrument_listings", type_="unique"
    )
    op.execute(
        "ALTER TABLE instrument_listings ADD CONSTRAINT ex_instrument_listings_venue_venue_symbol "
        "EXCLUDE USING btree (venue WITH =, venue_symbol WITH =) WHERE (enabled) "
        "DEFERRABLE INITIALLY DEFERRED"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE instrument_listings DROP CONSTRAINT ex_instrument_listings_venue_venue_symbol"
    )
    op.create_unique_constraint(
        op.f("uq_instrument_listings_venue_venue_symbol"),
        "instrument_listings",
        ["venue", "venue_symbol"],
    )
    op.drop_constraint(
        op.f("fk_orders_account_id_strategy_instance_id"), "orders", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_orders_risk_decision_id_account_id_entry_approved"), "orders", type_="foreignkey"
    )
    op.drop_column("orders", "entry_approved")
    for column in ("exit_signal_id", "entry_signal_id"):
        op.drop_constraint(
            op.f(f"fk_trades_{column}_strategy_instance_id"), "trades", type_="foreignkey"
        )
    op.drop_constraint(
        op.f("fk_trades_account_id_strategy_instance_id"), "trades", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_risk_decisions_account_id_strategy_instance_id"),
        "risk_decisions",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_risk_decisions_signal_id_strategy_instance_id"),
        "risk_decisions",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("uq_risk_decisions_id_account_id_approved"), "risk_decisions", type_="unique"
    )
    op.drop_constraint(
        op.f("fk_risk_decisions_strategy_instance_id"), "risk_decisions", type_="foreignkey"
    )
    op.drop_column("risk_decisions", "strategy_instance_id")
    op.drop_constraint(op.f("uq_signals_id_strategy_instance_id"), "signals", type_="unique")
    op.drop_constraint(op.f("ck_signals_expires_after_bars"), "signals", type_="check")
    op.drop_column("signals", "expires_after_bars")
    op.drop_column("signals", "reason")
