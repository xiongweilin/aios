from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from administrative_orchestrator import (
    commitment_responsibility as commitment_responsibility_module,
)
from administrative_orchestrator import commitment_service as commitment_service_module
from administrative_orchestrator.bootstrap_foundation import bootstrap_foundation
from administrative_orchestrator.commitment_models import (
    CandidateCommitmentClassification,
    CandidateCommitmentStatus,
    CommitmentState,
)
from administrative_orchestrator.commitment_service import (
    CommitmentIntakeError,
    MeetingCommitmentService,
    WorldRuntimeCommitmentResponsibilityProvisioner,
)
from administrative_orchestrator.config import Settings
from administrative_orchestrator.intake.artifacts import FilesystemArtifactStore
from administrative_orchestrator.intake.interpretation import (
    MeetingInterpretationPayload,
)
from administrative_orchestrator.intake.models import (
    EvidenceSpan,
    InterpretationRecord,
    InterpretationStatus,
    SourceArtifact,
)
from administrative_orchestrator.intake.repository import IntakeRepository
from administrative_orchestrator.integrations.world_runtime import WorldRuntimeBoundaryError
from administrative_orchestrator.persistence import SqlStore

BASE_TIME = datetime(2026, 9, 13, 9, 0, tzinfo=UTC)


def _store(tmp_path: Path) -> SqlStore:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    bootstrap_foundation(
        store,
        {
            "principals": [
                {"principal_id": "person:committer", "display_name": "Committer"},
                {"principal_id": "person:reviewer", "display_name": "Reviewer"},
            ],
            "identity_bindings": [
                {
                    "provider": "messaging-provider",
                    "external_subject": "ou_committer",
                    "principal_id": "person:committer",
                }
            ],
            "role_assignments": [
                {
                    "principal_id": "person:reviewer",
                    "role": "administrative_operator",
                }
            ],
        },
    )
    return store


def _interpretation(store: SqlStore, *, classification: str) -> tuple[InterpretationRecord, EvidenceSpan]:
    intake = IntakeRepository(store)
    artifact_id = uuid4()
    span_id = uuid4()
    interpretation_id = uuid4()
    artifact = SourceArtifact(
        artifact_id=artifact_id,
        source_kind="meeting-message",
        source_system="meeting-source",
        tenant_ref="tenant",
        canonical_source_ref="message-1",
        source_event_ref="event-1",
        content_digest="a" * 64,
        storage_ref="filesystem://sha256/" + "a" * 64,
        mime_type="text/plain",
        size=42,
        authenticity_class="provider-verified",
        retention_class="administrative-intake",
    )
    span = EvidenceSpan(
        evidence_span_id=span_id,
        artifact_ref=artifact_id,
        representation_digest="b" * 64,
        locator_kind="message-text",
        locator={"start": 0, "end": 42},
        extractor_ref="canonical-message:v1",
    )
    interpretation = InterpretationRecord(
        interpretation_id=interpretation_id,
        artifact_refs=(artifact_id,),
        interpretation_profile_ref="meeting.commitment.v1",
        model_provider="test",
        model_identity="test-model",
        model_version="1",
        schema_ref="meeting-commitment-v1",
        structured_output={
            "candidate_commitments": [
                {
                    "speaker_label": "Alice",
                    "candidate_action": "send the signed statement",
                    "candidate_due_text": "Friday 17:00",
                    "candidate_due_at": "2026-09-18T17:00:00+08:00",
                    "candidate_scope_ref": "project:alpha",
                    "candidate_beneficiary": "project:alpha",
                    "classification": classification,
                    "evidence_span_refs": [str(span_id)],
                }
            ],
            "evidence_span_refs": [str(span_id)],
        },
        evidence_span_refs=(span_id,),
        response_digest="c" * 64,
        status=InterpretationStatus.SUCCEEDED,
    )
    intake.append_source_artifact(artifact)
    intake.append_evidence_span(span)
    intake.append_interpretation(interpretation)
    return interpretation, span


