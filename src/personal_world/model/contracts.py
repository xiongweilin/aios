from __future__ import annotations

from datetime import UTC, datetime
from enum import IntEnum, StrEnum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from semantic_language import SemanticRef


def utc_now() -> datetime:
    return datetime.now(UTC)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceClass(StrEnum):
    HUMAN_EXPLICIT = "human-explicit"
    DOMAIN_CONTROLLER = "domain-controller"
    EXTERNAL_RECORD = "external-record"
    IMPORT = "import"
    MODEL_INFERENCE = "model-inference"
    DERIVED = "derived"


class QualificationStatus(StrEnum):
    CANDIDATE = "candidate"
    CURRENT = "current"
    CONTESTED = "contested"
    REVALIDATION_REQUIRED = "revalidation-required"
    SUPERSEDED = "superseded"
    RETRACTED = "retracted"


class RecordKind(StrEnum):
    FACT = "fact"
    PREFERENCE = "preference"
    RELATIONSHIP = "relationship"
    RESOURCE_LINK = "resource-link"


class SensitivityClass(IntEnum):
    PUBLIC = 0
    PERSONAL = 10
    SENSITIVE = 20
    HIGHLY_SENSITIVE = 30


class PreferenceOrigin(StrEnum):
    EXPLICIT = "explicit"
    ACCEPTED_INFERENCE = "accepted-inference"
    UNACCEPTED_INFERENCE = "unaccepted-inference"
    IMPORTED = "imported"


class TemporalScope(StrictModel):
    observed_at: datetime | None = None
    recorded_at: datetime = Field(default_factory=utc_now)
    valid_from: datetime | None = None
    valid_until: datetime | None = None

    @model_validator(mode="after")
    def validate_window(self) -> TemporalScope:
        if self.valid_from and self.valid_until and self.valid_until <= self.valid_from:
            raise ValueError("valid_until must be after valid_from")
        return self


class SourceDescriptorCreate(StrictModel):
    source_class: SourceClass
    external_ref: str | None = None
    actor_ref: str | None = None
    description: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourceDescriptor(SourceDescriptorCreate):
    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=utc_now)


class ObservationCreate(StrictModel):
    subject_id: UUID
    source_id: UUID
    semantic: SemanticRef
    value: Any
    temporal: TemporalScope = Field(default_factory=TemporalScope)
    sensitivity: SensitivityClass = SensitivityClass.PERSONAL
    metadata: dict[str, Any] = Field(default_factory=dict)


class Observation(ObservationCreate):
    id: UUID = Field(default_factory=uuid4)


class ClaimCreate(StrictModel):
    subject_id: UUID
    source_id: UUID
    semantic: SemanticRef
    value: Any
    observation_refs: tuple[UUID, ...] = ()
    temporal: TemporalScope = Field(default_factory=TemporalScope)
    confidence: float | None = Field(default=None, ge=0, le=1)
    sensitivity: SensitivityClass = SensitivityClass.PERSONAL
    metadata: dict[str, Any] = Field(default_factory=dict)


class Claim(ClaimCreate):
    id: UUID = Field(default_factory=uuid4)


class RecordCreateBase(StrictModel):
    subject_id: UUID
    semantic: SemanticRef
    value: Any
    source_refs: tuple[UUID, ...] = Field(min_length=1)
    claim_refs: tuple[UUID, ...] = ()
    temporal: TemporalScope = Field(default_factory=TemporalScope)
    sensitivity: SensitivityClass = SensitivityClass.PERSONAL
    context: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    admit_current: bool = True


class PersonalFactCreate(RecordCreateBase):
    pass


class PreferenceCreate(RecordCreateBase):
    origin: PreferenceOrigin
    strength: float | None = Field(default=None, ge=0, le=1)


class RelationshipCreate(RecordCreateBase):
    target_ref: str = Field(min_length=1)
    relation_namespace: str = Field(min_length=1)


class ResourceLinkCreate(RecordCreateBase):
    resource_ref: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    relation: str = Field(min_length=1)
    credential_ref: str | None = None


class PersonalRecord(StrictModel):
    id: UUID
    lineage_id: UUID
    revision: int = Field(ge=1)
    kind: RecordKind
    subject_id: UUID
    semantic: SemanticRef
    value: Any
    source_refs: tuple[UUID, ...]
    claim_refs: tuple[UUID, ...]
    temporal: TemporalScope
    sensitivity: SensitivityClass
    status: QualificationStatus
    context: dict[str, Any]
    metadata: dict[str, Any]
    supersedes_id: UUID | None = None
    preference_origin: PreferenceOrigin | None = None
    strength: float | None = None
    target_ref: str | None = None
    relation_namespace: str | None = None
    resource_ref: str | None = None
    domain: str | None = None
    relation: str | None = None
    credential_ref: str | None = None
    qualified_at: datetime | None = None
    qualification_reason: str | None = None
    deleted_at: datetime | None = None


class RevisionRequest(StrictModel):
    expected_revision: int = Field(ge=1)
    value: Any
    source_refs: tuple[UUID, ...] = Field(min_length=1)
    claim_refs: tuple[UUID, ...] = ()
    temporal: TemporalScope = Field(default_factory=TemporalScope)
    sensitivity: SensitivityClass | None = None
    context: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    qualification_reason: str = "revision"


class RevalidationRequest(StrictModel):
    expected_revision: int = Field(ge=1)
    status: Literal[
        QualificationStatus.CURRENT,
        QualificationStatus.CONTESTED,
        QualificationStatus.REVALIDATION_REQUIRED,
        QualificationStatus.RETRACTED,
    ]
    reason: str = Field(min_length=1)


