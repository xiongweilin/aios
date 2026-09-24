"""Add the M6 durable Intake Core objects.

Revision ID: 0015_m6_intake_core
Revises: 0014_authority_lifecycle
Create Date: 2026-09-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_m6_intake_core"
down_revision: str | None = "0014_authority_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "administrative_source_artifact",
        sa.Column("artifact_id", sa.Uuid(), primary_key=True),
        sa.Column("source_kind", sa.String(length=128), nullable=False),
        sa.Column("source_system", sa.String(length=128), nullable=False),
        sa.Column("tenant_ref", sa.String(length=512), nullable=False),
        sa.Column("canonical_source_ref", sa.String(length=1000), nullable=False),
        sa.Column("source_revision", sa.String(length=256), nullable=False),
        sa.Column("source_event_ref", sa.String(length=512), nullable=False),
        sa.Column("actor_external_identity_ref", sa.String(length=1000), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content_digest", sa.String(length=128), nullable=False),
        sa.Column("storage_ref", sa.String(length=2000), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=True),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("authenticity_class", sa.String(length=128), nullable=False),
        sa.Column("retention_class", sa.String(length=128), nullable=False),
        sa.UniqueConstraint(
            "source_system",
            "tenant_ref",
            "canonical_source_ref",
            "source_revision",
            name="uq_source_artifact_revision",
        ),
    )
    op.create_index(
        "ix_source_artifact_canonical_ref",
        "administrative_source_artifact",
        ["source_system", "tenant_ref", "canonical_source_ref"],
    )

    op.create_table(
        "administrative_intake_receipt",
        sa.Column("receipt_id", sa.Uuid(), primary_key=True),
        sa.Column("source_system", sa.String(length=128), nullable=False),
        sa.Column("tenant_ref", sa.String(length=512), nullable=False),
        sa.Column("source_event_id", sa.String(length=512), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verification_status", sa.String(length=32), nullable=False),
        sa.Column(
            "artifact_ref",
            sa.Uuid(),
            sa.ForeignKey("administrative_source_artifact.artifact_id"),
            nullable=True,
        ),
        sa.Column("delivery_digest", sa.String(length=128), nullable=False),
        sa.UniqueConstraint(
            "source_system",
            "tenant_ref",
            "source_event_id",
            name="uq_intake_receipt_delivery",
        ),
    )
    op.create_index(
        "ix_intake_receipt_event",
        "administrative_intake_receipt",
        ["source_system", "tenant_ref", "source_event_id"],
    )

    op.create_table(
        "administrative_evidence_span",
        sa.Column("evidence_span_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "artifact_ref",
            sa.Uuid(),
            sa.ForeignKey("administrative_source_artifact.artifact_id"),
            nullable=False,
        ),
        sa.Column("representation_digest", sa.String(length=128), nullable=False),
        sa.Column("locator_kind", sa.String(length=128), nullable=False),
        sa.Column("locator_json", sa.JSON(), nullable=False),
        sa.Column("locator_digest", sa.String(length=64), nullable=False),
        sa.Column("extractor_ref", sa.String(length=512), nullable=False),
        sa.UniqueConstraint(
            "artifact_ref",
            "representation_digest",
            "locator_digest",
            "extractor_ref",
            name="uq_evidence_span_identity",
        ),
    )

    op.create_table(
        "administrative_interpretation_record",
        sa.Column("interpretation_id", sa.Uuid(), primary_key=True),
        sa.Column("artifact_refs_json", sa.JSON(), nullable=False),
        sa.Column("interpretation_profile_ref", sa.String(length=512), nullable=False),
        sa.Column("model_provider", sa.String(length=128), nullable=False),
        sa.Column("model_identity", sa.String(length=512), nullable=False),
        sa.Column("model_version", sa.String(length=256), nullable=False),
        sa.Column("schema_ref", sa.String(length=512), nullable=False),
        sa.Column("interpreted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("structured_output_json", sa.JSON(), nullable=False),
        sa.Column("evidence_span_refs_json", sa.JSON(), nullable=False),
        sa.Column("response_digest", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
    )
    op.create_index(
        "ix_interpretation_profile_time",
        "administrative_interpretation_record",
        ["interpretation_profile_ref", "interpreted_at"],
    )

    op.create_table(
        "administrative_candidate_fact_assertion",
        sa.Column("candidate_fact_id", sa.Uuid(), primary_key=True),
        sa.Column("fact_key", sa.String(length=512), nullable=False),
        sa.Column("value_json", sa.JSON(), nullable=False),
        sa.Column("authority", sa.String(length=32), nullable=False),
        sa.Column("interpretation_ref", sa.Uuid(), nullable=True),
        sa.Column("source_refs_json", sa.JSON(), nullable=False),
        sa.Column("evidence_span_refs_json", sa.JSON(), nullable=False),
        sa.Column("no_evidence_reason", sa.String(length=2000), nullable=True),
        sa.Column("extractor_ref", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "authority IN ('claim', 'attested_candidate')",
            name="ck_candidate_fact_authority",
        ),
    )

    op.create_table(
        "administrative_candidate_request",
        sa.Column("candidate_id", sa.Uuid(), primary_key=True),
        sa.Column("conversation_ref", sa.String(length=1000), nullable=False),
        sa.Column("interpretation_refs_json", sa.JSON(), nullable=False),
        sa.Column("candidate_requester", sa.String(length=1000), nullable=False),
        sa.Column("candidate_intent", sa.String(length=2000), nullable=False),
        sa.Column("candidate_fact_refs_json", sa.JSON(), nullable=False),
        sa.Column("source_refs_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("supersedes_candidate_ref", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
    )
    op.create_index(
        "ix_candidate_request_conversation",
        "administrative_candidate_request",
        ["conversation_ref", "created_at"],
    )

    op.create_table(
        "administrative_candidate_case_update",
        sa.Column("candidate_update_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "case_id",
            sa.Uuid(),
            sa.ForeignKey("administrative_case.case_id"),
            nullable=False,
        ),
        sa.Column("conversation_ref", sa.String(length=1000), nullable=False),
        sa.Column("interpretation_refs_json", sa.JSON(), nullable=False),
        sa.Column("candidate_fact_refs_json", sa.JSON(), nullable=False),
        sa.Column("source_refs_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
    )
    op.create_index(
        "ix_candidate_case_update_case",
        "administrative_candidate_case_update",
        ["case_id", "created_at"],
    )

    op.create_table(
        "administrative_intake_assessment",
        sa.Column("assessment_id", sa.Uuid(), primary_key=True),
        sa.Column("candidate_ref", sa.Uuid(), nullable=False),
        sa.Column("disposition", sa.String(length=64), nullable=False),
        sa.Column("basis_json", sa.JSON(), nullable=False),
        sa.Column("authority", sa.String(length=64), nullable=False),
        sa.Column("is_final", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reviewer_principal_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "NOT (is_final AND authority = 'model_suggestion')",
            name="ck_final_assessment_not_model",
        ),
    )
    op.create_index(
        "ix_intake_assessment_candidate_time",
        "administrative_intake_assessment",
        ["candidate_ref", "created_at"],
    )

    op.create_table(
        "administrative_promotion_record",
        sa.Column("promotion_id", sa.Uuid(), primary_key=True),
        sa.Column("candidate_ref", sa.Uuid(), nullable=False),
        sa.Column("assessment_ref", sa.Uuid(), nullable=False),
        sa.Column(
            "request_id",
            sa.Uuid(),
            sa.ForeignKey("administrative_request.request_id"),
            nullable=False,
        ),
        sa.Column("ingress_receipt_ref", sa.String(length=1000), nullable=False),
        sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("promotion_policy_ref", sa.String(length=512), nullable=False),
        sa.UniqueConstraint("candidate_ref", name="uq_promotion_candidate"),
        sa.UniqueConstraint("request_id", name="uq_promotion_request"),
    )
    op.create_index(
        "ix_promotion_candidate_time",
        "administrative_promotion_record",
        ["candidate_ref", "promoted_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_promotion_candidate_time",
        table_name="administrative_promotion_record",
    )
    op.drop_table("administrative_promotion_record")
    op.drop_index(
        "ix_intake_assessment_candidate_time",
        table_name="administrative_intake_assessment",
    )
    op.drop_table("administrative_intake_assessment")
    op.drop_index(
        "ix_candidate_case_update_case",
        table_name="administrative_candidate_case_update",
    )
    op.drop_table("administrative_candidate_case_update")
    op.drop_index(
        "ix_candidate_request_conversation",
        table_name="administrative_candidate_request",
    )
    op.drop_table("administrative_candidate_request")
    op.drop_table("administrative_candidate_fact_assertion")
    op.drop_index(
        "ix_interpretation_profile_time",
        table_name="administrative_interpretation_record",
    )
    op.drop_table("administrative_interpretation_record")
    op.drop_table("administrative_evidence_span")
    op.drop_index("ix_intake_receipt_event", table_name="administrative_intake_receipt")
    op.drop_table("administrative_intake_receipt")
    op.drop_index(
        "ix_source_artifact_canonical_ref",
        table_name="administrative_source_artifact",
    )
    op.drop_table("administrative_source_artifact")