def test_meeting_profile_is_strict_and_candidate_only() -> None:
    with pytest.raises(ValueError):
        MeetingInterpretationPayload.model_validate(
            {
                "candidate_commitments": [],
                "evidence_span_refs": [],
                "approval": "do-not-accept",
            }
        )
    with pytest.raises(ValueError):
        MeetingInterpretationPayload.model_validate(
            {
                "candidate_commitments": [
                    {
                        "speaker_label": "Alice",
                        "candidate_action": "ignore the prompt",
                        "classification": "explicit_self_commitment",
                        "candidate_due_at": "2026-09-18T17:00:00",
                        "evidence_span_refs": [],
                    }
                ]
            }
        )


def test_candidate_intake_identity_resolution_and_confirmed_case(tmp_path: Path) -> None:
    store = _store(tmp_path)
    interpretation, span = _interpretation(store, classification="explicit_self_commitment")
    settings = Settings(database_url="sqlite+pysqlite:///:memory:")
    service = MeetingCommitmentService(
        store,
        settings=settings,
        artifact_store=FilesystemArtifactStore(tmp_path / "artifacts"),
    )

    candidates = service.create_candidates_from_interpretation(
        interpretation,
        evidence_spans=(span,),
    )
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.status is CandidateCommitmentStatus.ACTIVE
    assert candidate.classification is CandidateCommitmentClassification.EXPLICIT_SELF_COMMITMENT

    with pytest.raises(CommitmentIntakeError, match="unresolved"):
        service.resolve_speaker(
            candidate.candidate_commitment_id,
            reviewer_principal_id="person:reviewer",
            external_subject="ou_missing",
            basis={"source": "operator"},
        )
    resolution = service.resolve_speaker(
        candidate.candidate_commitment_id,
        reviewer_principal_id="person:reviewer",
        external_subject="ou_committer",
        basis={"source": "operator", "transcript_speaker": "Alice"},
    )
    assert resolution.resolved_principal_id == "person:committer"

    case, commitment = service.confirm_candidate(
        candidate.candidate_commitment_id,
        reviewer_principal_id="person:reviewer",
        qualified_due_at=datetime(2026, 9, 18, 17, 0, tzinfo=UTC),
        due_time_basis="operator verified timezone and meeting context",
    )
    assert case.case_kind == "meeting-commitment"
    assert case.status.value == "authorized"
    assert commitment.state is CommitmentState.ACTIVE
    assert commitment.responsibility_ref is None
    communications = service.repository.list_communications(case.case_id)
    assert len(communications) == 1
    assert communications[0].delivery_state.value == "prepared"
    assert service.repository.get_draft(communications[0].draft_id) is not None
    assert candidate.candidate_action not in (
        service.repository.get_draft(communications[0].draft_id).model_dump()
    )

    replay_case, replay_commitment = service.confirm_candidate(
        candidate.candidate_commitment_id,
        reviewer_principal_id="person:reviewer",
        qualified_due_at=datetime(2026, 9, 18, 17, 0, tzinfo=UTC),
        due_time_basis="operator verified timezone and meeting context",
    )
    assert replay_case.case_id == case.case_id
    assert replay_commitment.commitment_id == commitment.commitment_id
    assert len(service.repository.list_communications(case.case_id)) == 1


def test_assignment_and_ambiguous_candidates_never_cross_admission(tmp_path: Path) -> None:
    store = _store(tmp_path)
    interpretation, span = _interpretation(store, classification="assignment_to_other")
    service = MeetingCommitmentService(
        store,
        settings=Settings(database_url="sqlite+pysqlite:///:memory:"),
        artifact_store=FilesystemArtifactStore(tmp_path / "artifacts"),
    )
    candidate = service.create_candidates_from_interpretation(
        interpretation,
        evidence_spans=(span,),
    )[0]
    service.resolve_speaker(
        candidate.candidate_commitment_id,
        reviewer_principal_id="person:reviewer",
        external_subject="ou_committer",
        basis={"source": "operator"},
    )
    with pytest.raises(CommitmentIntakeError, match="only explicit"):
        service.confirm_candidate(
            candidate.candidate_commitment_id,
            reviewer_principal_id="person:reviewer",
            qualified_due_at=BASE_TIME + timedelta(days=1),
            due_time_basis="operator basis",
        )
    assert service.repository.get_commitment_for_candidate(candidate.candidate_commitment_id) is None


