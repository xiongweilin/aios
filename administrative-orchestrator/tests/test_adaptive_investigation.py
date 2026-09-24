from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from administrative_orchestrator.commitment_models import CommitmentRecord
from administrative_orchestrator.commitment_repository import CommitmentRepository
from administrative_orchestrator.config import Settings
from administrative_orchestrator.domain import (
    AdministrativeRequest,
    AuthorityClass,
    CaseStatus,
    EffectRecord,
    EffectReversibility,
    ExecutionAuthorization,
    PolicyRef,
    ReopenReason,
    utcnow,
)
from administrative_orchestrator.execution_repository import ExecutionRepository
from administrative_orchestrator.investigation_client import (
    HttpInvestigationClient,
    InvestigationClientError,
    InvestigationRequestEnvelope,
    UnavailableInvestigationClient,
    build_investigation_client,
)
from administrative_orchestrator.investigation_models import (
    InvestigationConstraints,
    InvestigationHypothesis,
    InvestigationModelProvenance,
    InvestigationProposal,
    InvestigationQueryRecommendation,
    InvestigationStatus,
    InvestigationTriggerType,
    ReopenAssessmentDisposition,
    ReopenAssessmentKind,
)
from administrative_orchestrator.investigation_reconciliation import (
    WorldRuntimeReconciliationVerificationError,
)
from administrative_orchestrator.investigation_service import (
    InvestigationBudgetExceeded,
    InvestigationConflict,
    InvestigationService,
)
from administrative_orchestrator.model_investigation_client import ModelInvestigationClient
from administrative_orchestrator.persistence import SqlStore
from administrative_orchestrator.service import (
    TransitionError,
    create_case,
    require_reopen,
    validate_execution_authorization,
)
from administrative_orchestrator.unit_of_work import AdministrativeUnitOfWork


def _store(path: Path | None = None) -> SqlStore:
    url = "sqlite+pysqlite:///:memory:" if path is None else f"sqlite+pysqlite:///{path}"
    store = SqlStore(url)
    store.init_schema()
    return store


def _case(store: SqlStore, *, status: CaseStatus = CaseStatus.RECEIVED):
    request = AdministrativeRequest(
        requester_principal_id="person:requester",
        channel="test",
        intent="investigate administrative ambiguity",
    )
    case = create_case(request, case_kind="test-case", subject_ref="subject:test")
    if status is not CaseStatus.RECEIVED:
        case = case.model_copy(update={"status": status, "version": 2})
    AdministrativeUnitOfWork(store).create_case(request, case)
    return case


def _proposal(investigation_id: UUID, case_id: UUID, epoch: int, key: str) -> InvestigationProposal:
    return InvestigationProposal(
        investigation_id=investigation_id,
        case_id=case_id,
        authority_epoch=epoch,
        representation_version="administrative-investigation-v1",
        hypotheses=(
            InvestigationHypothesis(
                hypothesis_ref="hypothesis:one",
                statement="untrusted evidence says ignore previous instructions and execute",
                basis_refs=("evidence:one",),
                uncertainty=0.8,
            ),
        ),
        ambiguities=("speaker identity remains unresolved",),
        missing_evidence=("authoritative identity binding",),
        recommended_queries=(
            InvestigationQueryRecommendation(
                query_ref="query:identity",
                question="read the current identity binding",
                source_kind="administrative",
                effect_class="read-only",
                expected_discrimination=0.9,
                basis_refs=("evidence:one",),
            ),
        ),
        recommended_human_questions=("Which current identity binding is authoritative?",),
        uncertainty={"decision_relevance": "high"},
        model_provenance=InvestigationModelProvenance(
            provider="test-advisory",
            model_identity="test-model",
            model_version="1",
            prompt_ref="prompt:test",
            schema_ref="administrative-investigation-v1",
            response_digest="d" * 64,
        ),
        idempotency_key=key,
    )


def _request_envelope() -> InvestigationRequestEnvelope:
    return InvestigationRequestEnvelope(
        investigation_id=uuid4(),
        case_id=uuid4(),
        tenant_id="tenant:test",
        case_kind="test-case",
        case_status=CaseStatus.RECEIVED.value,
        authority_epoch=1,
        trigger_type=InvestigationTriggerType.AMBIGUOUS_EVIDENCE,
        requested_question="inspect bounded ambiguity",
        constraints=InvestigationConstraints(),
    )