class ContextProjectionRequest(StrictModel):
    subject_id: UUID
    purpose: str = Field(min_length=1)
    scope: str | None = None
    requested_kinds: tuple[RecordKind, ...] = (
        RecordKind.FACT,
        RecordKind.PREFERENCE,
        RecordKind.RELATIONSHIP,
        RecordKind.RESOURCE_LINK,
    )
    query: str | None = None
    limit: int = Field(default=50, ge=1, le=500)
    as_of: datetime | None = None


class ContextProjection(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    subject_id: UUID
    purpose: str
    scope: str | None
    generated_at: datetime = Field(default_factory=utc_now)
    included_items: tuple[PersonalRecord, ...]
    contested_items: tuple[PersonalRecord, ...]
    stale_items: tuple[PersonalRecord, ...]
    excluded_count: int
    source_refs: tuple[UUID, ...]


class SearchRequest(StrictModel):
    subject_id: UUID
    purpose: str
    query: str = Field(min_length=1)
    kinds: tuple[RecordKind, ...] = (
        RecordKind.FACT,
        RecordKind.PREFERENCE,
        RecordKind.RELATIONSHIP,
        RecordKind.RESOURCE_LINK,
    )
    limit: int = Field(default=20, ge=1, le=100)


class SearchHit(StrictModel):
    record: PersonalRecord
    lexical_score: float
    semantic_score: float
    score: float


class ModelContextBundle(StrictModel):
    purpose: str
    query: str | None
    projection_ref: UUID
    included_items: tuple[PersonalRecord, ...]
    unresolved_conflicts: tuple[PersonalRecord, ...]
    stale_items: tuple[PersonalRecord, ...]
    unknowns: tuple[str, ...] = ()
    excluded_count: int
    source_refs: tuple[UUID, ...]


class DataAccessProfile(StrictModel):
    service_identity: str
    allowed_purposes: tuple[str, ...]
    allowed_kinds: tuple[RecordKind, ...]
    max_sensitivity: SensitivityClass

    def allows_purpose(self, purpose: str) -> bool:
        return "*" in self.allowed_purposes or purpose in self.allowed_purposes


class RedactionRequest(StrictModel):
    object_type: Literal["source", "observation", "claim", "record"]
    object_id: UUID
    reason: str = Field(min_length=1)


class ErasureRequest(StrictModel):
    subject_id: UUID
    reason: str = Field(min_length=1)
    kinds: tuple[RecordKind, ...] | None = None


class ErasureResult(StrictModel):
    subject_id: UUID
    redacted_sources: int
    redacted_observations: int
    redacted_claims: int
    redacted_records: int
    completed_at: datetime = Field(default_factory=utc_now)


class DomainClaim(StrictModel):
    record_kind: RecordKind = RecordKind.FACT
    semantic: SemanticRef
    value: Any
    sensitivity: SensitivityClass = SensitivityClass.PERSONAL
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    preference_origin: PreferenceOrigin | None = None
    strength: float | None = Field(default=None, ge=0, le=1)
    target_ref: str | None = None
    relation_namespace: str | None = None
    resource_ref: str | None = None
    domain: str | None = None
    relation: str | None = None
    credential_ref: str | None = None

    @model_validator(mode="after")
    def validate_record_shape(self) -> DomainClaim:
        if self.record_kind == RecordKind.PREFERENCE:
            if self.preference_origin is None:
                raise ValueError("preference domain claim requires preference_origin")
        elif self.preference_origin is not None or self.strength is not None:
            raise ValueError("preference fields require record_kind=preference")

        if self.record_kind == RecordKind.RELATIONSHIP:
            if not self.target_ref or not self.relation_namespace:
                raise ValueError(
                    "relationship domain claim requires target_ref and relation_namespace"
                )
        elif self.target_ref is not None or self.relation_namespace is not None:
            raise ValueError("relationship fields require record_kind=relationship")

        if self.record_kind == RecordKind.RESOURCE_LINK:
            if not self.resource_ref or not self.domain or not self.relation:
                raise ValueError(
                    "resource-link domain claim requires resource_ref, domain and relation"
                )
        elif any(
            value is not None
            for value in (self.resource_ref, self.domain, self.relation, self.credential_ref)
        ):
            raise ValueError("resource-link fields require record_kind=resource-link")

        return self


class DomainPersonalProjection(StrictModel):
    subject_id: UUID
    source_domain: str = Field(min_length=1)
    source_object_ref: str = Field(min_length=1)
    source_version: str | None = None
    observed_at: datetime = Field(default_factory=utc_now)
    claims: tuple[DomainClaim, ...] = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DisclosureAudit(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    service_identity: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    subject_id: UUID
    action: Literal["current", "history", "projection", "search"]
    record_refs: tuple[UUID, ...] = ()
    excluded_count: int = Field(default=0, ge=0)
    occurred_at: datetime = Field(default_factory=utc_now)


class PersonalWorldBundle(StrictModel):
    contract: Literal["personal-world-bundle-v1"] = "personal-world-bundle-v1"
    exported_at: datetime = Field(default_factory=utc_now)
    sources: tuple[dict[str, Any], ...]
    observations: tuple[dict[str, Any], ...]
    claims: tuple[dict[str, Any], ...]
    records: tuple[dict[str, Any], ...]
    access_profiles: tuple[dict[str, Any], ...]
    disclosures: tuple[dict[str, Any], ...] = ()
