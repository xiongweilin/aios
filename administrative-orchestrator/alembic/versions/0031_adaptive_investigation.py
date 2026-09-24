"""Persist bounded investigation, reframing, and governed reopen records."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0031_adaptive_investigation"
down_revision: str | None = "0030_m9_communications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "administrative_investigation",
        sa.Column("investigation_id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.String(length=512), nullable=False),
        sa.Column(
            "case_id",
            sa.Uuid(),
            sa.ForeignKey("administrative_case.case_id"),
            nullable=False,
        ),
        sa.Column("authority_epoch", sa.Integer(), nullable=False),
        sa.Column("trigger_type", sa.String(length=128), nullable=False),
        sa.Column("trigger_json", sa.JSON(), nullable=False),
        sa.Column("requested_question", sa.String(length=4000), nullable=False),
        sa.Column("allowed_evidence_refs_json", sa.JSON(), nullable=False),
        sa.Column("current_fact_snapshot_ref", sa.String(length=512), nullable=True),
        sa.Column("current_governance_basis_ref", sa.String(length=512), nullable=True),
        sa.Column("current_obligation_refs_json", sa.JSON(), nullable=False),
        sa.Column("current_commitment_refs_json", sa.JSON(), nullable=False),
        sa.Column("constraints_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=512), nullable=False),
        sa.Column("request_digest", sa.String(length=64), nullable=False),
        sa.Column("rounds_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("model_calls_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "evidence_requests_used", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("last_error_code", sa.String(length=256), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "case_id",
            "idempotency_key",
            name="uq_admin_investigation_case_idempotency",
        ),
    )
    op.create_index(
        "ix_admin_investigation_case_epoch",
        "administrative_investigation",
        ["case_id", "authority_epoch"],
    )
    op.create_index(
        "ix_admin_investigation_status_created",
        "administrative_investigation",
        ["status", "created_at"],
    )

    op.create_table(
        "administrative_investigation_proposal",
        sa.Column("proposal_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "investigation_id",
            sa.Uuid(),
            sa.ForeignKey("administrative_investigation.investigation_id"),
            nullable=False,
        ),
        sa.Column(
            "case_id",
            sa.Uuid(),
            sa.ForeignKey("administrative_case.case_id"),
            nullable=False,
        ),
        sa.Column("authority_epoch", sa.Integer(), nullable=False),
        sa.Column("representation_version", sa.String(length=256), nullable=False),
        sa.Column("hypotheses_json", sa.JSON(), nullable=False),
        sa.Column("ambiguities_json", sa.JSON(), nullable=False),
        sa.Column("missing_evidence_json", sa.JSON(), nullable=False),
        sa.Column("recommended_queries_json", sa.JSON(), nullable=False),
        sa.Column("recommended_human_questions_json", sa.JSON(), nullable=False),
        sa.Column("possible_reframings_json", sa.JSON(), nullable=False),
        sa.Column("possible_reopen_targets_json", sa.JSON(), nullable=False),
        sa.Column("uncertainty_json", sa.JSON(), nullable=False),
        sa.Column("model_provenance_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=512), nullable=False),
        sa.Column("proposal_digest", sa.String(length=64), nullable=False),
        sa.UniqueConstraint(
            "investigation_id",
            "idempotency_key",
            name="uq_admin_investigation_proposal_idempotency",
        ),
    )
    op.create_index(
        "ix_admin_investigation_proposal_case_epoch",
        "administrative_investigation_proposal",
        ["case_id", "authority_epoch"],
    )

    op.create_table(
        "administrative_reframing_proposal",
        sa.Column("reframing_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "investigation_id",
            sa.Uuid(),
            sa.ForeignKey("administrative_investigation.investigation_id"),
            nullable=False,
        ),
        sa.Column(
            "proposal_id",
            sa.Uuid(),
            sa.ForeignKey("administrative_investigation_proposal.proposal_id"),
            nullable=False,
        ),
        sa.Column(
            "case_id",
            sa.Uuid(),
            sa.ForeignKey("administrative_case.case_id"),
            nullable=False,
        ),
        sa.Column("current_frame", sa.String(length=2000), nullable=False),
        sa.Column("proposed_frame", sa.String(length=2000), nullable=False),
        sa.Column("reason", sa.String(length=4000), nullable=False),
        sa.Column("evidence_refs_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "administrative_investigation_evidence_request",
        sa.Column("evidence_request_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "investigation_id",
            sa.Uuid(),
            sa.ForeignKey("administrative_investigation.investigation_id"),
            nullable=False,
        ),
        sa.Column(
            "case_id",
            sa.Uuid(),
            sa.ForeignKey("administrative_case.case_id"),
            nullable=False,
        ),
        sa.Column("authority_epoch", sa.Integer(), nullable=False),
        sa.Column("source_kind", sa.String(length=128), nullable=False),
        sa.Column("requested_question", sa.String(length=4000), nullable=False),
        sa.Column("allowed_evidence_refs_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("evidence_refs_json", sa.JSON(), nullable=False),
        sa.Column("requested_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fulfilled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.String(length=512), nullable=False),
        sa.UniqueConstraint(
            "investigation_id",
            "idempotency_key",
            name="uq_admin_investigation_evidence_request_idempotency",
        ),
    )
    op.create_index(
        "ix_admin_investigation_evidence_request_case_epoch",
        "administrative_investigation_evidence_request",
        ["case_id", "authority_epoch"],
    )

    op.create_table(
        "administrative_investigation_evidence",
        sa.Column("evidence_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "investigation_id",
            sa.Uuid(),
            sa.ForeignKey("administrative_investigation.investigation_id"),
            nullable=False,
        ),
        sa.Column(
            "case_id",
            sa.Uuid(),
            sa.ForeignKey("administrative_case.case_id"),
            nullable=False,
        ),
        sa.Column("authority_epoch", sa.Integer(), nullable=False),
        sa.Column(
            "evidence_request_id",
            sa.Uuid(),
            sa.ForeignKey("administrative_investigation_evidence_request.evidence_request_id"),
            nullable=True,
        ),
        sa.Column("evidence_ref", sa.String(length=1000), nullable=False),
        sa.Column("source_kind", sa.String(length=128), nullable=False),
        sa.Column("source", sa.String(length=512), nullable=False),
        sa.Column("owner", sa.String(length=255), nullable=False),
        sa.Column("source_ref", sa.String(length=1000), nullable=True),
        sa.Column("source_version", sa.String(length=256), nullable=True),
        sa.Column("digest", sa.String(length=128), nullable=True),
        sa.Column("added_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=512), nullable=False),
        sa.UniqueConstraint(
            "investigation_id",
            "idempotency_key",
            name="uq_admin_investigation_evidence_idempotency",
        ),
    )

    op.create_table(
        "administrative_reopen_assessment",
        sa.Column("assessment_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "investigation_id",
            sa.Uuid(),
            sa.ForeignKey("administrative_investigation.investigation_id"),
            nullable=False,
        ),
        sa.Column(
            "case_id",
            sa.Uuid(),
            sa.ForeignKey("administrative_case.case_id"),
            nullable=False,
        ),
        sa.Column("authority_epoch", sa.Integer(), nullable=False),
        sa.Column("disposition", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.String(length=4000), nullable=False),
        sa.Column("evidence_refs_json", sa.JSON(), nullable=False),
        sa.Column("proposal_ref", sa.Uuid(), nullable=True),
        sa.Column("assessment_kind", sa.String(length=64), nullable=False),
        sa.Column("assessed_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=512), nullable=False),
        sa.Column("assessment_digest", sa.String(length=64), nullable=False),
        sa.UniqueConstraint(
            "investigation_id",
            "idempotency_key",
            name="uq_admin_reopen_assessment_idempotency",
        ),
    )
    op.create_index(
        "ix_admin_reopen_assessment_case_epoch",
        "administrative_reopen_assessment",
        ["case_id", "authority_epoch"],
    )

    op.create_table(
        "administrative_reopen_record",
        sa.Column("reopen_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "investigation_id",
            sa.Uuid(),
            sa.ForeignKey("administrative_investigation.investigation_id"),
            nullable=False,
        ),
        sa.Column(
            "case_id",
            sa.Uuid(),
            sa.ForeignKey("administrative_case.case_id"),
            nullable=False,
        ),
        sa.Column(
            "assessment_ref",
            sa.Uuid(),
            sa.ForeignKey("administrative_reopen_assessment.assessment_id"),
            nullable=False,
        ),
        sa.Column("previous_authority_epoch", sa.Integer(), nullable=False),
        sa.Column("new_authority_epoch", sa.Integer(), nullable=False),
        sa.Column("reopen_reason", sa.String(length=4000), nullable=False),
        sa.Column("evidence_refs_json", sa.JSON(), nullable=False),
        sa.Column("authorized_by", sa.String(length=255), nullable=False),
        sa.Column("invalidated_decision_refs_json", sa.JSON(), nullable=False),
        sa.Column("invalidated_governance_basis_refs_json", sa.JSON(), nullable=False),
        sa.Column("affected_obligation_refs_json", sa.JSON(), nullable=False),
        sa.Column("affected_execution_authorization_refs_json", sa.JSON(), nullable=False),
        sa.Column("affected_commitment_refs_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=512), nullable=False),
        sa.UniqueConstraint(
            "case_id",
            "idempotency_key",
            name="uq_admin_reopen_record_idempotency",
        ),
        sa.UniqueConstraint("assessment_ref", name="uq_admin_reopen_record_assessment"),
    )
    op.create_index(
        "ix_admin_reopen_record_case_epoch",
        "administrative_reopen_record",
        ["case_id", "previous_authority_epoch"],
    )


def downgrade() -> None:
    op.drop_index("ix_admin_reopen_record_case_epoch", table_name="administrative_reopen_record")
    op.drop_table("administrative_reopen_record")
    op.drop_index(
        "ix_admin_reopen_assessment_case_epoch",
        table_name="administrative_reopen_assessment",
    )
    op.drop_table("administrative_reopen_assessment")
    op.drop_table("administrative_investigation_evidence")
    op.drop_index(
        "ix_admin_investigation_evidence_request_case_epoch",
        table_name="administrative_investigation_evidence_request",
    )
    op.drop_table("administrative_investigation_evidence_request")
    op.drop_table("administrative_reframing_proposal")
    op.drop_index(
        "ix_admin_investigation_proposal_case_epoch",
        table_name="administrative_investigation_proposal",
    )
    op.drop_table("administrative_investigation_proposal")
    op.drop_index(
        "ix_admin_investigation_status_created",
        table_name="administrative_investigation",
    )
    op.drop_index(
        "ix_admin_investigation_case_epoch",
        table_name="administrative_investigation",
    )
    op.drop_table("administrative_investigation")