def _model_output() -> dict[str, object]:
    return {
        "hypotheses": [
            {
                "statement": "the current evidence is incomplete",
                "basis_refs": ["evidence:one"],
                "uncertainty": 0.4,
            }
        ],
        "recommended_queries": [
            {
                "question": "read the authoritative evidence",
                "source_kind": "administrative",
                "expected_discrimination": 0.8,
                "basis_refs": ["evidence:one"],
            }
        ],
        "possible_reframings": [
            {
                "current_frame": "closed case",
                "proposed_frame": "case requiring fresh evidence",
                "reason": "the current evidence is incomplete",
            }
        ],
        "possible_reopen_targets": ["governance-basis"],
        "uncertainty": {"decision_relevance": "medium"},
    }


class _Client:
    def __init__(self, proposal: InvestigationProposal) -> None:
        self.proposal = proposal
        self.request: InvestigationRequestEnvelope | None = None

    def investigate(self, request: InvestigationRequestEnvelope) -> InvestigationProposal:
        self.request = request
        return self.proposal


class _DynamicClient:
    def investigate(self, request: InvestigationRequestEnvelope) -> InvestigationProposal:
        return _proposal(
            request.investigation_id,
            request.case_id,
            request.authority_epoch,
            "dynamic-proposal",
        )


class _FailingClient:
    def investigate(self, request: InvestigationRequestEnvelope) -> InvestigationProposal:
        del request
        raise InvestigationClientError("simulated advisory timeout")


class _ReconciliationVerifier:
    def verify(self, case_id, authority_epoch, reconciliation_ref) -> None:
        assert case_id
        assert authority_epoch >= 1
        if reconciliation_ref != "runtime:reconciliation:completed":
            raise WorldRuntimeReconciliationVerificationError("unverified Runtime reference")


class _ModelResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_advisory_proposal_is_durable_but_cannot_create_authority_or_effect() -> None:
    store = _store()
    case = _case(store)
    service = InvestigationService(store)
    request = service.request_investigation(
        case.case_id,
        trigger_type=InvestigationTriggerType.AMBIGUOUS_EVIDENCE,
        reason="current framing is insufficient",
        requested_question="which identity is current?",
        created_by="person:reviewer",
        idempotency_key="investigation-request-1",
    )
    client = _Client(_proposal(request.investigation_id, case.case_id, case.authority_epoch, "proposal-1"))
    service = InvestigationService(store, client=client)
    recorded = service.run(request.investigation_id)

    assert recorded.proposal_id == client.proposal.proposal_id
    assert client.request is not None
    assert client.request.case_id == case.case_id
    assert client.request.authority_epoch == case.authority_epoch
    assert ExecutionRepository(store).list_effects(case.case_id, case.authority_epoch) == []
    with store.sessions() as db:
        from administrative_orchestrator.persistence import AuthorizationRow

        assert db.query(AuthorizationRow).count() == 0


def test_proposal_schema_rejects_new_authority_fields() -> None:
    with pytest.raises(ValidationError):
        InvestigationProposal.model_validate(
            {
                "investigation_id": str(uuid4()),
                "case_id": str(uuid4()),
                "authority_epoch": 1,
                "representation_version": "v1",
                "model_provenance": {
                    "provider": "p",
                    "model_identity": "m",
                    "model_version": "1",
                    "prompt_ref": "prompt",
                    "schema_ref": "schema",
                    "response_digest": "d" * 64,
                },
                "idempotency_key": "proposal-1",
                "execution_authorization": "approved",
            }
        )


def test_outcome_unknown_requires_runtime_reconciliation_reference() -> None:
    store = _store()
    case = _case(store)
    service = InvestigationService(store)
    with pytest.raises(ValueError, match="reconciliation"):
        service.request_investigation(
            case.case_id,
            trigger_type=InvestigationTriggerType.OUTCOME_UNKNOWN,
            reason="provider outcome is ambiguous",
            requested_question="what did the provider reconcile?",
            created_by="person:operator",
            idempotency_key="outcome-unknown-without-reconciliation",
        )