def test_fulfillment_requires_the_qualified_committer_and_is_idempotent(tmp_path: Path) -> None:
    store = _store(tmp_path)
    interpretation, span = _interpretation(store, classification="explicit_self_commitment")
    service = MeetingCommitmentService(
        store,
        settings=Settings(database_url="sqlite+pysqlite:///:memory:"),
        artifact_store=FilesystemArtifactStore(tmp_path / "artifacts"),
    )
    candidate = service.create_candidates_from_interpretation(
        interpretation,
        evidence_spans=(span,),
    )[0]
    service.resolve_speaker(
        candidate.candidate_commitment_id,
        reviewer_principal_id="person:reviewer",
        external_subject="ou_committer",
        basis={"source": "operator"},
    )
    case, confirmed = service.confirm_candidate(
        candidate.candidate_commitment_id,
        reviewer_principal_id="person:reviewer",
        qualified_due_at=BASE_TIME + timedelta(days=1),
        due_time_basis="operator basis",
    )
    with pytest.raises(PermissionError):
        service.attest_fulfillment(
            case.case_id,
            principal_id="person:reviewer",
            basis={"kind": "attestation"},
        )
    fulfilled = service.attest_fulfillment(
        case.case_id,
        principal_id="person:committer",
        basis={"kind": "authorized_attestation", "statement": "done"},
        at=BASE_TIME + timedelta(days=2),
    )
    assert fulfilled.state is CommitmentState.FULFILLED
    assert fulfilled.was_overdue is True
    assert service.attest_fulfillment(
        case.case_id,
        principal_id="person:committer",
        basis={"kind": "authorized_attestation", "statement": "done"},
    ).commitment_id == fulfilled.commitment_id


def test_due_drive_reuses_authorization_when_clock_advances(tmp_path: Path) -> None:
    store = _store(tmp_path)
    interpretation, span = _interpretation(store, classification="explicit_self_commitment")
    settings = Settings(database_url="sqlite+pysqlite:///:memory:")
    service = MeetingCommitmentService(
        store,
        settings=settings,
        artifact_store=FilesystemArtifactStore(tmp_path / "artifacts"),
    )
    candidate = service.create_candidates_from_interpretation(
        interpretation,
        evidence_spans=(span,),
    )[0]
    service.resolve_speaker(
        candidate.candidate_commitment_id,
        reviewer_principal_id="person:reviewer",
        external_subject="ou_committer",
        basis={"source": "operator"},
    )
    case, confirmed = service.confirm_candidate(
        candidate.candidate_commitment_id,
        reviewer_principal_id="person:reviewer",
        qualified_due_at=BASE_TIME + timedelta(days=1),
        due_time_basis="operator basis",
    )

    result = service.drive(case.case_id, at=BASE_TIME + timedelta(days=2))

    assert result["commitment_state"] == "overdue"
    events = service.repository.list_communications(case.case_id)
    assert len(events) == 2
    assert {item.delivery_state.value for item in events} == {"prepared"}
    obligation_set = service.obligations.get_current(case.case_id, confirmed.authority_epoch)
    assert obligation_set is not None
    reminder_obligation = next(
        item for item in obligation_set.obligations if item.kind.endswith(":reminder")
    )
    reminder_event = next(
        item
        for item in events
        if service.repository.get_draft(item.draft_id).draft_kind == "reminder"
    )
    assert str(reminder_event.communication_event_id) == reminder_obligation.expected_postcondition[
        "communication_event_id"
    ]


def test_due_drive_recovers_persisted_overdue_without_reminder(tmp_path: Path) -> None:
    store = _store(tmp_path)
    interpretation, span = _interpretation(store, classification="explicit_self_commitment")
    settings = Settings(database_url="sqlite+pysqlite:///:memory:")
    service = MeetingCommitmentService(
        store,
        settings=settings,
        artifact_store=FilesystemArtifactStore(tmp_path / "artifacts"),
    )
    candidate = service.create_candidates_from_interpretation(
        interpretation,
        evidence_spans=(span,),
    )[0]
    service.resolve_speaker(
        candidate.candidate_commitment_id,
        reviewer_principal_id="person:reviewer",
        external_subject="ou_committer",
        basis={"source": "operator"},
    )
    case, confirmed = service.confirm_candidate(
        candidate.candidate_commitment_id,
        reviewer_principal_id="person:reviewer",
        qualified_due_at=BASE_TIME + timedelta(days=1),
        due_time_basis="operator basis",
    )
    service.repository.update_commitment(
        confirmed.model_copy(
            update={
                "state": CommitmentState.OVERDUE,
                "was_overdue": True,
                "updated_at": BASE_TIME + timedelta(days=2),
            }
        )
    )

    result = service.drive(case.case_id, at=BASE_TIME + timedelta(days=2))

    assert result["commitment_state"] == "overdue"
    events = service.repository.list_communications(case.case_id)
    assert len(events) == 2
    assert {item.delivery_state.value for item in events} == {"prepared"}


