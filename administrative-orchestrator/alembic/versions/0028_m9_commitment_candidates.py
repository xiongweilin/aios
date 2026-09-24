"""Persist M9 meeting commitment candidates and speaker qualification."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0028_m9_commitment_candidates"
down_revision: str | None = "0027_m8_current_qualification"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "administrative_candidate_commitment",
        sa.Column("candidate_commitment_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "source_artifact_ref",
            sa.Uuid(),
            sa.ForeignKey("administrative_source_artifact.artifact_id"),
            nullable=False,
        ),
        sa.Column(
            "interpretation_ref",
            sa.Uuid(),
            sa.ForeignKey("administrative_interpretation_record.interpretation_id"),
            nullable=False,
        ),
        sa.Column("evidence_span_refs_json", sa.JSON(), nullable=False),
        sa.Column("candidate_committer_identity", sa.String(512), nullable=False),
        sa.Column("candidate_action", sa.String(2000), nullable=False),
        sa.Column("candidate_due_text", sa.String(512), nullable=True),
        sa.Column("candidate_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("candidate_scope_ref", sa.String(1000), nullable=True),
        sa.Column("candidate_beneficiary", sa.String(1000), nullable=True),
        sa.Column("classification", sa.String(64), nullable=False),
        sa.Column("status", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("superseded_by", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "ix_admin_candidate_commitment_status_created",
        "administrative_candidate_commitment",
        ["status", "created_at"],
    )
    op.create_table(
        "administrative_speaker_principal_resolution",
        sa.Column("resolution_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "candidate_ref",
            sa.Uuid(),
            sa.ForeignKey("administrative_candidate_commitment.candidate_commitment_id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("source_speaker_identity", sa.String(512), nullable=False),
        sa.Column("resolved_principal_id", sa.String(255), nullable=False),
        sa.Column("provider", sa.String(128), nullable=False),
        sa.Column("external_subject", sa.String(1000), nullable=False),
        sa.Column("basis_json", sa.JSON(), nullable=False),
        sa.Column("resolver_type", sa.String(128), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("administrative_speaker_principal_resolution")
    op.drop_index(
        "ix_admin_candidate_commitment_status_created",
        table_name="administrative_candidate_commitment",
    )
    op.drop_table("administrative_candidate_commitment")
