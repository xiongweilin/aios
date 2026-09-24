from __future__ import annotations

from uuid import uuid4

import pytest
from semantic_language import SemanticRef

from personal_world.model.contracts import (
    ContextProjectionRequest,
    PersonalFactCreate,
    PreferenceCreate,
    PreferenceOrigin,
    RevisionRequest,
    SourceClass,
    SourceDescriptorCreate,
)
from personal_world.persistence import NotFoundError
from personal_world.service import PersonalWorldService


def semantic(namespace: str, item_id: str) -> SemanticRef:
    return SemanticRef(kind="predicate", id=item_id, namespace=namespace)


def test_scope_filter_is_minimum_necessary_and_audited(
    service: PersonalWorldService,
) -> None:
    subject = uuid4()
    source = service.create_source(
        SourceDescriptorCreate(
            source_class=SourceClass.HUMAN_EXPLICIT,
            actor_ref="human:self",
        )
    )
    global_pref = service.create_preference(
        PreferenceCreate(
            subject_id=subject,
            semantic=semantic("travel", "seat"),
            value="window",
            source_refs=(source.id,),
            origin=PreferenceOrigin.EXPLICIT,
        )
    )
    scoped_pref = service.create_preference(
        PreferenceCreate(
            subject_id=subject,
            semantic=semantic("travel", "hotel"),
            value="quiet",
            source_refs=(source.id,),
            origin=PreferenceOrigin.EXPLICIT,
            context={"scope": "trip:japan-2026"},
        )
    )
    service.create_preference(
        PreferenceCreate(
            subject_id=subject,
            semantic=semantic("travel", "hotel"),
            value="central",
            source_refs=(source.id,),
            origin=PreferenceOrigin.EXPLICIT,
            context={"scope": "trip:france-2027"},
        )
    )

    projection = service.project(
        ContextProjectionRequest(
            subject_id=subject,
            purpose="travel-planning",
            scope="trip:japan-2026",
        ),
        service_identity="travel",
    )

    assert {item.id for item in projection.included_items} == {
        global_pref.id,
        scoped_pref.id,
    }
    assert projection.excluded_count == 1

    audit = service.list_disclosures(subject)
    assert len(audit) == 1
    assert audit[0].service_identity == "travel"
    assert audit[0].purpose == "travel-planning"
    assert audit[0].action == "projection"
    assert set(audit[0].record_refs) == {global_pref.id, scoped_pref.id}
    assert audit[0].excluded_count == 1


def test_record_redaction_never_resurrects_prior_revision(
    service: PersonalWorldService,
) -> None:
    subject = uuid4()
    source = service.create_source(
        SourceDescriptorCreate(
            source_class=SourceClass.HUMAN_EXPLICIT,
            actor_ref="human:self",
        )
    )
    first = service.create_fact(
        PersonalFactCreate(
            subject_id=subject,
            semantic=semantic("personal", "city"),
            value="Tokyo",
            source_refs=(source.id,),
        )
    )
    second = service.revise(
        first.id,
        RevisionRequest(
            expected_revision=1,
            value="Osaka",
            source_refs=(source.id,),
        ),
    )

    service.redact("record", second.id)

    with pytest.raises(NotFoundError):
        service.store.current_record(first.lineage_id)
    assert service.store.list_records(subject) == []
    assert service.store.history(subject) == []


def test_disclosure_audit_survives_bundle_restore(
    service: PersonalWorldService,
    tmp_path,
) -> None:
    subject = uuid4()
    service.current_for_subject(
        subject,
        service_identity="agency-console",
        purpose="audit",
    )
    bundle = service.export_bundle()

    from personal_world.persistence import SqlAlchemyPersonalWorldStore, create_database_engine

    store = SqlAlchemyPersonalWorldStore(
        create_database_engine(f"sqlite:///{tmp_path / 'audit-restore.db'}")
    )
    store.create_schema()
    restored = PersonalWorldService(store)
    restored.import_bundle(bundle)

    audits = restored.list_disclosures(subject)
    assert len(audits) == 1
    assert audits[0].action == "current"