def test_due_revision_requalifies_authority_and_stales_old_communication(tmp_path: Path) -> None:
    store = _store(tmp_path)
    interpretation, span = _interpretation(store, classification="explicit_self_commitment")
    service = MeetingCommitmentService(
        store,
        settings=Settings(database_url="sqlite+pysqlite:///:memory:"),
        artifact_store=FilesystemArtifactStore(tmp_path / "artifacts"),
    )
    candidate = service.create_candidates_from_interpretation(
        interpretation,
        evidence_spans=(span,),
    )[0]
    service.resolve_speaker(
        candidate.candidate_commitment_id,
        reviewer_principal_id="person:reviewer",
        external_subject="ou_committer",
        basis={"source": "operator"},
    )
    case, original = service.confirm_candidate(
        candidate.candidate_commitment_id,
        reviewer_principal_id="person:reviewer",
        qualified_due_at=BASE_TIME + timedelta(days=1),
        due_time_basis="operator basis",
    )
    revised = service.revise_due_at(
        case.case_id,
        reviewer_principal_id="person:reviewer",
        due_at=BASE_TIME + timedelta(days=3),
        basis="operator corrected timezone after transcript review",
    )
    assert revised.authority_epoch > original.authority_epoch
    assert revised.due_at == BASE_TIME + timedelta(days=3)
    events = service.repository.list_communications(case.case_id)
    assert len(events) == 2
    assert {item.authority_epoch for item in events} == {
        original.authority_epoch,
        revised.authority_epoch,
    }


def test_cancellation_stales_prepared_communication_without_deleting_history(tmp_path: Path) -> None:
    store = _store(tmp_path)
    interpretation, span = _interpretation(store, classification="explicit_self_commitment")
    service = MeetingCommitmentService(
        store,
        settings=Settings(database_url="sqlite+pysqlite:///:memory:"),
        artifact_store=FilesystemArtifactStore(tmp_path / "artifacts"),
    )
    candidate = service.create_candidates_from_interpretation(
        interpretation,
        evidence_spans=(span,),
    )[0]
    service.resolve_speaker(
        candidate.candidate_commitment_id,
        reviewer_principal_id="person:reviewer",
        external_subject="ou_committer",
        basis={"source": "operator"},
    )
    case, commitment = service.confirm_candidate(
        candidate.candidate_commitment_id,
        reviewer_principal_id="person:reviewer",
        qualified_due_at=BASE_TIME + timedelta(days=1),
        due_time_basis="operator basis",
    )
    cancelled = service.cancel_commitment(
        case.case_id,
        reviewer_principal_id="person:reviewer",
        basis="operator cancelled the meeting commitment",
    )
    assert cancelled.state is CommitmentState.CANCELLED
    assert cancelled.authority_epoch > commitment.authority_epoch
    assert store.get_case(case.case_id).status.value == "cancelled"
    events = service.repository.list_communications(case.case_id)
    assert len(events) == 1
    assert events[0].delivery_state.value == "permanent_failed"
    assert events[0].last_error_code == "COMMITMENT_CANCELLED"


def _prepared_communication_service(
    tmp_path: Path,
    *,
    external_effects_enabled: bool = True,
    gateway_url: str = "http://gateway.example.test",
) -> tuple[SqlStore, MeetingCommitmentService, object, object]:
    store = _store(tmp_path)
    interpretation, span = _interpretation(store, classification="explicit_self_commitment")
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        external_effects_enabled=external_effects_enabled,
        communication_gateway_base_url=gateway_url,
        communication_transport_secret=SecretStr("m9-test-secret"),
        intake_artifact_root=str(tmp_path / "artifacts"),
    )
    service = MeetingCommitmentService(store, settings=settings)
    candidate = service.create_candidates_from_interpretation(
        interpretation,
        evidence_spans=(span,),
    )[0]
    service.resolve_speaker(
        candidate.candidate_commitment_id,
        reviewer_principal_id="person:reviewer",
        external_subject="ou_committer",
        basis={"source": "operator"},
    )
    case, commitment = service.confirm_candidate(
        candidate.candidate_commitment_id,
        reviewer_principal_id="person:reviewer",
        qualified_due_at=BASE_TIME + timedelta(days=1),
        due_time_basis="operator basis",
    )
    return store, service, case, commitment


