from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from personal_world.model.contracts import (
    ContextProjectionRequest,
    DomainClaim,
    DomainPersonalProjection,
    ErasureRequest,
    ObservationCreate,
    PersonalFactCreate,
    PreferenceCreate,
    PreferenceOrigin,
    QualificationStatus,
    RecordKind,
    ResourceLinkCreate,
    RevisionRequest,
    RevalidationRequest,
    SemanticRef,
    SensitivityClass,
    SourceClass,
    SourceDescriptorCreate,
    TemporalScope,
)
from personal_world.persistence import SqlAlchemyPersonalWorldStore, create_database_engine
from personal_world.service import AdmissionError, PersonalWorldService


def human_source(service: PersonalWorldService):
    return service.create_source(
        SourceDescriptorCreate(source_class=SourceClass.HUMAN_EXPLICIT, actor_ref="human:self")
    )


def test_model_inference_cannot_silently_become_current(service: PersonalWorldService) -> None:
    subject = uuid4()
    source = service.create_source(
        SourceDescriptorCreate(source_class=SourceClass.MODEL_INFERENCE, actor_ref="model:test")
    )
    record = service.create_fact(
        PersonalFactCreate(
            subject_id=subject,
            semantic=SemanticRef(kind="predicate", id="city", namespace="personal"),
            value="Tokyo",
            source_refs=(source.id,),
        )
    )
    assert record.status == QualificationStatus.CANDIDATE
    with pytest.raises(AdmissionError):
        service.revalidate(
            record.id,
            RevalidationRequest(
                expected_revision=1,
                status=QualificationStatus.CURRENT,
                reason="model guessed it",
            ),
        )


def test_explicitly_accepted_inference_can_be_preference(service: PersonalWorldService) -> None:
    subject = uuid4()
    source = service.create_source(
        SourceDescriptorCreate(source_class=SourceClass.MODEL_INFERENCE, actor_ref="model:test")
    )
    record = service.create_preference(
        PreferenceCreate(
            subject_id=subject,
            semantic=SemanticRef(kind="predicate", id="seat-preference", namespace="personal"),
            value="window",
            source_refs=(source.id,),
            origin=PreferenceOrigin.ACCEPTED_INFERENCE,
        )
    )
    assert record.status == QualificationStatus.CURRENT


def test_revision_preserves_history_and_as_of_world(service: PersonalWorldService) -> None:
    subject = uuid4()
    source = human_source(service)
    first = service.create_fact(
        PersonalFactCreate(
            subject_id=subject,
            semantic=SemanticRef(kind="predicate", id="home-city", namespace="personal"),
            value="Tokyo",
            source_refs=(source.id,),
            temporal=TemporalScope(
                observed_at=datetime(2026, 1, 1, tzinfo=UTC),
                recorded_at=datetime(2026, 1, 1, tzinfo=UTC),
                valid_from=datetime(2026, 1, 1, tzinfo=UTC),
            ),
        )
    )
    second = service.revise(
        first.id,
        RevisionRequest(
            expected_revision=1,
            value="Osaka",
            source_refs=(source.id,),
            temporal=TemporalScope(
                observed_at=datetime(2026, 9, 1, tzinfo=UTC),
                recorded_at=datetime(2026, 9, 1, tzinfo=UTC),
                valid_from=datetime(2026, 9, 1, tzinfo=UTC),
            ),
        ),
    )
    assert second.revision == 2
    march = service.current_for_subject(
        subject,
        service_identity="agency-console",
        purpose="audit",
        as_of=datetime(2026, 3, 1, tzinfo=UTC),
    )
    current = service.current_for_subject(
        subject,
        service_identity="agency-console",
        purpose="audit",
    )
    assert [item.value for item in march] == ["Tokyo"]
    assert [item.value for item in current] == ["Osaka"]
    assert len(
        service.history_for_subject(subject, service_identity="agency-console", purpose="audit")
    ) == 2


def test_projection_is_purpose_limited(service: PersonalWorldService) -> None:
    subject = uuid4()
    source = human_source(service)
    service.create_fact(
        PersonalFactCreate(
            subject_id=subject,
            semantic=SemanticRef(kind="predicate", id="private-note", namespace="personal"),
            value="do not disclose",
            source_refs=(source.id,),
            sensitivity=SensitivityClass.SENSITIVE,
        )
    )
    service.create_preference(
        PreferenceCreate(
            subject_id=subject,
            semantic=SemanticRef(kind="predicate", id="seat", namespace="travel"),
            value="window",
            source_refs=(source.id,),
            origin=PreferenceOrigin.EXPLICIT,
        )
    )
    service.create_resource_link(
        ResourceLinkCreate(
            subject_id=subject,
            semantic=SemanticRef(kind="predicate", id="loyalty-account", namespace="travel"),
            value={"label": "primary"},
            source_refs=(source.id,),
            resource_ref="travel:loyalty:123",
            domain="travel",
            relation="uses",
        )
    )
    projection = service.project(
        ContextProjectionRequest(subject_id=subject, purpose="travel-planning"),
        service_identity="travel",
    )
    assert {item.kind for item in projection.included_items} == {
        RecordKind.PREFERENCE,
        RecordKind.RESOURCE_LINK,
    }
    assert projection.excluded_count == 1


