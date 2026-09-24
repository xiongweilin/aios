from __future__ import annotations

from pathlib import Path

import pytest

from personal_world.model.contracts import DataAccessProfile, RecordKind, SensitivityClass
from personal_world.persistence import SqlAlchemyPersonalWorldStore, create_database_engine
from personal_world.service import PersonalWorldService


@pytest.fixture
def service(tmp_path: Path) -> PersonalWorldService:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'personal-world.db'}")
    store = SqlAlchemyPersonalWorldStore(engine)
    store.create_schema()
    runtime = PersonalWorldService(store)
    runtime.put_access_profile(
        DataAccessProfile(
            service_identity="agency-console",
            allowed_purposes=("*",),
            allowed_kinds=tuple(RecordKind),
            max_sensitivity=SensitivityClass.HIGHLY_SENSITIVE,
        )
    )
    runtime.put_access_profile(
        DataAccessProfile(
            service_identity="travel",
            allowed_purposes=("travel-planning",),
            allowed_kinds=(RecordKind.PREFERENCE, RecordKind.RESOURCE_LINK),
            max_sensitivity=SensitivityClass.PERSONAL,
        )
    )
    return runtime
