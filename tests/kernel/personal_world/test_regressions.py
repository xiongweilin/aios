from __future__ import annotations

from uuid import uuid4

import pytest

from personal_world.model.contracts import (
    ErasureRequest,
    ObservationCreate,
    PersonalFactCreate,
    RevisionRequest,
    SemanticRef,
    SourceClass,
    SourceDescriptorCreate,
)
from personal_world.persistence import SqlAlchemyPersonalWorldStore, create_database_engine
from personal_world.service import AdmissionError, PersonalWorldService


def test_model_only_revision_cannot_replace_current(service: PersonalWorldService) -> None:
    subject = uuid4()
    human = service.create_source(
        SourceDescriptorCreate(source_class=SourceClass.HUMAN_EXPLICIT)
    )
    model = service.create_source(
        SourceDescriptorCreate(source_class=SourceClass.MODEL_INFERENCE)
    )
    current = service.create_fact(
        PersonalFactCreate(
            subject_id=subject,
            semantic=SemanticRef(kind="predicate", id="home-city", namespace="personal"),
            value="Tokyo",
            source_refs=(human.id,),
        )
    )

    with pytest.raises(AdmissionError):
        service.revise(
            current.id,
            RevisionRequest(
                expected_revision=1,
                value="Osaka",
                source_refs=(model.id,),
            ),
        )


def test_bundle_import_refuses_non_empty_store(service: PersonalWorldService) -> None:
    source = service.create_source(
        SourceDescriptorCreate(source_class=SourceClass.HUMAN_EXPLICIT)
    )
    bundle = service.export_bundle()
    assert source.id

    with pytest.raises(ValueError, match="empty store"):
        service.import_bundle(bundle)


def test_partial_record_erasure_must_not_destroy_other_provenance(tmp_path) -> None:
    store = SqlAlchemyPersonalWorldStore(
        create_database_engine(f"sqlite:///{tmp_path / 'partial-erasure.db'}")
    )
    store.create_schema()
    service = PersonalWorldService(store)
    subject = uuid4()
    shared = service.create_source(
        SourceDescriptorCreate(source_class=SourceClass.HUMAN_EXPLICIT)
    )
    service.create_observation(
        ObservationCreate(
            subject_id=subject,
            source_id=shared.id,
            semantic=SemanticRef(kind="predicate", id="language", namespace="personal"),
            value="zh-CN",
        )
    )
    service.create_fact(
        PersonalFactCreate(
            subject_id=subject,
            semantic=SemanticRef(kind="predicate", id="language", namespace="personal"),
            value="zh-CN",
            source_refs=(shared.id,),
        )
    )

    service.erase(
        ErasureRequest(
            subject_id=subject,
            reason="erase only facts",
            kinds=("fact",),
        )
    )

    # A scoped record erasure must not silently remove raw provenance, because other
    # personal record kinds may still reference it.
    assert store.get_source(shared.id).id == shared.id
