from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from hypothesis import given, settings, strategies as st

from personal_world.model.contracts import (
    DataAccessProfile,
    PersonalFactCreate,
    QualificationStatus,
    RecordKind,
    SensitivityClass,
    RevalidationRequest,
    RevisionRequest,
    SemanticRef,
    SourceClass,
    SourceDescriptorCreate,
    TemporalScope,
)
from personal_world.persistence import SqlAlchemyPersonalWorldStore, create_database_engine
from personal_world.service import PersonalWorldService

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _fresh_service() -> PersonalWorldService:
    store = SqlAlchemyPersonalWorldStore(create_database_engine("sqlite://"))
    store.create_schema()
    service = PersonalWorldService(store)
    service.put_access_profile(
        DataAccessProfile(
            service_identity="agency-console",
            allowed_purposes=("*",),
            allowed_kinds=tuple(RecordKind),
            max_sensitivity=SensitivityClass.HIGHLY_SENSITIVE,
        )
    )
    return service


def _source(service: PersonalWorldService):
    return service.create_source(
        SourceDescriptorCreate(source_class=SourceClass.HUMAN_EXPLICIT, actor_ref="human:self")
    )


@settings(max_examples=60, deadline=None)
@given(
    recorded_day=st.integers(min_value=-30, max_value=30),
    valid_from_day=st.integers(min_value=-30, max_value=30),
    lifetime_days=st.one_of(st.none(), st.integers(min_value=1, max_value=60)),
    query_day=st.integers(min_value=-30, max_value=60),
)
def test_as_of_is_intersection_of_record_time_and_valid_time(
    recorded_day: int,
    valid_from_day: int,
    lifetime_days: int | None,
    query_day: int,
) -> None:
    service = _fresh_service()
    subject = uuid4()
    source = _source(service)
    valid_from = BASE + timedelta(days=valid_from_day)
    valid_until = (
        None if lifetime_days is None else valid_from + timedelta(days=lifetime_days)
    )
    service.create_fact(
        PersonalFactCreate(
            subject_id=subject,
            semantic=SemanticRef(kind="predicate", id="temporal-property", namespace="personal"),
            value="visible",
            source_refs=(source.id,),
            temporal=TemporalScope(
                observed_at=BASE + timedelta(days=recorded_day - 1),
                recorded_at=BASE + timedelta(days=recorded_day),
                valid_from=valid_from,
                valid_until=valid_until,
            ),
        )
    )

    moment = BASE + timedelta(days=query_day)
    records = service.current_for_subject(
        subject,
        service_identity="agency-console",
        purpose="audit",
        as_of=moment,
    )
    expected = (
        recorded_day <= query_day
        and valid_from_day <= query_day
        and (valid_until is None or moment < valid_until)
    )
    assert bool(records) is expected


@settings(max_examples=40, deadline=None)
@given(
    first_recorded=st.integers(min_value=-20, max_value=-1),
    correction_recorded=st.integers(min_value=1, max_value=20),
    backdate=st.integers(min_value=-40, max_value=0),
)
def test_late_arriving_backdated_correction_does_not_rewrite_record_time(
    first_recorded: int,
    correction_recorded: int,
    backdate: int,
) -> None:
    service = _fresh_service()
    subject = uuid4()
    source = _source(service)
    first = service.create_fact(
        PersonalFactCreate(
            subject_id=subject,
            semantic=SemanticRef(kind="predicate", id="home-city", namespace="personal"),
            value="Tokyo",
            source_refs=(source.id,),
            temporal=TemporalScope(
                recorded_at=BASE + timedelta(days=first_recorded),
                valid_from=BASE + timedelta(days=-50),
            ),
        )
    )
    service.revise(
        first.id,
        RevisionRequest(
            expected_revision=1,
            value="Osaka",
            source_refs=(source.id,),
            temporal=TemporalScope(
                recorded_at=BASE + timedelta(days=correction_recorded),
                valid_from=BASE + timedelta(days=backdate),
            ),
        ),
    )

    before = service.current_for_subject(
        subject,
        service_identity="agency-console",
        purpose="audit",
        as_of=BASE,
    )
    after = service.current_for_subject(
        subject,
        service_identity="agency-console",
        purpose="audit",
        as_of=BASE + timedelta(days=correction_recorded + 1),
    )
    assert [item.value for item in before] == ["Tokyo"]
    assert [item.value for item in after] == ["Osaka"]


def test_revalidation_gets_new_record_time_and_preserves_historical_status(
    service: PersonalWorldService,
    monkeypatch,
) -> None:
    subject = uuid4()
    source = _source(service)
    first_time = datetime(2026, 1, 1, tzinfo=UTC)
    revalidation_time = datetime(2026, 2, 1, tzinfo=UTC)
    first = service.create_fact(
        PersonalFactCreate(
            subject_id=subject,
            semantic=SemanticRef(kind="predicate", id="residence", namespace="personal"),
            value="Tokyo",
            source_refs=(source.id,),
            temporal=TemporalScope(recorded_at=first_time, valid_from=first_time),
        )
    )

    monkeypatch.setattr("personal_world.service.utc_now", lambda: revalidation_time)
    retracted = service.revalidate(
        first.id,
        RevalidationRequest(
            expected_revision=1,
            status=QualificationStatus.RETRACTED,
            reason="human correction",
        ),
    )

    assert retracted.temporal.recorded_at == revalidation_time
    january = service.current_for_subject(
        subject,
        service_identity="agency-console",
        purpose="audit",
        as_of=datetime(2026, 1, 15, tzinfo=UTC),
    )
    february = service.current_for_subject(
        subject,
        service_identity="agency-console",
        purpose="audit",
        as_of=datetime(2026, 2, 2, tzinfo=UTC),
    )
    assert len(january) == 1
    assert january[0].status == QualificationStatus.CURRENT
    assert len(february) == 1
    assert february[0].status == QualificationStatus.RETRACTED