def test_domain_projection_is_candidate_not_domain_truth_copy(service: PersonalWorldService) -> None:
    subject = uuid4()
    records = service.ingest_domain_projection(
        DomainPersonalProjection(
            subject_id=subject,
            source_domain="travel",
            source_object_ref="booking:123",
            source_version="4",
            claims=(
                DomainClaim(
                    semantic=SemanticRef(kind="predicate", id="booking-link", namespace="travel"),
                    value="travel:booking:123",
                ),
            ),
        ),
        actor_ref="travel-controller",
    )
    assert len(records) == 1
    assert records[0].status == QualificationStatus.CANDIDATE
    assert records[0].metadata["source_domain"] == "travel"


def test_administrative_domain_projection_can_preserve_relationship_shape(
    service: PersonalWorldService,
) -> None:
    subject = uuid4()
    records = service.ingest_domain_projection(
        DomainPersonalProjection(
            subject_id=subject,
            source_domain="administrative-orchestrator",
            source_object_ref="employee:42",
            source_version="17",
            claims=(
                DomainClaim(
                    record_kind=RecordKind.RELATIONSHIP,
                    semantic=SemanticRef(
                        kind="predicate",
                        id="employee-of",
                        namespace="administrative",
                    ),
                    value={"employee_ref": "employee:42"},
                    target_ref="organization:acme",
                    relation_namespace="employment",
                    metadata={"case_ref": "case:employment:42"},
                ),
            ),
        ),
        actor_ref="administrative-orchestrator",
    )

    assert len(records) == 1
    record = records[0]
    assert record.kind == RecordKind.RELATIONSHIP
    assert record.status == QualificationStatus.CANDIDATE
    assert record.target_ref == "organization:acme"
    assert record.relation_namespace == "employment"
    assert record.metadata["source_domain"] == "administrative-orchestrator"


def test_development_domain_projection_can_preserve_resource_link_shape(
    service: PersonalWorldService,
) -> None:
    subject = uuid4()
    records = service.ingest_domain_projection(
        DomainPersonalProjection(
            subject_id=subject,
            source_domain="autonomous-development",
            source_object_ref="target:personal-world",
            source_version="9",
            claims=(
                DomainClaim(
                    record_kind=RecordKind.RESOURCE_LINK,
                    semantic=SemanticRef(
                        kind="predicate",
                        id="development-repository",
                        namespace="development",
                    ),
                    value={"label": "personal-world repository"},
                    resource_ref="github:xiongweilin/personal-world",
                    domain="development",
                    relation="maintains",
                    metadata={"target_ref": "target:personal-world"},
                ),
            ),
        ),
        actor_ref="autonomous-development",
    )

    assert len(records) == 1
    record = records[0]
    assert record.kind == RecordKind.RESOURCE_LINK
    assert record.status == QualificationStatus.CANDIDATE
    assert record.resource_ref == "github:xiongweilin/personal-world"
    assert record.domain == "development"
    assert record.relation == "maintains"


def test_erasure_does_not_remove_shared_source(tmp_path) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'shared.db'}")
    store = SqlAlchemyPersonalWorldStore(engine)
    store.create_schema()
    runtime = PersonalWorldService(store)
    source = runtime.create_source(
        SourceDescriptorCreate(source_class=SourceClass.EXTERNAL_RECORD, external_ref="shared:1")
    )
    first, second = uuid4(), uuid4()
    runtime.create_observation(
        ObservationCreate(
            subject_id=first,
            source_id=source.id,
            semantic=SemanticRef(kind="predicate", id="x", namespace="personal"),
            value=1,
        )
    )
    runtime.create_observation(
        ObservationCreate(
            subject_id=second,
            source_id=source.id,
            semantic=SemanticRef(kind="predicate", id="x", namespace="personal"),
            value=2,
        )
    )
    result = runtime.erase(ErasureRequest(subject_id=first, reason="requested"))
    assert result.redacted_sources == 0
    assert store.get_source(source.id).id == source.id


def test_bundle_round_trip_preserves_ids(service: PersonalWorldService, tmp_path) -> None:
    subject = uuid4()
    source = human_source(service)
    fact = service.create_fact(
        PersonalFactCreate(
            subject_id=subject,
            semantic=SemanticRef(kind="predicate", id="language", namespace="personal"),
            value="zh-CN",
            source_refs=(source.id,),
        )
    )
    bundle = service.export_bundle()
    engine = create_database_engine(f"sqlite:///{tmp_path / 'restored.db'}")
    restored_store = SqlAlchemyPersonalWorldStore(engine)
    restored_store.create_schema()
    restored = PersonalWorldService(restored_store)
    restored.import_bundle(bundle)
    loaded = restored_store.current_record(fact.lineage_id)
    assert loaded.id == fact.id
    assert loaded.lineage_id == fact.lineage_id
    assert loaded.value == "zh-CN"


def test_revising_non_head_is_rejected(service: PersonalWorldService) -> None:
    subject = uuid4()
    source = human_source(service)
    first = service.create_fact(
        PersonalFactCreate(
            subject_id=subject,
            semantic=SemanticRef(kind="predicate", id="language", namespace="personal"),
            value="zh",
            source_refs=(source.id,),
        )
    )
    service.revise(
        first.id,
        RevisionRequest(expected_revision=1, value="en", source_refs=(source.id,)),
    )
    with pytest.raises(AdmissionError):
        service.revise(
            first.id,
            RevisionRequest(expected_revision=1, value="ja", source_refs=(source.id,)),
        )