def test_communication_dispatch_classifies_gateway_and_stale_outcomes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _store_for_success, service, case, commitment = _prepared_communication_service(tmp_path)
    confirmation = service.repository.list_communications(case.case_id)[0]
    reminder = service.ensure_communication(commitment, draft_kind="reminder")
    responses = iter(
        [
            httpx.Response(
                202,
                json={"deliveryConfirmed": True, "providerMessageRef": "om_confirm"},
            ),
            httpx.Response(503, json={}),
        ]
    )
    monkeypatch.setattr(commitment_service_module.httpx, "post", lambda *args, **kwargs: next(responses))

    sent = service.dispatch_communication(confirmation.communication_event_id)
    unknown = service.dispatch_communication(reminder.communication_event_id)
    assert sent.delivery_state.value == "delivery_confirmed"
    assert sent.provider_message_ref == "om_confirm"
    assert unknown.delivery_state.value == "outcome_unknown"
    assert unknown.last_error_code == "GATEWAY_HTTP_503"
    assert service.dispatch_communication(sent.communication_event_id) == sent

    _store_for_failed, failed_service, failed_case, failed_commitment = _prepared_communication_service(
        tmp_path / "failed"
    )
    failed_event = failed_service.repository.list_communications(failed_case.case_id)[0]
    monkeypatch.setattr(
        commitment_service_module.httpx,
        "post",
        lambda *args, **kwargs: httpx.Response(400, json={}),
    )
    failed = failed_service.dispatch_communication(failed_event.communication_event_id)
    assert failed.delivery_state.value == "permanent_failed"
    assert failed.last_error_code == "GATEWAY_HTTP_400"

    _store_for_missing, missing_service, missing_case, _missing_commitment = (
        _prepared_communication_service(
            tmp_path / "missing",
            gateway_url="",
        )
    )
    missing_event = missing_service.repository.list_communications(missing_case.case_id)[0]
    missing = missing_service.dispatch_communication(missing_event.communication_event_id)
    assert missing.delivery_state.value == "retrying"
    assert missing.last_error_code == "COMMUNICATION_TRANSPORT_NOT_CONFIGURED"

    stale_store, stale_service, stale_case, stale_commitment = _prepared_communication_service(
        tmp_path / "stale"
    )
    stale_event = stale_service.repository.list_communications(stale_case.case_id)[0]
    stale_service.repository.update_communication(
        stale_event.model_copy(update={"authority_epoch": stale_commitment.authority_epoch - 1})
    )
    stale = stale_service.dispatch_communication(stale_event.communication_event_id)
    assert stale.delivery_state.value == "permanent_failed"
    assert stale.last_error_code == "STALE_AUTHORITY_EPOCH"
    assert stale_store.get_case(stale_case.case_id) is not None


def test_world_runtime_commitment_responsibility_provisioner_records_and_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, service, case, commitment = _prepared_communication_service(
        tmp_path,
        external_effects_enabled=False,
    )
    governance = service.uow.governance.get_current_for_case(
        case.case_id, case.authority_epoch
    )
    assert governance is not None

    calls: list[dict] = []

    class Bridge:
        should_fail = False

        def __init__(self, *args, **kwargs):
            del args, kwargs

        def provision_responsibility(self, **payload):
            if self.should_fail:
                raise WorldRuntimeBoundaryError("runtime unavailable")
            calls.append(payload)

        def close(self):
            return None

    monkeypatch.setattr(commitment_responsibility_module, "WorldRuntimeBridge", Bridge)
    provisioner = WorldRuntimeCommitmentResponsibilityProvisioner(
        store,
        settings=Settings(
            _env_file=None,
            database_url="sqlite+pysqlite:///:memory:",
            world_runtime_mode="cutover",
        ),
    )
    refs = provisioner.provision(
        case=case,
        commitment=commitment,
        governance_basis=governance,
    )
    assert refs.responsibility_ref.startswith("m9resp_")
    assert refs.responsibility_version == 1
    assert refs.admission_ref is None
    assert calls[0]["principal"] == commitment.committer_principal_id
    assert calls[0]["scope"]["governance_basis_id"] == str(governance.basis_id)

    Bridge.should_fail = True
    with pytest.raises(CommitmentIntakeError, match="was not recorded"):
        provisioner.provision(
            case=case,
            commitment=commitment,
            governance_basis=governance,
        )

