"""Add immutable fact history and durable ingress receipts.

Revision ID: 0005_fact_history_ingress
Revises: 0004_fact_snapshot
Create Date: 2026-09-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_fact_history_ingress"
down_revision: str | None = "0004_fact_snapshot"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "administrative_fact_snapshot_history",
        sa.Column("snapshot_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "case_id",
            sa.Uuid(),
            sa.ForeignKey("administrative_case.case_id"),
            nullable=False,
        ),
        sa.Column("case_version", sa.Integer(), nullable=False),
        sa.Column("authority_epoch", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=255), nullable=False),
        sa.Column("owner", sa.String(length=255), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("digest", sa.String(length=128), nullable=True),
        sa.Column("facts_json", sa.JSON(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_admin_fact_history_case",
        "administrative_fact_snapshot_history",
        ["case_id", "case_version"],
    )

    op.create_table(
        "administrative_ingress_receipt",
        sa.Column("source_event_id", sa.String(length=512), primary_key=True),
        sa.Column(
            "request_id",
            sa.Uuid(),
            sa.ForeignKey("administrative_request.request_id"),
            nullable=False,
        ),
        sa.Column(
            "case_id",
            sa.Uuid(),
            sa.ForeignKey("administrative_case.case_id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_admin_ingress_receipt_case",
        "administrative_ingress_receipt",
        ["case_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_admin_ingress_receipt_case", table_name="administrative_ingress_receipt")
    op.drop_table("administrative_ingress_receipt")
    op.drop_index("ix_admin_fact_history_case", table_name="administrative_fact_snapshot_history")
    op.drop_table("administrative_fact_snapshot_history")
