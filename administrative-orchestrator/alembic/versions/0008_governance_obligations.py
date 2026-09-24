"""Add governance basis, obligations, effect lineage and policy lifecycle.

Revision ID: 0008_governance_obligations
Revises: 0007_authority_basis
Create Date: 2026-09-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_governance_obligations"
down_revision: str | None = "0007_authority_basis"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "administrative_governance_basis",
        sa.Column("basis_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("case_version_at_basis", sa.Integer(), nullable=False),
        sa.Column("authority_epoch", sa.Integer(), nullable=False),
        sa.Column("fact_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("fact_digest", sa.String(length=128), nullable=False),
        sa.Column("policy_json", sa.JSON(), nullable=False),
        sa.Column("policy_definition_digest", sa.String(length=128), nullable=False),
        sa.Column("organization_scope", sa.String(length=512), nullable=False),
        sa.Column("approval_satisfaction_id", sa.Uuid(), nullable=False),
        sa.Column("qualifications_json", sa.JSON(), nullable=False),
        sa.Column("authority_digest", sa.String(length=128), nullable=False),
        sa.Column("basis_digest", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["administrative_case.case_id"]),
        sa.PrimaryKeyConstraint("basis_id"),
        sa.UniqueConstraint("approval_satisfaction_id"),
    )
    op.create_index(
        "ix_governance_basis_case_epoch",
        "administrative_governance_basis",
        ["case_id", "authority_epoch"],
    )

    op.create_table(
        "administrative_obligation_set",
        sa.Column("requirement_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("authority_epoch", sa.Integer(), nullable=False),
        sa.Column("governance_basis_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["administrative_case.case_id"]),
        sa.PrimaryKeyConstraint("requirement_id"),
    )
    op.create_index(
        "ix_obligation_set_case_epoch",
        "administrative_obligation_set",
        ["case_id", "authority_epoch"],
    )

    op.create_table(
        "administrative_obligation",
        sa.Column("obligation_id", sa.Uuid(), nullable=False),
        sa.Column("requirement_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("authority_epoch", sa.Integer(), nullable=False),
        sa.Column("governance_basis_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=128), nullable=False),
        sa.Column("subject_ref", sa.String(length=512), nullable=False),
        sa.Column("target_system", sa.String(length=255), nullable=False),
        sa.Column("required_operation", sa.String(length=255), nullable=False),
        sa.Column("expected_postcondition_json", sa.JSON(), nullable=False),
        sa.Column("authority_class", sa.String(length=64), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["requirement_id"],
            ["administrative_obligation_set.requirement_id"],
        ),
        sa.ForeignKeyConstraint(["case_id"], ["administrative_case.case_id"]),
        sa.PrimaryKeyConstraint("obligation_id"),
    )
    op.create_index(
        "ix_obligation_case_epoch",
        "administrative_obligation",
        ["case_id", "authority_epoch"],
    )

    op.create_table(
        "administrative_effect_obligation_link",
        sa.Column("effect_id", sa.Uuid(), nullable=False),
        sa.Column("obligation_id", sa.Uuid(), nullable=False),
        sa.Column("governance_basis_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["effect_id"], ["administrative_effect.effect_id"]),
        sa.ForeignKeyConstraint(
            ["obligation_id"],
            ["administrative_obligation.obligation_id"],
        ),
        sa.PrimaryKeyConstraint("effect_id"),
        sa.UniqueConstraint("obligation_id"),
    )

    op.create_table(
        "administrative_policy_lifecycle_event",
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("policy_id", sa.String(length=255), nullable=False),
        sa.Column("version", sa.String(length=128), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("actor_principal_id", sa.String(length=255), nullable=False),
        sa.Column("reason", sa.String(length=1000), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index(
        "ix_policy_lifecycle_policy_time",
        "administrative_policy_lifecycle_event",
        ["policy_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_policy_lifecycle_policy_time",
        table_name="administrative_policy_lifecycle_event",
    )
    op.drop_table("administrative_policy_lifecycle_event")
    op.drop_table("administrative_effect_obligation_link")
    op.drop_index("ix_obligation_case_epoch", table_name="administrative_obligation")
    op.drop_table("administrative_obligation")
    op.drop_index("ix_obligation_set_case_epoch", table_name="administrative_obligation_set")
    op.drop_table("administrative_obligation_set")
    op.drop_index("ix_governance_basis_case_epoch", table_name="administrative_governance_basis")
    op.drop_table("administrative_governance_basis")