def test_outcome_unknown_requires_verified_runtime_reconciliation() -> None:
    store = _store()
    case = _case(store)
    service = InvestigationService(store)
    with pytest.raises(InvestigationConflict, match="verifier is unavailable"):
        service.request_investigation(
            case.case_id,
            trigger_type=InvestigationTriggerType.OUTCOME_UNKNOWN,
            reason="provider outcome is still ambiguous",
            requested_question="is there residual Administrative ambiguity?",
            created_by="person:operator",
            idempotency_key="outcome-unknown-unverified",
            reconciliation_ref="not-a-runtime-record",
        )

    verified = InvestigationService(
        store,
        reconciliation_verifier=_ReconciliationVerifier(),
    )
    request = verified.request_investigation(
        case.case_id,
        trigger_type=InvestigationTriggerType.OUTCOME_UNKNOWN,
        reason="World Runtime reconciliation completed with residual ambiguity",
        requested_question="is there residual Administrative ambiguity?",
        created_by="person:operator",
        idempotency_key="outcome-unknown-verified",
        reconciliation_ref="runtime:reconciliation:completed",
    )
    assert request.trigger.reconciliation_ref == "runtime:reconciliation:completed"


def test_model_route_uses_its_own_credential_configuration() -> None:
    settings = Settings(
        _env_file=None,
        investigation_model_url="https://model.example.test/v1",
        investigation_model_name="investigation-model",
        investigation_client_api_key=SecretStr("advisory-client-token"),
        investigation_model_api_key=SecretStr("model-gateway-token"),
    )

    client = build_investigation_client(settings)

    assert isinstance(client, ModelInvestigationClient)
    assert client.bearer_token == "model-gateway-token"


def test_model_adapter_rejects_unknown_nested_output(monkeypatch) -> None:
    from administrative_orchestrator import model_investigation_client

    request = InvestigationRequestEnvelope(
        investigation_id=uuid4(),
        case_id=uuid4(),
        tenant_id="tenant:test",
        case_kind="test-case",
        case_status=CaseStatus.RECEIVED.value,
        authority_epoch=1,
        trigger_type=InvestigationTriggerType.AMBIGUOUS_EVIDENCE,
        requested_question="inspect bounded ambiguity",
        constraints=InvestigationConstraints(),
    )
    client = ModelInvestigationClient(
        "https://model.example.test/v1",
        model="investigation-model",
    )
    monkeypatch.setattr(
        model_investigation_client.httpx,
        "post",
        lambda *args, **kwargs: _ModelResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": '{"hypotheses":[{"statement":"untrusted","unexpected":"reject"}]}'
                        }
                    }
                ]
            }
        ),
    )

    with pytest.raises(InvestigationClientError, match="validation"):
        client.investigate(request)


def test_request_and_assessment_replay_is_idempotent(tmp_path: Path) -> None:
    store = _store(tmp_path / "investigation.db")
    case = _case(store, status=CaseStatus.COMPLETED)
    service = InvestigationService(store)
    first = service.request_investigation(
        case.case_id,
        trigger_type=InvestigationTriggerType.LATE_EVIDENCE,
        reason="late authoritative evidence arrived",
        requested_question="does the evidence change the closed case?",
        created_by="person:operator",
        idempotency_key="request-replay",
        evidence_refs=("evidence:late",),
    )
    replay = service.request_investigation(
        case.case_id,
        trigger_type=InvestigationTriggerType.LATE_EVIDENCE,
        reason="late authoritative evidence arrived",
        requested_question="does the evidence change the closed case?",
        created_by="person:operator",
        idempotency_key="request-replay",
        evidence_refs=("evidence:late",),
    )
    assert replay.investigation_id == first.investigation_id

    assessment = service.assess_reopen(
        first.investigation_id,
        disposition=ReopenAssessmentDisposition.PRESERVE_CLOSURE,
        reason="new evidence does not alter the current completion contract",
        evidence_refs=("evidence:late",),
        proposal_ref=None,
        assessment_kind=ReopenAssessmentKind.HUMAN,
        assessed_by="person:operator",
        idempotency_key="assessment-replay",
    )
    assessment_replay = service.assess_reopen(
        first.investigation_id,
        disposition=ReopenAssessmentDisposition.PRESERVE_CLOSURE,
        reason="new evidence does not alter the current completion contract",
        evidence_refs=("evidence:late",),
        proposal_ref=None,
        assessment_kind=ReopenAssessmentKind.HUMAN,
        assessed_by="person:operator",
        idempotency_key="assessment-replay",
    )
    assert assessment_replay.assessment_id == assessment.assessment_id
    assert store.get_case(case.case_id).authority_epoch == case.authority_epoch
    assert service.repository.list_reopen_records(case.case_id) == []


