"""Persist the current fact snapshot on AdministrativeCase.

Revision ID: 0004_fact_snapshot
Revises: 0003_transactional_outbox
Create Date: 2026-09-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_fact_snapshot"
down_revision: str | None = "0003_transactional_outbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "administrative_case",
        sa.Column("fact_snapshot_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("administrative_case", "fact_snapshot_json")
