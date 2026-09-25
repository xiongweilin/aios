"""Add administrative grants, effect intents, and Kernel shadow projections.

Revision ID: 0009_kernel_bridge
Revises: 0008_governance_obligations
Create Date: 2026-09-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_kernel_bridge"
down_revision: str | None = "0008_governance_obligations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "administrative_execution_grant",
        sa.Column("grant_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("authority_epoch", sa.Integer(), nullable=False),
        sa.Column("obligation_id", sa.Uuid(), nullable=False),
        sa.Column("governance_basis_id", sa.Uuid(), nullable=False),
        sa.Column("approval_satisfaction_id", sa.Uuid(), nullable=False),
        sa.Column("policy_json", sa.JSON(), nullable=False),
        sa.Column("subject_ref", sa.String(length=512), nullable=False),
        sa.Column("target_system", sa.String(length=255), nullable=False),
        sa.Column("operation", sa.String(length=255), nullable=False),
        sa.Column("authority_class", sa.String(length=64), nullable=False),
        sa.Column("expected_postcondition_json", sa.JSON(), nullable=False),
        sa.Column("issued_by", sa.String(length=255), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["administrative_case.case_id"]),
        sa.ForeignKeyConstraint(
            ["obligation_id"], ["administrative_obligation.obligation_id"]
        ),
        sa.ForeignKeyConstraint(
            ["governance_basis_id"], ["administrative_governance_basis.basis_id"]
        ),
        sa.PrimaryKeyConstraint("grant_id"),
        sa.UniqueConstraint("obligation_id"),
    )
    op.create_index(
        "ix_execution_grant_case_epoch",
        "administrative_execution_grant",
        ["case_id", "authority_epoch"],
    )

    op.create_table(
        "administrative_effect_intent",
        sa.Column("intent_id", sa.Uuid(), nullable=False),
        sa.Column("grant_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("authority_epoch", sa.Integer(), nullable=False),
        sa.Column("obligation_id", sa.Uuid(), nullable=False),
        sa.Column("capability", sa.String(length=512), nullable=False),
        sa.Column("subject_ref", sa.String(length=512), nullable=False),
        sa.Column("parameters_json", sa.JSON(), nullable=False),
        sa.Column("expected_postcondition_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["grant_id"], ["administrative_execution_grant.grant_id"]
        ),
        sa.ForeignKeyConstraint(["case_id"], ["administrative_case.case_id"]),
        sa.ForeignKeyConstraint(
            ["obligation_id"], ["administrative_obligation.obligation_id"]
        ),
        sa.PrimaryKeyConstraint("intent_id"),
        sa.UniqueConstraint("grant_id"),
        sa.UniqueConstraint("obligation_id"),
    )
    op.create_index(
        "ix_effect_intent_case_epoch",
        "administrative_effect_intent",
        ["case_id", "authority_epoch"],
    )

    op.create_table(
        "administrative_kernel_bridge_projection",
        sa.Column("projection_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("authority_epoch", sa.Integer(), nullable=False),
        sa.Column("grant_id", sa.Uuid(), nullable=False),
        sa.Column("intent_id", sa.Uuid(), nullable=False),
        sa.Column("obligation_id", sa.Uuid(), nullable=False),
        sa.Column("contract_catalog", sa.String(length=255), nullable=False),
        sa.Column("runtime_protocol", sa.String(length=64), nullable=False),
        sa.Column("persistent_responsibility_contract", sa.String(length=255), nullable=False),
        sa.Column("responsibility_json", sa.JSON(), nullable=False),
        sa.Column("admission_json", sa.JSON(), nullable=False),
        sa.Column("assessment_json", sa.JSON(), nullable=False),
        sa.Column("work_proposal_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("kernel_responsibility_ref", sa.String(length=512), nullable=True),
        sa.Column("kernel_proposal_ref", sa.String(length=512), nullable=True),
        sa.Column("kernel_work_ref", sa.String(length=512), nullable=True),
        sa.Column("kernel_run_ref", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["administrative_case.case_id"]),
        sa.ForeignKeyConstraint(
            ["grant_id"], ["administrative_execution_grant.grant_id"]
        ),
        sa.ForeignKeyConstraint(
            ["intent_id"], ["administrative_effect_intent.intent_id"]
        ),
        sa.ForeignKeyConstraint(
            ["obligation_id"], ["administrative_obligation.obligation_id"]
        ),
        sa.PrimaryKeyConstraint("projection_id"),
        sa.UniqueConstraint("grant_id"),
        sa.UniqueConstraint("intent_id"),
        sa.UniqueConstraint("obligation_id"),
    )
    op.create_index(
        "ix_kernel_projection_case_epoch",
        "administrative_kernel_bridge_projection",
        ["case_id", "authority_epoch"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_kernel_projection_case_epoch",
        table_name="administrative_kernel_bridge_projection",
    )
    op.drop_table("administrative_kernel_bridge_projection")
    op.drop_index("ix_effect_intent_case_epoch", table_name="administrative_effect_intent")
    op.drop_table("administrative_effect_intent")
    op.drop_index("ix_execution_grant_case_epoch", table_name="administrative_execution_grant")
    op.drop_table("administrative_execution_grant")