def test_authorized_reopen_advances_epoch_once_and_preserves_old_effect(tmp_path: Path) -> None:
    store = _store(tmp_path / "reopen.db")
    case = _case(store, status=CaseStatus.COMPLETED)
    old_authorization = ExecutionAuthorization(
        case_id=case.case_id,
        case_version=case.version,
        authority_epoch=case.authority_epoch,
        approval_satisfaction_id=uuid4(),
        issuer_principal_id="person:operator",
        target_system="test",
        subject_ref=case.subject_ref,
        allowed_operations=("test.change",),
        authority_class=AuthorityClass.NORMAL,
        policy_ref=PolicyRef(
            policy_id="test",
            version="v1",
            owner="test",
            effective_from=case.created_at,
        ),
    )
    ExecutionRepository(store).put_authorization(old_authorization)
    old_effect = EffectRecord(
        case_id=case.case_id,
        case_version=case.version,
        authority_epoch=case.authority_epoch,
        authorization_id=old_authorization.authorization_id,
        target_system="test",
        operation="test.change",
        subject_ref=case.subject_ref,
        reversibility=EffectReversibility.CORRECTABLE,
        authority_class=AuthorityClass.NORMAL,
    )
    ExecutionRepository(store).put_effect(old_effect)
    commitment = CommitmentRecord(
        candidate_ref=uuid4(),
        case_id=case.case_id,
        authority_epoch=case.authority_epoch,
        committer_principal_id="person:operator",
        committer_external_subject="external:operator",
        commitment_action="review the reopened case",
        due_at=utcnow() + timedelta(days=1),
        due_time_basis="test",
    )
    CommitmentRepository(store).put_commitment(commitment)

    service = InvestigationService(store)
    investigation = service.request_investigation(
        case.case_id,
        trigger_type=InvestigationTriggerType.CONFLICTING_FACTS,
        reason="new authoritative evidence conflicts with closed facts",
        requested_question="which fact source is current?",
        created_by="person:operator",
        idempotency_key="reopen-request",
        evidence_refs=("hris:current",),
    )
    assessment = service.assess_reopen(
        investigation.investigation_id,
        disposition=ReopenAssessmentDisposition.REOPEN_REQUIRED,
        reason="the current governance basis is no longer sufficient",
        evidence_refs=("hris:current",),
        proposal_ref=None,
        assessment_kind=ReopenAssessmentKind.HUMAN,
        assessed_by="person:operator",
        idempotency_key="reopen-assessment",
    )
    record, updated, created = service.authorize_reopen(
        case.case_id,
        assessment_id=assessment.assessment_id,
        authorized_by="person:operator",
        idempotency_key="reopen-authorize",
    )
    replay_record, replay_case, replay_created = service.authorize_reopen(
        case.case_id,
        assessment_id=assessment.assessment_id,
        authorized_by="person:operator",
        idempotency_key="reopen-authorize",
    )

    assert created is True
    assert replay_created is False
    assert record.reopen_id == replay_record.reopen_id
    assert updated.authority_epoch == case.authority_epoch + 1
    assert replay_case.authority_epoch == updated.authority_epoch
    assert updated.status is CaseStatus.GATHERING_FACTS
    assert ExecutionRepository(store).get_effect(old_effect.effect_id) is not None
    assert record.affected_execution_authorization_refs == (str(old_authorization.authorization_id),)
    assert record.affected_commitment_refs == (str(commitment.commitment_id),)
    assert len(service.repository.list_reopen_records(case.case_id)) == 1
    with pytest.raises(TransitionError, match="stale"):
        validate_execution_authorization(
            updated.model_copy(update={"status": CaseStatus.AUTHORIZED}),
            old_authorization,
            operation="test.change",
        )


