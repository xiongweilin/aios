from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest

from personal_world.model.contracts import (
    DataAccessProfile,
    PersonalFactCreate,
    QualificationStatus,
    RecordKind,
    SensitivityClass,
    SemanticRef,
    SourceClass,
    SourceDescriptorCreate,
)
from personal_world.persistence import (
    Base,
    ConcurrencyError,
    SqlAlchemyPersonalWorldStore,
    create_database_engine,
)
from personal_world.service import PersonalWorldService

pytestmark = pytest.mark.postgres


def test_postgres_multi_instance_cas() -> None:
    url = os.getenv("PERSONAL_WORLD_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("PERSONAL_WORLD_TEST_POSTGRES_URL is not configured")

    engine = create_database_engine(url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    first_store = SqlAlchemyPersonalWorldStore(engine)
    second_store = SqlAlchemyPersonalWorldStore(create_database_engine(url))
    first = PersonalWorldService(first_store)
    source = first.create_source(
        SourceDescriptorCreate(source_class=SourceClass.HUMAN_EXPLICIT, actor_ref="human:self")
    )
    fact = first.create_fact(
        PersonalFactCreate(
            subject_id=uuid4(),
            semantic=SemanticRef(kind="predicate", id="language", namespace="personal"),
            value="zh-CN",
            source_refs=(source.id,),
        )
    )
    winning = fact.model_copy(
        update={
            "id": uuid4(),
            "revision": 2,
            "value": "en-US",
            "supersedes_id": fact.id,
            "status": QualificationStatus.CURRENT,
        }
    )
    stale = fact.model_copy(
        update={
            "id": uuid4(),
            "revision": 2,
            "value": "ja-JP",
            "supersedes_id": fact.id,
            "status": QualificationStatus.CURRENT,
        }
    )

    first_store.append_revision(
        lineage_id=fact.lineage_id,
        expected_revision=1,
        record=winning,
    )
    with pytest.raises(ConcurrencyError):
        second_store.append_revision(
            lineage_id=fact.lineage_id,
            expected_revision=1,
            record=stale,
        )

    assert second_store.current_record(fact.lineage_id).value == "en-US"



def test_postgres_concurrent_writers_have_exactly_one_winner() -> None:
    url = os.getenv("PERSONAL_WORLD_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("PERSONAL_WORLD_TEST_POSTGRES_URL is not configured")

    engine = create_database_engine(url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    store = SqlAlchemyPersonalWorldStore(engine)
    service = PersonalWorldService(store)
    source = service.create_source(
        SourceDescriptorCreate(source_class=SourceClass.HUMAN_EXPLICIT, actor_ref="human:self")
    )
    subject = uuid4()
    first = service.create_fact(
        PersonalFactCreate(
            subject_id=subject,
            semantic=SemanticRef(kind="predicate", id="concurrency", namespace="personal"),
            value="initial",
            source_refs=(source.id,),
        )
    )

    writer_count = 32
    barrier = Barrier(writer_count)

    def attempt(index: int) -> str:
        local_store = SqlAlchemyPersonalWorldStore(create_database_engine(url))
        candidate = first.model_copy(
            update={
                "id": uuid4(),
                "revision": 2,
                "value": f"writer-{index}",
                "supersedes_id": first.id,
                "status": QualificationStatus.CURRENT,
            }
        )
        barrier.wait()
        try:
            local_store.append_revision(
                lineage_id=first.lineage_id,
                expected_revision=1,
                record=candidate,
            )
        except ConcurrencyError:
            return "conflict"
        return "won"

    with ThreadPoolExecutor(max_workers=writer_count) as pool:
        results = list(pool.map(attempt, range(writer_count)))

    assert results.count("won") == 1
    assert results.count("conflict") == writer_count - 1
    history = store.history(subject)
    assert [record.revision for record in history] == [1, 2]
    assert len({record.revision for record in history}) == 2
    assert store.current_record(first.lineage_id).revision == 2


def test_postgres_bundle_restore_after_store_recreation() -> None:
    url = os.getenv("PERSONAL_WORLD_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("PERSONAL_WORLD_TEST_POSTGRES_URL is not configured")

    engine = create_database_engine(url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    store = SqlAlchemyPersonalWorldStore(engine)
    service = PersonalWorldService(store)
    service.put_access_profile(
        DataAccessProfile(
            service_identity="administrative-orchestrator",
            allowed_purposes=("*",),
            allowed_kinds=tuple(RecordKind),
            max_sensitivity=SensitivityClass.HIGHLY_SENSITIVE,
        )
    )
    source = service.create_source(
        SourceDescriptorCreate(source_class=SourceClass.HUMAN_EXPLICIT, actor_ref="human:self")
    )
    subject = uuid4()
    first = service.create_fact(
        PersonalFactCreate(
            subject_id=subject,
            semantic=SemanticRef(kind="predicate", id="restore-city", namespace="personal"),
            value="Tokyo",
            source_refs=(source.id,),
        )
    )
    second = first.model_copy(
        update={
            "id": uuid4(),
            "revision": 2,
            "value": "Osaka",
            "supersedes_id": first.id,
        }
    )
    store.append_revision(
        lineage_id=first.lineage_id,
        expected_revision=1,
        record=second,
    )
    bundle = service.export_bundle()
    expected = bundle.model_dump(mode="json")
    expected.pop("exported_at", None)

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    restored = PersonalWorldService(SqlAlchemyPersonalWorldStore(engine))
    restored.import_bundle(bundle)

    actual = restored.export_bundle().model_dump(mode="json")
    actual.pop("exported_at", None)
    assert actual == expected
    assert restored.store.current_record(first.lineage_id).value == "Osaka"
    assert [record.value for record in restored.store.history(subject)] == ["Tokyo", "Osaka"]
