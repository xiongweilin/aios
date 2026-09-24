from __future__ import annotations

from uuid import uuid4

import pytest

from personal_world.model.contracts import (
    ClaimCreate,
    ErasureRequest,
    ObservationCreate,
    PersonalFactCreate,
    PreferenceCreate,
    PreferenceOrigin,
    RecordKind,
    SemanticRef,
    SourceClass,
    SourceDescriptorCreate,
)
from personal_world.persistence import NotFoundError
from personal_world.service import PersonalWorldService


def _provenance(service: PersonalWorldService, subject_id, term: str):
    source = service.create_source(
        SourceDescriptorCreate(
            source_class=SourceClass.HUMAN_EXPLICIT,
            actor_ref="human:self",
            description=term,
        )
    )
    observation = service.create_observation(
        ObservationCreate(
            subject_id=subject_id,
            source_id=source.id,
            semantic=SemanticRef(kind="predicate", id=term, namespace="personal"),
            value=term,
        )
    )
    claim = service.create_claim(
        ClaimCreate(
            subject_id=subject_id,
            source_id=source.id,
            semantic=SemanticRef(kind="predicate", id=term, namespace="personal"),
            value=term,
            observation_refs=(observation.id,),
        )
    )
    return source, observation, claim


def test_kind_scoped_erasure_preserves_unrelated_provenance(
    service: PersonalWorldService,
) -> None:
    subject = uuid4()
    fact_source, fact_observation, fact_claim = _provenance(service, subject, "city")
    pref_source, pref_observation, pref_claim = _provenance(service, subject, "seat")

    service.create_fact(
        PersonalFactCreate(
            subject_id=subject,
            semantic=SemanticRef(kind="predicate", id="city", namespace="personal"),
            value="Tokyo",
            source_refs=(fact_source.id,),
            claim_refs=(fact_claim.id,),
        )
    )
    preference = service.create_preference(
        PreferenceCreate(
            subject_id=subject,
            semantic=SemanticRef(kind="predicate", id="seat", namespace="personal"),
            value="window",
            source_refs=(pref_source.id,),
            claim_refs=(pref_claim.id,),
            origin=PreferenceOrigin.EXPLICIT,
        )
    )

    result = service.erase(
        ErasureRequest(subject_id=subject, reason="remove facts", kinds=(RecordKind.FACT,))
    )
    assert result.redacted_records == 1
    assert result.redacted_claims == 1
    assert result.redacted_observations == 1

    with pytest.raises(NotFoundError):
        service.store.get_source(fact_source.id)
    with pytest.raises(NotFoundError):
        service.store.get_observation(fact_observation.id)
    with pytest.raises(NotFoundError):
        service.store.get_claim(fact_claim.id)

    assert service.store.get_source(pref_source.id).id == pref_source.id
    assert service.store.get_observation(pref_observation.id).id == pref_observation.id
    assert service.store.get_claim(pref_claim.id).id == pref_claim.id
    assert service.store.current_record(preference.lineage_id).id == preference.id