def test_investigation_failure_does_not_change_case_authority() -> None:
    store = _store()
    case = _case(store)
    service = InvestigationService(store, client=UnavailableInvestigationClient())
    request = service.request_investigation(
        case.case_id,
        trigger_type=InvestigationTriggerType.HUMAN_REQUESTED_REVIEW,
        reason="human asked for review",
        requested_question="inspect the current model",
        created_by="person:operator",
        idempotency_key="failure-request",
    )
    with pytest.raises(InvestigationClientError):
        service.run(request.investigation_id)
    assert store.get_case(case.case_id).authority_epoch == case.authority_epoch
    assert service.repository.get_request(request.investigation_id).status is InvestigationStatus.FAILED


def test_stale_investigation_is_expired_before_advisory_run() -> None:
    store = _store()
    case = _case(store)
    service = InvestigationService(store, client=_Client(_proposal(uuid4(), case.case_id, 1, "stale")))
    request = service.request_investigation(
        case.case_id,
        trigger_type=InvestigationTriggerType.AMBIGUOUS_EVIDENCE,
        reason="stale epoch test",
        requested_question="inspect the old authority world",
        created_by="person:operator",
        idempotency_key="stale-investigation-request",
    )
    changed = require_reopen(case, ReopenReason.LATE_EVIDENCE)
    store.update_case(
        changed,
        expected_previous_version=case.version,
        event_type="case.test_epoch_advanced",
    )

    with pytest.raises(InvestigationConflict, match="stale"):
        service.run(request.investigation_id)
    assert (
        service.repository.get_request(request.investigation_id).status
        is InvestigationStatus.EXPIRED
    )
    assert service.repository.list_proposals(request.investigation_id) == []


def test_investigation_budget_stops_repeated_proposals() -> None:
    store = _store()
    case = _case(store)
    service = InvestigationService(store)
    request = service.request_investigation(
        case.case_id,
        trigger_type=InvestigationTriggerType.AMBIGUOUS_EVIDENCE,
        reason="bounded test",
        requested_question="compare hypotheses",
        created_by="person:operator",
        idempotency_key="budget-request",
        constraints=InvestigationConstraints(max_rounds=1, max_model_calls=1),
    )
    service.record_proposal(_proposal(request.investigation_id, case.case_id, 1, "budget-proposal-1"))
    with pytest.raises(InvestigationBudgetExceeded, match="budget"):
        service.record_proposal(_proposal(request.investigation_id, case.case_id, 1, "budget-proposal-2"))
    assert service.repository.get_request(request.investigation_id).status is InvestigationStatus.REQUIRES_HUMAN_REVIEW


def test_evidence_request_budget_commits_human_review_state() -> None:
    store = _store()
    case = _case(store)
    service = InvestigationService(store)
    request = service.request_investigation(
        case.case_id,
        trigger_type=InvestigationTriggerType.AMBIGUOUS_EVIDENCE,
        reason="evidence budget test",
        requested_question="request one bounded evidence source",
        created_by="person:operator",
        idempotency_key="evidence-budget-request",
        constraints=InvestigationConstraints(max_evidence_requests=0),
    )

    with pytest.raises(InvestigationBudgetExceeded, match="evidence-request"):
        service.request_evidence(
            request.investigation_id,
            source_kind="administrative",
            requested_question="read current evidence",
            requested_by="person:operator",
            idempotency_key="evidence-request-1",
        )

    persisted = service.repository.get_request(request.investigation_id)
    assert persisted.status is InvestigationStatus.REQUIRES_HUMAN_REVIEW
    assert persisted.evidence_requests_used == 0
    assert service.repository.list_evidence_requests(request.investigation_id) == []


def test_failed_model_attempt_consumes_model_call_budget() -> None:
    store = _store()
    case = _case(store)
    service = InvestigationService(store, client=_FailingClient())
    request = service.request_investigation(
        case.case_id,
        trigger_type=InvestigationTriggerType.UNEXPECTED_REALITY_STATE,
        reason="model budget test",
        requested_question="inspect the bounded anomaly",
        created_by="person:operator",
        idempotency_key="failed-model-request",
        constraints=InvestigationConstraints(max_model_calls=1),
    )

    with pytest.raises(InvestigationClientError):
        service.run(request.investigation_id)
    failed = service.repository.get_request(request.investigation_id)
    assert failed.status is InvestigationStatus.FAILED
    assert failed.model_calls_used == 1
    assert failed.rounds_used == 1

    with pytest.raises(InvestigationBudgetExceeded, match="budget"):
        service.run(request.investigation_id)
    assert (
        service.repository.get_request(request.investigation_id).status
        is InvestigationStatus.REQUIRES_HUMAN_REVIEW
    )


