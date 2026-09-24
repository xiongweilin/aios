"""Enforce one frozen obligation graph per case and authority epoch.

Revision ID: 0024_m8_obligation_unique
Revises: 0023_outbox_replay_audit
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0024_m8_obligation_unique"
down_revision: str | None = "0023_outbox_replay_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A unique index works on both PostgreSQL and SQLite, and deliberately
    # fails the migration if historical data already contains a conflict.
    op.create_index(
        "uq_admin_obligation_set_case_epoch",
        "administrative_obligation_set",
        ["case_id", "authority_epoch"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_admin_obligation_set_case_epoch",
        table_name="administrative_obligation_set",
    )
