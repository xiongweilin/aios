from __future__ import annotations

from uuid import uuid4

from personal_world.model.contracts import (
    ContextProjectionRequest,
    ErasureRequest,
    PersonalFactCreate,
    SearchRequest,
    SemanticRef,
    SourceClass,
    SourceDescriptorCreate,
)
from personal_world.service import PersonalWorldService


def test_erasure_removes_personal_content_from_all_derived_surfaces(
    service: PersonalWorldService,
) -> None:
    subject = uuid4()
    secret = "erase-me-unique-secret-7731"
    source = service.create_source(
        SourceDescriptorCreate(
            source_class=SourceClass.HUMAN_EXPLICIT,
            actor_ref="human:self",
            description=secret,
            metadata={"secret": secret},
        )
    )
    service.create_fact(
        PersonalFactCreate(
            subject_id=subject,
            semantic=SemanticRef(kind="predicate", id="private-note", namespace="personal"),
            value={"text": secret},
            source_refs=(source.id,),
            context={"note": secret},
            metadata={"secret": secret},
        )
    )

    before_search = service.search(
        SearchRequest(subject_id=subject, purpose="audit", query=secret),
        service_identity="administrative-orchestrator",
    )
    assert before_search
    before_projection = service.project(
        ContextProjectionRequest(subject_id=subject, purpose="audit", query=secret),
        service_identity="administrative-orchestrator",
    )
    assert before_projection.included_items

    service.erase(ErasureRequest(subject_id=subject, reason="user requested erasure"))

    assert service.search(
        SearchRequest(subject_id=subject, purpose="audit", query=secret),
        service_identity="administrative-orchestrator",
    ) == []
    projection = service.project(
        ContextProjectionRequest(subject_id=subject, purpose="audit", query=secret),
        service_identity="administrative-orchestrator",
    )
    assert projection.included_items == ()
    assert projection.contested_items == ()
    assert projection.stale_items == ()
    assert service.history_for_subject(
        subject,
        service_identity="administrative-orchestrator",
        purpose="audit",
    ) == []

    bundle_json = service.export_bundle().model_dump_json()
    assert secret not in bundle_json