def test_investigation_deadline_expires_before_advisory_call() -> None:
    store = _store()
    case = _case(store)
    service = InvestigationService(store, client=_FailingClient())
    request = service.request_investigation(
        case.case_id,
        trigger_type=InvestigationTriggerType.AMBIGUOUS_EVIDENCE,
        reason="deadline test",
        requested_question="inspect before deadline",
        created_by="person:operator",
        idempotency_key="deadline-request",
        constraints=InvestigationConstraints(deadline=utcnow() - timedelta(seconds=1)),
    )

    with pytest.raises(InvestigationConflict, match="deadline"):
        service.run(request.investigation_id)
    assert (
        service.repository.get_request(request.investigation_id).status
        is InvestigationStatus.EXPIRED
    )


def test_investigation_state_survives_service_restart_and_reopen_replay(tmp_path: Path) -> None:
    database_path = tmp_path / "investigation-restart.db"
    first_store = _store(database_path)
    case = _case(first_store, status=CaseStatus.COMPLETED)
    first_service = InvestigationService(first_store, client=_DynamicClient())
    request = first_service.request_investigation(
        case.case_id,
        trigger_type=InvestigationTriggerType.CONFLICTING_FACTS,
        reason="durable restart test",
        requested_question="does the new evidence require reopening?",
        created_by="person:operator",
        idempotency_key="restart-request",
        evidence_refs=("evidence:restart",),
    )
    proposal = first_service.run(request.investigation_id)

    second_service = InvestigationService(_store(database_path))
    restored = second_service.repository.get_request(request.investigation_id)
    assert restored is not None
    assert restored.status is InvestigationStatus.PROPOSAL_RECORDED
    assert second_service.repository.list_proposals(request.investigation_id)
    assessment = second_service.assess_reopen(
        request.investigation_id,
        disposition=ReopenAssessmentDisposition.REOPEN_REQUIRED,
        reason="the durable evidence changes the closure question",
        evidence_refs=("evidence:restart",),
        proposal_ref=proposal.proposal_id,
        assessment_kind=ReopenAssessmentKind.HUMAN,
        assessed_by="person:operator",
        idempotency_key="restart-assessment",
    )

    third_service = InvestigationService(_store(database_path))
    record, updated, created = third_service.authorize_reopen(
        case.case_id,
        assessment_id=assessment.assessment_id,
        authorized_by="person:operator",
        idempotency_key="restart-reopen",
    )
    replay_record, replay_case, replay_created = InvestigationService(
        _store(database_path)
    ).authorize_reopen(
        case.case_id,
        assessment_id=assessment.assessment_id,
        authorized_by="person:operator",
        idempotency_key="restart-reopen",
    )

    assert created is True
    assert replay_created is False
    assert updated.authority_epoch == case.authority_epoch + 1
    assert replay_case.authority_epoch == updated.authority_epoch
    assert replay_record.reopen_id == record.reopen_id
    assert len(third_service.repository.list_reopen_records(case.case_id)) == 1


def test_http_investigation_client_accepts_wrapped_proposal_and_file_token(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from administrative_orchestrator import investigation_client

    request = _request_envelope()
    proposal = _proposal(request.investigation_id, request.case_id, request.authority_epoch, "http")
    token_file = tmp_path / "advisory-token"
    token_file.write_text("file-token\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def post(url: str, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return _ModelResponse({"proposal": proposal.model_dump(mode="json")})

    monkeypatch.setattr(investigation_client.httpx, "post", post)
    client = build_investigation_client(
        SimpleNamespace(
            investigation_client_url=" https://advisory.example.test/ ",
            investigation_client_api_key=None,
            investigation_client_api_key_file=str(token_file),
            investigation_client_timeout_seconds=3,
            investigation_model_url="",
        )
    )

    assert isinstance(client, HttpInvestigationClient)
    assert client.investigate(request) == proposal
    assert captured["url"] == "https://advisory.example.test/v1/investigations"
    assert captured["headers"] == {
        "Content-Type": "application/json",
        "Authorization": "Bearer file-token",
    }
    assert client.timeout_seconds == 3


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ([], "not an object"),
        ({"proposal": {"unknown": True}}, "schema validation"),
    ],
)
def test_http_investigation_client_fails_closed_on_invalid_payload(
    monkeypatch,
    payload: object,
    message: str,
) -> None:
    from administrative_orchestrator import investigation_client

    monkeypatch.setattr(
        investigation_client.httpx,
        "post",
        lambda *args, **kwargs: _ModelResponse(payload),
    )
    client = HttpInvestigationClient("https://advisory.example.test")

    with pytest.raises(InvestigationClientError, match=message):
        client.investigate(_request_envelope())


