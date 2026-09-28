from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from administrative_orchestrator.commitment_models import CommitmentState
from administrative_orchestrator.config import Settings
from administrative_orchestrator.integrations.credentials import (
    CredentialRef,
    CredentialResolutionError,
    EnvironmentCredentialResolver,
    EnvironmentOrFileCredentialResolver,
    read_credential_file,
)



def test_m9_credential_resolvers_keep_values_at_the_process_edge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ref = CredentialRef("m9:test", "M9_TEST_SECRET")
    monkeypatch.setenv("M9_TEST_SECRET", "from-environment")
    assert EnvironmentCredentialResolver().resolve(ref) == "from-environment"

    monkeypatch.delenv("M9_TEST_SECRET")
    secret_file = tmp_path / "secret"
    secret_file.write_text("from-file\n", encoding="utf-8")
    resolver = EnvironmentOrFileCredentialResolver({"M9_TEST_SECRET": str(secret_file)})
    assert resolver.resolve(ref) == "from-file"
    assert read_credential_file(str(secret_file), configuration_ref="m9:test") == "from-file"

    with pytest.raises(CredentialResolutionError):
        EnvironmentCredentialResolver().resolve(ref)
    with pytest.raises(CredentialResolutionError):
        read_credential_file(str(tmp_path / "missing"), configuration_ref="m9:test")
    blank = tmp_path / "blank"
    blank.write_text("  \n", encoding="utf-8")
    with pytest.raises(CredentialResolutionError):
        read_credential_file(str(blank), configuration_ref="m9:test")



def test_m9_settings_keep_external_effects_disabled_by_default() -> None:
    settings = Settings(database_url="sqlite+pysqlite:///:memory:")
    assert settings.external_effects_enabled is False
    assert settings.world_runtime_mode == "disabled"


def test_meeting_commitment_workflow_branches_remain_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from administrative_orchestrator.workflows import definitions

    settings = SimpleNamespace(worker_database_url="db", database_url="db")
    case = SimpleNamespace(status=SimpleNamespace(value="completed"))

    def run_case(commitment: SimpleNamespace, discharge_result=None, discharge_error=None):
        class Store:
            def get_case(self, case_id):
                del case_id
                return case

        class Repository:
            def get_commitment(self, case_id):
                return commitment

        class Service:
            def __init__(self, store, *, settings):
                del store, settings
                self.repository = Repository()

            def drive(self, case_id):
                return {"case_id": str(case_id), "commitment_state": "active"}

            def discharge_responsibility(self, case_id):
                del case_id
                if discharge_error is not None:
                    raise discharge_error
                return discharge_result

        monkeypatch.setattr(definitions, "get_settings", lambda: settings)
        monkeypatch.setattr(definitions, "SqlStore", lambda _: Store())
        monkeypatch.setattr(definitions, "MeetingCommitmentService", Service)
        return definitions.drive_meeting_commitment_case_step("00000000-0000-0000-0000-000000000009")

    active = run_case(
        SimpleNamespace(
            state=CommitmentState.ACTIVE,
            responsibility_ref=None,
        )
    )
    assert active["commitment_state"] == "active"

    pending = run_case(
        SimpleNamespace(
            state=CommitmentState.FULFILLED,
            responsibility_ref="resp-m9",
        ),
        discharge_error=RuntimeError("world runtime unavailable"),
    )
    assert pending["responsibility_status"] == "pending"
    assert pending["responsibility_blocker"] == "RuntimeError"

    discharged_commitment = SimpleNamespace(
        state=CommitmentState.FULFILLED,
        responsibility_ref="resp-m9",
        responsibility_transition_ref="transition-m9",
    )
    discharged = run_case(
        SimpleNamespace(state=CommitmentState.FULFILLED, responsibility_ref="resp-m9"),
        discharge_result=discharged_commitment,
    )
    assert discharged["responsibility_status"] == "discharged"
