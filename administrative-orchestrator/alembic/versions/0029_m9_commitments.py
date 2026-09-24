"""Persist qualified M9 commitment responsibility and fulfillment attestations."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0029_m9_commitments"
down_revision: str | None = "0028_m9_commitment_candidates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "administrative_commitment",
        sa.Column("commitment_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "candidate_ref",
            sa.Uuid(),
            sa.ForeignKey("administrative_candidate_commitment.candidate_commitment_id"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "case_id",
            sa.Uuid(),
            sa.ForeignKey("administrative_case.case_id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("authority_epoch", sa.Integer(), nullable=False),
        sa.Column("committer_principal_id", sa.String(255), nullable=False),
        sa.Column("committer_external_subject", sa.String(1000), nullable=False),
        sa.Column("commitment_action", sa.String(2000), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("due_time_basis", sa.String(512), nullable=False),
        sa.Column("scope_ref", sa.String(1000), nullable=True),
        sa.Column("beneficiary_principal_id", sa.String(255), nullable=True),
        sa.Column("fulfillment_kind", sa.String(64), nullable=False),
        sa.Column("state", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("responsibility_ref", sa.String(512), nullable=True),
        sa.Column("responsibility_version", sa.Integer(), nullable=True),
        sa.Column("responsibility_admission_ref", sa.String(512), nullable=True),
        sa.Column("responsibility_assessment_ref", sa.String(512), nullable=True),
        sa.Column("responsibility_proposal_ref", sa.String(512), nullable=True),
        sa.Column("responsibility_discharge_assessment_ref", sa.String(512), nullable=True),
        sa.Column("responsibility_discharge_decision_ref", sa.String(512), nullable=True),
        sa.Column("responsibility_transition_ref", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("was_overdue", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index(
        "ix_admin_commitment_state_due",
        "administrative_commitment",
        ["state", "due_at"],
    )
    op.create_table(
        "administrative_commitment_fulfillment_attestation",
        sa.Column("attestation_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "case_id",
            sa.Uuid(),
            sa.ForeignKey("administrative_case.case_id"),
            nullable=False,
        ),
        sa.Column("authority_epoch", sa.Integer(), nullable=False),
        sa.Column("commitment_version", sa.Integer(), nullable=False),
        sa.Column("principal_id", sa.String(255), nullable=False),
        sa.Column("disposition", sa.String(64), nullable=False),
        sa.Column("basis_json", sa.JSON(), nullable=False),
        sa.Column("attested_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "case_id",
            "commitment_version",
            name="uq_admin_commitment_attestation_version",
        ),
    )


def downgrade() -> None:
    op.drop_table("administrative_commitment_fulfillment_attestation")
    op.drop_index("ix_admin_commitment_state_due", table_name="administrative_commitment")
    op.drop_table("administrative_commitment")