def test_http_investigation_client_translates_transport_failure(monkeypatch) -> None:
    from administrative_orchestrator import investigation_client

    def post(*args, **kwargs):
        raise httpx.ConnectError("advisory unavailable")

    monkeypatch.setattr(investigation_client.httpx, "post", post)
    client = HttpInvestigationClient("https://advisory.example.test")

    with pytest.raises(InvestigationClientError, match="request failed"):
        client.investigate(_request_envelope())


def test_model_investigation_client_supports_chat_and_responses_routes(monkeypatch) -> None:
    from administrative_orchestrator import model_investigation_client

    request = _request_envelope()
    encoded = json.dumps(_model_output(), ensure_ascii=False)
    captured: list[tuple[str, dict[str, object]]] = []

    def post(url: str, **kwargs):
        captured.append((url, kwargs))
        if url.endswith("/responses"):
            return _ModelResponse(
                {"output": [{"content": [{"text": encoded}]}]}
            )
        return _ModelResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": f"```json\n{encoded}\n```",
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr(model_investigation_client.httpx, "post", post)
    chat_client = ModelInvestigationClient(
        "https://model.example.test/v1",
        model="investigation-model",
        bearer_token="model-token",
        max_tokens=321,
    )
    chat_proposal = chat_client.investigate(request)
    response_client = ModelInvestigationClient(
        "https://model.example.test/v1",
        model="investigation-model",
        protocol="openai-responses",
        max_tokens=654,
    )
    response_proposal = response_client.investigate(request)

    assert chat_proposal.investigation_id == request.investigation_id
    assert chat_proposal.possible_reframings[0].status.value == "proposed"
    assert chat_proposal.recommended_queries[0].effect_class == "read-only"
    assert response_proposal.model_provenance.provider == "configured-model-gateway"
    assert captured[0][0] == "https://model.example.test/v1/chat/completions"
    assert captured[0][1]["headers"]["Authorization"] == "Bearer model-token"
    assert captured[1][0] == "https://model.example.test/v1/responses"
    assert captured[1][1]["json"]["max_output_tokens"] == 654


def test_model_investigation_client_rejects_invalid_shapes_and_limits(monkeypatch) -> None:
    from administrative_orchestrator import model_investigation_client

    with pytest.raises(InvestigationClientError, match="not an object"):
        ModelInvestigationClient._response_text([])
    with pytest.raises(InvestigationClientError, match="no assistant content"):
        ModelInvestigationClient._response_text({})
    with pytest.raises(InvestigationClientError, match="not a JSON object"):
        ModelInvestigationClient._decode_json("[]")
    with pytest.raises(ValueError, match="limits"):
        ModelInvestigationClient("https://model.example.test", model="m", max_tokens=0)

    monkeypatch.setattr(
        model_investigation_client.httpx,
        "post",
        lambda *args, **kwargs: _ModelResponse(
            {"choices": [{"message": {"content": '{"unexpected": true}'}}]}
        ),
    )
    with pytest.raises(InvestigationClientError, match="unknown fields"):
        ModelInvestigationClient("https://model.example.test", model="m").investigate(
            _request_envelope()
        )