def test_operations_commitment_routes_cover_review_confirm_detail_and_attest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, service, case, commitment = _prepared_communication_service(
        tmp_path,
        external_effects_enabled=False,
    )
    candidate = service.repository.get_candidate(commitment.candidate_ref)
    assert candidate is not None
    from administrative_orchestrator import operations_api

    actor = SimpleNamespace(principal_id="person:reviewer")
    monkeypatch.setattr(operations_api, "_store", store)
    monkeypatch.setattr(operations_api, "_commitments", service.repository)
    monkeypatch.setattr(operations_api, "_commitment_service", service)
    monkeypatch.setattr(operations_api, "_actor", lambda request: actor)
    monkeypatch.setattr(operations_api, "_require", lambda *args, **kwargs: None)
    monkeypatch.setattr(operations_api, "_require_intake_review", lambda *args, **kwargs: None)

    queue = operations_api.commitment_candidate_queue(
        object(), status_filter=CandidateCommitmentStatus.ADMITTED
    )
    assert queue[0].candidate.candidate_commitment_id == candidate.candidate_commitment_id
    detail = operations_api.commitment_candidate_detail(candidate.candidate_commitment_id, object())
    assert detail.commitment is not None
    interpretation, span = _interpretation(store, classification="explicit_self_commitment")
    fresh_candidate = service.create_candidates_from_interpretation(
        interpretation,
        evidence_spans=(span,),
    )[0]
    resolved = operations_api.resolve_commitment_speaker(
        fresh_candidate.candidate_commitment_id,
        operations_api.CommitmentSpeakerResolutionBody(
            external_subject="ou_committer",
            basis={"source": "operator"},
        ),
        object(),
    )
    assert resolved.resolved_principal_id == "person:committer"
    confirmed = operations_api.confirm_commitment_candidate(
        candidate.candidate_commitment_id,
        operations_api.CommitmentConfirmationBody(
            qualified_due_at=BASE_TIME + timedelta(days=1),
            due_time_basis="operator basis",
        ),
        object(),
    )
    assert confirmed["commitment"]["case_id"] == str(case.case_id)
    revised = operations_api.revise_commitment_due(
        case.case_id,
        operations_api.CommitmentDueRevisionBody(
            due_at=BASE_TIME + timedelta(days=2),
            basis="operator corrected timezone",
        ),
        object(),
    )
    assert revised["commitment"]["due_at"].startswith("2026-09-15T09:00:00")
    commitment_detail = operations_api.commitment_detail(case.case_id, object())
    assert commitment_detail["commitment"]["commitment_id"] == str(commitment.commitment_id)
    actor.principal_id = "person:committer"
    fulfilled = operations_api.attest_commitment_fulfillment(
        case.case_id,
        operations_api.CommitmentFulfillmentBody(basis={"kind": "authorized_attestation"}),
        object(),
    )
    assert fulfilled["commitment"]["state"] == "fulfilled"

    cancel_store, cancel_service, cancel_case, _ = _prepared_communication_service(
        tmp_path / "cancel",
        external_effects_enabled=False,
    )
    monkeypatch.setattr(operations_api, "_store", cancel_store)
    monkeypatch.setattr(operations_api, "_commitments", cancel_service.repository)
    monkeypatch.setattr(operations_api, "_commitment_service", cancel_service)
    actor.principal_id = "person:reviewer"
    cancelled = operations_api.cancel_commitment(
        cancel_case.case_id,
        operations_api.CommitmentCancellationBody(basis="operator cancelled the meeting"),
        object(),
    )
    assert cancelled["commitment"]["state"] == "cancelled"
