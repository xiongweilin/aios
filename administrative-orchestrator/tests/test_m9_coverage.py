from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from administrative_orchestrator.commitment_models import CommitmentState
from administrative_orchestrator.config import Settings
from administrative_orchestrator.intake.artifacts import FilesystemArtifactStore
from administrative_orchestrator.integrations.credentials import (
    CredentialRef,
    CredentialResolutionError,
    EnvironmentCredentialResolver,
    EnvironmentOrFileCredentialResolver,
    read_credential_file,
)
from administrative_orchestrator.integrations.production_effects import (
    AdministrativeCommunicationEffectConnection,
    AdministrativeCommunicationEffectConnector,
    ConnectorConfigurationError,
    ConnectorStatus,
)


class _Resolver:
    def resolve(self, ref: CredentialRef) -> str:
        assert ref.configuration_ref
        return "test-secret"


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


@pytest.mark.asyncio
async def test_administrative_communication_connector_classifies_transport_outcomes(
    tmp_path: Path,
) -> None:
    artifact_store = FilesystemArtifactStore(tmp_path / "artifacts")
    stored = artifact_store.put("确认消息".encode())
    connection = AdministrativeCommunicationEffectConnection(
        gateway_base_url="http://gateway.example.test",
        transport_credential=CredentialRef("m9:gateway", "M9_GATEWAY_SECRET"),
        artifact_root=tmp_path / "artifacts",
        allow_insecure_http=True,
    )

    async def run(status: int, payload: object) -> object:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status, json=payload, request=request)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        connector = AdministrativeCommunicationEffectConnector(
            connection,
            credentials=_Resolver(),
            client=client,
        )
        try:
            return await connector.invoke(
                request_ref="event-m9-connector",
                subject_ref="commitment:event-m9-connector",
                parameters={
                    "communication_event_id": "event-m9-connector",
                    "recipient_open_id": "ou_m9",
                    "content_storage_ref": stored.storage_ref,
                    "content_digest": stored.digest,
                    "draft_kind": "confirmation",
                },
            )
        finally:
            await client.aclose()

    incomplete = await run(202, {})
    assert incomplete.status is ConnectorStatus.SUCCEEDED

    success = await run(
        202,
        {"transportAccepted": True, "deliveryConfirmed": False, "providerMessageRef": "om_m9"},
    )
    assert success.status is ConnectorStatus.SUCCEEDED
    assert success.external_operation_ref == "om_m9"
    assert success.observed_postcondition == {
        "target_system": "communication",
        "operation": "message.send",
        "subject_ref": "commitment:event-m9-connector",
        "communication_event_id": "event-m9-connector",
        "transport_accepted": True,
        "delivery_confirmed": False,
        "read_state": "unknown",
    }

    unknown = await run(503, {})
    assert unknown.status is ConnectorStatus.UNKNOWN
    assert unknown.error_code == "GatewayHTTP503"
    failed = await run(400, {})
    assert failed.status is ConnectorStatus.FAILED
    assert failed.error_code == "GatewayHTTP400"
    malformed = await run(202, ["not-an-object"])
    assert malformed.status is ConnectorStatus.FAILED
    assert malformed.error_code == "InvalidCommunicationReceipt"

    async def failing_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("transport disappeared", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(failing_handler))
    connector = AdministrativeCommunicationEffectConnector(
        connection,
        credentials=_Resolver(),
        client=client,
    )
    try:
        outcome_unknown = await connector.invoke(
            request_ref="event-m9-timeout",
            subject_ref="commitment:event-m9-timeout",
            parameters={
                "recipient_open_id": "ou_m9",
                "content_storage_ref": stored.storage_ref,
                "content_digest": stored.digest,
            },
        )
    finally:
        await client.aclose()
    assert outcome_unknown.status is ConnectorStatus.UNKNOWN
    assert outcome_unknown.error_code == "ReadTimeout"
    assert await connector.reconcile("event-m9-timeout") is None

    invalid = await connector.invoke(
        request_ref="event-m9-invalid",
        subject_ref="commitment:event-m9-invalid",
        parameters={"recipient_open_id": "ou_m9", "content_digest": "short"},
    )
    assert invalid.status is ConnectorStatus.FAILED
    with pytest.raises(ConnectorConfigurationError):
        AdministrativeCommunicationEffectConnection(
            gateway_base_url="http://gateway.example.test",
            transport_credential=CredentialRef("m9:gateway", "M9_GATEWAY_SECRET"),
            artifact_root=tmp_path / "artifacts",
            timeout_seconds=0,
            allow_insecure_http=True,
        )


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
