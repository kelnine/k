"""Signals may FLATTEN.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-15

A strategy's time exit (``ctx.flatten()``) is a signal of its own: ``FLATTEN`` closes
whatever the instance holds on the symbol, in either direction, and cancels its resting
entry — in the theoretical book and the account alike, also when the book is already
flat (docs/05 §5.3). ``signals.action`` accepts the new value.

Downgrading refuses while a ``FLATTEN`` signal is stored: the old schema cannot hold it.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_ACTIONS = "'LONG', 'SHORT', 'EXIT_LONG', 'EXIT_SHORT', 'MOVE_SL', 'NO_TRADE'"
NEW_ACTIONS = f"{OLD_ACTIONS}, 'FLATTEN'"


def upgrade() -> None:
    op.drop_constraint(op.f("ck_signals_action"), "signals", type_="check")
    op.create_check_constraint(op.f("ck_signals_action"), "signals", f"action IN ({NEW_ACTIONS})")


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM signals WHERE action = 'FLATTEN') THEN "
        "RAISE EXCEPTION 'signals with action FLATTEN exist; revision 0002 cannot store them'; "
        "END IF; END $$"
    )
    op.drop_constraint(op.f("ck_signals_action"), "signals", type_="check")
    op.create_check_constraint(op.f("ck_signals_action"), "signals", f"action IN ({OLD_ACTIONS})")