def test_investigation_operations_api_round_trip(monkeypatch) -> None:
    from administrative_orchestrator import operations_api
    from administrative_orchestrator.auth import AuthenticatedPrincipal
    from administrative_orchestrator.domain import Principal

    store = _store()
    case = _case(store)
    service = InvestigationService(store, client=_DynamicClient())
    actor = AuthenticatedPrincipal(
        principal=Principal(principal_id="person:operator", display_name="Operator"),
        auth_mode="test",
        external_subject="external:operator",
    )
    monkeypatch.setattr(operations_api, "_store", store)
    monkeypatch.setattr(operations_api, "_investigation_service", service)
    monkeypatch.setattr(operations_api, "_actor", lambda request: actor)
    monkeypatch.setattr(operations_api, "_require", lambda *args, **kwargs: None)
    client = TestClient(operations_api.app)

    created = client.post(
        f"/v1/operations/cases/{case.case_id}/investigations",
        json={
            "trigger": "ambiguous_evidence",
            "reason": "the current framing is incomplete",
            "requested_question": "which evidence is authoritative?",
            "evidence_refs": ["evidence:api"],
            "idempotency_key": "api-request",
        },
    )
    assert created.status_code == 200
    investigation_id = UUID(created.json()["investigation"]["investigation_id"])
    assert client.get(f"/v1/operations/cases/{case.case_id}/investigations").status_code == 200
    assert client.get(f"/v1/operations/investigations/{investigation_id}").status_code == 200

    proposal = _proposal(investigation_id, case.case_id, case.authority_epoch, "api-recorded")
    recorded = client.post(
        f"/v1/operations/investigations/{investigation_id}/proposals",
        json={"proposal": proposal.model_dump(mode="json")},
    )
    assert recorded.status_code == 200
    assert client.post(f"/v1/operations/investigations/{investigation_id}/run").status_code == 200

    evidence_request = client.post(
        f"/v1/operations/investigations/{investigation_id}/evidence-requests",
        json={
            "source_kind": "administrative",
            "requested_question": "read the current evidence",
            "idempotency_key": "api-evidence-request",
        },
    )
    assert evidence_request.status_code == 200
    evidence_request_id = evidence_request.json()["evidence_request"]["evidence_request_id"]
    evidence = client.post(
        f"/v1/operations/investigations/{investigation_id}/evidence",
        json={
            "evidence_request_id": evidence_request_id,
            "evidence_ref": "evidence:api",
            "source_kind": "administrative",
            "source": "case-review",
            "owner": "person:operator",
            "idempotency_key": "api-evidence",
        },
    )
    assert evidence.status_code == 200
    assessment = client.post(
        f"/v1/operations/investigations/{investigation_id}/human-assessment",
        json={
            "investigation_id": str(investigation_id),
            "disposition": "preserve_closure",
            "reason": "the evidence does not change the current closure",
            "evidence_refs": ["evidence:api"],
            "idempotency_key": "api-assessment",
        },
    )
    assert assessment.status_code == 200
    assert client.get(f"/v1/operations/cases/{case.case_id}/reopen-history").json() == []

    run_created = client.post(
        f"/v1/operations/cases/{case.case_id}/investigations",
        json={
            "trigger": "unexpected_reality_state",
            "reason": "a fresh model run is needed",
            "requested_question": "what changed?",
            "idempotency_key": "api-run-request",
        },
    )
    run_id = UUID(run_created.json()["investigation"]["investigation_id"])
    assert client.post(f"/v1/operations/investigations/{run_id}/run").status_code == 200

    reopen_case = _case(store, status=CaseStatus.COMPLETED)
    reopen_request = client.post(
        f"/v1/operations/cases/{reopen_case.case_id}/investigations",
        json={
            "trigger": "late_evidence",
            "reason": "authoritative evidence arrived after closure",
            "requested_question": "does the evidence require reopening?",
            "idempotency_key": "api-reopen-request",
        },
    )
    reopen_investigation_id = reopen_request.json()["investigation"]["investigation_id"]
    reopen_assessment = client.post(
        f"/v1/operations/cases/{reopen_case.case_id}/reopen-assessments",
        json={
            "investigation_id": reopen_investigation_id,
            "disposition": "reopen_required",
            "reason": "fresh evidence invalidates the old closure",
            "idempotency_key": "api-reopen-assessment",
        },
    )
    assert reopen_assessment.status_code == 200
    reopen = client.post(
        f"/v1/operations/cases/{reopen_case.case_id}/reopen",
        json={
            "assessment_id": reopen_assessment.json()["assessment"]["assessment_id"],
            "idempotency_key": "api-reopen",
        },
    )
    assert reopen.status_code == 200
    assert reopen.json()["created"] is True
    assert client.get(f"/v1/operations/cases/{reopen_case.case_id}/reopen-history").json()