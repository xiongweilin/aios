from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid5

import httpx
from sqlalchemy.exc import IntegrityError

from .authority import AuthorityRepository
from .commitment_cancellation import CommitmentCancellationCoordinator
from .commitment_common import (
    M9_NAMESPACE,
    REVIEW_ROLES,
    CommitmentIntakeError,
    ResponsibilityProvisioner,
    ResponsibilityRefs,
)
from .commitment_communication import CommitmentCommunicationCoordinator
from .commitment_due import CommitmentDueCoordinator
from .commitment_lifecycle import CommitmentLifecycleCoordinator
from .commitment_models import (
    CandidateCommitment,
    CandidateCommitmentClassification,
    CandidateCommitmentStatus,
    CommitmentFulfillmentKind,
    CommitmentRecord,
    CommitmentState,
    CommunicationDraftRecord,
    CommunicationEffectRecord,
    SpeakerPrincipalResolution,
)
from .commitment_repository import CommitmentConflict, CommitmentRepository
from .commitment_responsibility import WorldRuntimeCommitmentResponsibilityProvisioner
from .commitment_revision import CommitmentRevisionCoordinator
from .config import Settings, get_settings
from .domain import (
    AdministrativeCase,
    AdministrativeRequest,
    AuthorityClass,
    CaseStatus,
    Decision,
    DecisionDisposition,
    FactAuthority,
    FactSnapshot,
    utcnow,
)
from .execution_repository import ExecutionRepository
from .intake.artifacts import ArtifactStore, FilesystemArtifactStore
from .intake.interpretation import MeetingInterpretationPayload
from .intake.models import EvidenceSpan, InterpretationRecord
from .obligations import ObligationRepository
from .policy import AuthorizedEffectTemplate, PolicyDisposition, PolicyEvaluation
from .policy_plane import PolicyRepository, default_commitment_policy_version
from .service import apply_policy_evaluation, create_case, record_decision, start_policy_evaluation
from .unit_of_work import AdministrativeUnitOfWork

_M9_NAMESPACE = M9_NAMESPACE
_REVIEW_ROLES = REVIEW_ROLES


class MeetingCommitmentService:
    """M9 candidate qualification and commitment lifecycle boundary.

    Model output enters here as a candidate only. The service remains the
    stable public facade while bounded collaborators own communication and
    post-admission lifecycle mechanics.
    """

    def __init__(
        self,
        store,
        *,
        repository: CommitmentRepository | None = None,
        authority: AuthorityRepository | None = None,
        uow: AdministrativeUnitOfWork | None = None,
        policies: PolicyRepository | None = None,
        artifact_store: ArtifactStore | None = None,
        settings: Settings | None = None,
        responsibility_provisioner: ResponsibilityProvisioner | None = None,
    ) -> None:
        self.store = store
        self.repository = repository or CommitmentRepository(store)
        self.authority = authority or AuthorityRepository(store)
        self.uow = uow or AdministrativeUnitOfWork(store)
        self.policies = policies or PolicyRepository(store)
        settings = settings or get_settings()
        self.artifact_store = artifact_store or FilesystemArtifactStore(
            __import__("pathlib").Path(settings.intake_artifact_root)
        )
        self.settings = settings
        self.execution = ExecutionRepository(store)
        self.obligations = ObligationRepository(store)
        self.responsibility_provisioner = responsibility_provisioner
        if (
            self.responsibility_provisioner is None
            and settings.world_runtime_mode != "disabled"
        ):
            self.responsibility_provisioner = WorldRuntimeCommitmentResponsibilityProvisioner(
                store, settings=settings
            )

    def create_candidates_from_interpretation(
        self,
        interpretation: InterpretationRecord,
        *,
        source_artifact_ref: UUID | None = None,
        evidence_spans: Sequence[EvidenceSpan] = (),
    ) -> tuple[CandidateCommitment, ...]:
        if interpretation.interpretation_profile_ref != "meeting.commitment.v1":
            return ()
        if not interpretation.structured_output:
            return ()
        payload = MeetingInterpretationPayload.model_validate(interpretation.structured_output)
        artifact_ref = source_artifact_ref or interpretation.artifact_refs[0]
        available_spans = {item.evidence_span_id for item in evidence_spans}
        output: list[CandidateCommitment] = []
        for index, draft in enumerate(payload.candidate_commitments):
            refs = tuple(dict.fromkeys((*draft.evidence_span_refs, *interpretation.evidence_span_refs)))
            if not refs and len(evidence_spans) == 1:
                refs = (evidence_spans[0].evidence_span_id,)
            if not refs:
                raise CommitmentIntakeError(
                    "meeting commitment candidate requires at least one EvidenceSpan"
                )
            if available_spans and any(ref not in available_spans for ref in refs):
                raise CommitmentIntakeError("candidate references an unavailable EvidenceSpan")
            candidate = CandidateCommitment(
                candidate_commitment_id=uuid5(
                    _M9_NAMESPACE, f"candidate:{interpretation.interpretation_id}:{index}"
                ),
                source_artifact_ref=artifact_ref,
                interpretation_ref=interpretation.interpretation_id,
                evidence_span_refs=refs,
                candidate_committer_identity=draft.speaker_label,
                candidate_action=draft.candidate_action,
                candidate_due_text=draft.candidate_due_text,
                candidate_due_at=draft.candidate_due_at,
                candidate_scope_ref=draft.candidate_scope_ref,
                candidate_beneficiary=draft.candidate_beneficiary,
                classification=CandidateCommitmentClassification(draft.classification.value),
            )
            output.append(self.repository.put_candidate(candidate))
        return tuple(output)

    def resolve_speaker(
        self,
        candidate_id: UUID,
        *,
        reviewer_principal_id: str,
        external_subject: str,
        basis: dict[str, Any],
        provider: str,
    ) -> SpeakerPrincipalResolution:
        candidate = self._candidate(candidate_id)
        self._require_reviewer(reviewer_principal_id)
        external_subject = external_subject.strip()
        provider = provider.strip()
        if not external_subject or not provider or not basis:
            raise CommitmentIntakeError("speaker resolution requires provider, subject and basis")
        principal = self.authority.resolve_identity(
            provider=provider,
            external_subject=external_subject,
            at=utcnow(),
        )
        if principal is None:
            raise CommitmentIntakeError(
                "speaker identity is unresolved or has zero/multiple current bindings"
            )
        resolution = SpeakerPrincipalResolution(
            resolution_id=uuid5(_M9_NAMESPACE, f"resolution:{candidate_id}"),
            candidate_ref=candidate_id,
            source_speaker_identity=candidate.candidate_committer_identity,
            resolved_principal_id=principal.principal_id,
            provider=provider,
            external_subject=external_subject,
            basis={**basis, "reviewer_principal_id": reviewer_principal_id},
            resolver_type="authorized_human",
        )
        return self.repository.put_resolution(resolution)

    def confirm_candidate(
        self,
        candidate_id: UUID,
        *,
        reviewer_principal_id: str,
        qualified_due_at: datetime,
        due_time_basis: str,
        fulfillment_kind: CommitmentFulfillmentKind = CommitmentFulfillmentKind.AUTHORIZED_ATTESTATION,
    ) -> tuple[AdministrativeCase, CommitmentRecord]:
        self._require_reviewer(reviewer_principal_id)
        if qualified_due_at.tzinfo is None:
            raise CommitmentIntakeError("qualified due_at must be offset-aware")
        due_time_basis = due_time_basis.strip()
        if not due_time_basis:
            raise CommitmentIntakeError("qualified due time requires a basis")
        candidate = self._candidate(candidate_id)
        if candidate.classification is not CandidateCommitmentClassification.EXPLICIT_SELF_COMMITMENT:
            raise CommitmentIntakeError("only explicit self commitments may be admitted")
        resolution = self.repository.get_resolution(candidate_id)
        if resolution is None:
            raise CommitmentIntakeError("speaker principal resolution is required")
        existing = self.repository.get_commitment_for_candidate(candidate_id)
        if existing is not None:
            case = self.store.get_case(existing.case_id)
            if case is None:
                raise CommitmentConflict("commitment points to a missing case")
            if existing.due_at != qualified_due_at.astimezone(UTC):
                raise CommitmentConflict("candidate already has a different qualified due time")
            return case, existing

        policy = self._current_policy()
        evaluation = self._commitment_policy_evaluation(policy)
        due_at = qualified_due_at.astimezone(UTC)
        case_id = uuid5(_M9_NAMESPACE, f"case:{candidate_id}")
        request = AdministrativeRequest(
            request_id=uuid5(_M9_NAMESPACE, f"request:{candidate_id}"),
            requester_principal_id=resolution.resolved_principal_id,
            channel="meeting-intake",
            intent="meeting-commitment",
            source_ref=f"candidate-commitment:{candidate_id}",
        )
        snapshot = FactSnapshot(
            source="meeting.commitment.v1",
            owner="administrative-orchestrator",
            authority=FactAuthority.CLAIM,
            source_ref=f"interpretation:{candidate.interpretation_ref}",
            facts={
                "candidate_ref": str(candidate_id),
                "committer_principal_id": resolution.resolved_principal_id,
                "committer_external_subject": resolution.external_subject,
                "commitment_action": candidate.candidate_action,
                "due_at": due_at.isoformat(),
                "due_time_basis": due_time_basis,
                "source_artifact_ref": str(candidate.source_artifact_ref),
                "evidence_span_refs": [str(item) for item in candidate.evidence_span_refs],
            },
        )
        original = create_case(
            request,
            case_kind="meeting-commitment",
            subject_ref=f"commitment:{candidate_id}",
            fact_snapshot=snapshot,
        ).model_copy(update={"case_id": case_id})
        try:
            self.uow.create_case(request, original)
        except IntegrityError as exc:
            replayed = self.store.get_case(case_id)
            if replayed is None:
                raise CommitmentConflict("commitment admission conflicted") from exc
            original = replayed

        if original.status is CaseStatus.RECEIVED:
            ready = start_policy_evaluation(original)
            awaiting = apply_policy_evaluation(ready, evaluation)
            self.uow.apply_policy_transition(original, awaiting, evaluation)
            current = awaiting
        else:
            current = self.store.get_case(case_id) or original

        if current.status is CaseStatus.AWAITING_DECISION:
            decision = Decision(
                decision_id=uuid5(_M9_NAMESPACE, f"decision:{candidate_id}"),
                case_id=current.case_id,
                case_version=current.version,
                authority_epoch=current.authority_epoch,
                principal_id=reviewer_principal_id,
                decision_role="administrative_operator",
                disposition=DecisionDisposition.APPROVE,
                rationale="Human-qualified explicit self commitment",
                policy_ref=current.policy_ref,  # type: ignore[arg-type]
            )
            assessment = self._assess_approval(current, evaluation, decision)
            if not assessment.satisfied or assessment.satisfaction is None:
                raise CommitmentIntakeError("reviewer does not satisfy the commitment policy")
            authorized = record_decision(current, decision, approval_complete=True)
            self.uow.apply_decision_transition(
                current,
                authorized,
                decision,
                organization_scope="*",
                approval_satisfaction=assessment.satisfaction,
            )
            current = authorized
        elif current.status is not CaseStatus.AUTHORIZED:
            raise CommitmentIntakeError(
                f"commitment admission cannot continue from case status {current.status.value}"
            )

        current = self.store.get_case(case_id) or current
        governance = self.uow.governance.get_current_for_case(
            current.case_id, current.authority_epoch
        )
        if governance is None:
            raise CommitmentIntakeError("approved commitment has no governance basis")
        commitment = CommitmentRecord(
            commitment_id=uuid5(_M9_NAMESPACE, f"commitment:{candidate_id}"),
            candidate_ref=candidate_id,
            case_id=current.case_id,
            authority_epoch=current.authority_epoch,
            committer_principal_id=resolution.resolved_principal_id,
            committer_external_subject=resolution.external_subject,
            commitment_action=candidate.candidate_action,
            due_at=due_at,
            due_time_basis=due_time_basis,
            scope_ref=candidate.candidate_scope_ref,
            fulfillment_kind=fulfillment_kind,
            created_at=current.updated_at,
            updated_at=current.updated_at,
        )
        if self.responsibility_provisioner is not None:
            refs = self.responsibility_provisioner.provision(
                case=current,
                commitment=commitment,
                governance_basis=governance,
            )
            commitment = commitment.model_copy(
                update={
                    "responsibility_ref": refs.responsibility_ref,
                    "responsibility_version": refs.responsibility_version,
                    "responsibility_admission_ref": refs.admission_ref,
                    "responsibility_assessment_ref": refs.assessment_ref,
                    "responsibility_proposal_ref": refs.proposal_ref,
                }
            )
        commitment = self.repository.put_commitment(commitment)
        self.repository.update_candidate_status(
            candidate_id, status=CandidateCommitmentStatus.ADMITTED
        )
        self.ensure_communication(commitment, draft_kind="confirmation")
        return current, commitment

    def ensure_communication(
        self,
        commitment: CommitmentRecord,
        *,
        draft_kind: str,
    ) -> CommunicationEffectRecord:
        return self._communication().ensure(commitment, draft_kind=draft_kind)

    def attest_fulfillment(
        self,
        case_id: UUID,
        *,
        principal_id: str,
        basis: dict[str, Any],
        at: datetime | None = None,
    ) -> CommitmentRecord:
        return CommitmentLifecycleCoordinator(self).attest_fulfillment(
            case_id,
            principal_id=principal_id,
            basis=basis,
            at=at,
        )

    def drive(self, case_id: UUID, *, at: datetime | None = None) -> dict[str, Any]:
        return CommitmentDueCoordinator(self).drive(case_id, at=at)

    def dispatch_communication(self, communication_event_id: UUID) -> CommunicationEffectRecord:
        return self._communication().dispatch(communication_event_id)

    def _dispatch_communication_via_world_runtime(
        self,
        *,
        communication: CommunicationEffectRecord,
        draft: CommunicationDraftRecord,
    ) -> CommunicationEffectRecord:
        return self._communication().dispatch_via_world_runtime(
            communication=communication,
            draft=draft,
        )

    def discharge_responsibility(self, case_id: UUID) -> CommitmentRecord:
        commitment = self.repository.get_commitment(case_id)
        case = self.store.get_case(case_id)
        if commitment is None or case is None:
            raise CommitmentIntakeError("commitment case not found")
        if commitment.state is not CommitmentState.FULFILLED:
            raise CommitmentIntakeError("responsibility discharge requires fulfillment")
        if not commitment.responsibility_ref or commitment.responsibility_version is None:
            raise CommitmentIntakeError("World Runtime responsibility has not been provisioned")
        from .integrations.world_runtime import WorldRuntimeBridge

        bridge = WorldRuntimeBridge(self.store, self.settings)
        try:
            status = bridge.responsibility_status(commitment.responsibility_ref)
            if status == "discharged":
                return commitment
            if status != "active":
                raise CommitmentIntakeError(
                    f"Runtime responsibility is not active: {status}"
                )
            root = f"{commitment.commitment_id}:{commitment.version}"
            decision_ref = (
                f"m9discharge_decision_"
                f"{uuid5(_M9_NAMESPACE, root + ':decision').hex}"
            )
            basis_refs = (
                f"commitment:{commitment.commitment_id}",
                f"fulfillment-attestation:{case_id}",
            )
            assessment_ref, decision_ref, transition_ref = (
                bridge.discharge_responsibility(
                    commitment.responsibility_ref,
                    decision_ref=decision_ref,
                    decided_by="service:administrative-orchestrator",
                    subject_ref=commitment.committer_principal_id,
                    basis_refs=basis_refs,
                )
            )
        finally:
            bridge.close()
        updated = commitment.model_copy(
            update={
                "responsibility_discharge_assessment_ref": assessment_ref,
                "responsibility_discharge_decision_ref": decision_ref,
                "responsibility_transition_ref": transition_ref,
                "updated_at": utcnow(),
            }
        )
        return self.repository.update_commitment(updated)

    def _communication_secret(self) -> str:
        return self._communication().communication_secret()

    def revise_due_at(
        self,
        case_id: UUID,
        *,
        reviewer_principal_id: str,
        due_at: datetime,
        basis: str,
    ) -> CommitmentRecord:
        return CommitmentRevisionCoordinator(self).revise_due_at(
            case_id,
            reviewer_principal_id=reviewer_principal_id,
            due_at=due_at,
            basis=basis,
        )

    def cancel_commitment(
        self,
        case_id: UUID,
        *,
        reviewer_principal_id: str,
        basis: str,
    ) -> CommitmentRecord:
        return CommitmentCancellationCoordinator(self).cancel_commitment(
            case_id,
            reviewer_principal_id=reviewer_principal_id,
            basis=basis,
        )

    @staticmethod
    def _commitment_policy_evaluation(policy) -> PolicyEvaluation:
        return PolicyEvaluation(
            policy_ref=policy.policy_ref,
            disposition=PolicyDisposition.HUMAN_DECISION_REQUIRED,
            reason="M9 commitment admission requires an authorized human decision",
            required_decision_roles=("administrative_operator",),
            allowed_effects=(
                AuthorizedEffectTemplate(
                    target_system="communication",
                    operation="message.send",
                    authority_class=AuthorityClass.NORMAL,
                ),
            ),
        )

    def _current_policy(self):
        try:
            return self.policies.resolve_current("meeting-commitment")
        except Exception:
            record = default_commitment_policy_version()
            self.policies.put_version(record)
            return record

    def _assess_approval(
        self,
        case: AdministrativeCase,
        evaluation: PolicyEvaluation,
        decision: Decision,
    ):
        from .authority import assess_approval_satisfaction

        return assess_approval_satisfaction(
            self.authority,
            case_id=case.case_id,
            authority_epoch=case.authority_epoch,
            policy_ref=case.policy_ref,  # type: ignore[arg-type]
            evaluation=evaluation,
            decisions=(decision,),
            organization_scope="*",
        )

    def _require_reviewer(self, principal_id: str) -> None:
        principal = self.authority.get_principal(principal_id)
        roles = self.authority.roles_for(principal_id, organization_scope="*")
        if principal is None or not roles.intersection(_REVIEW_ROLES):
            raise PermissionError(
                f"principal {principal_id} lacks an M9 commitment review role"
            )

    def _candidate(self, candidate_id: UUID) -> CandidateCommitment:
        candidate = self.repository.get_candidate(candidate_id)
        if candidate is None:
            raise CommitmentIntakeError("meeting commitment candidate not found")
        if candidate.status in {
            CandidateCommitmentStatus.REJECTED,
            CandidateCommitmentStatus.SUPERSEDED,
        }:
            raise CommitmentIntakeError("candidate is no longer admissible")
        return candidate

    def _communication(self) -> CommitmentCommunicationCoordinator:
        return CommitmentCommunicationCoordinator(
            self.store,
            repository=self.repository,
            uow=self.uow,
            artifact_store=self.artifact_store,
            settings=self.settings,
            execution=self.execution,
            obligations=self.obligations,
            http_post=httpx.post,
        )

    @staticmethod
    def _communication_text(commitment: CommitmentRecord, draft_kind: str) -> str:
        return CommitmentCommunicationCoordinator.communication_text(commitment, draft_kind)


__all__ = [
    "CommitmentIntakeError",
    "WorldRuntimeCommitmentResponsibilityProvisioner",
    "MeetingCommitmentService",
    "ResponsibilityProvisioner",
    "ResponsibilityRefs",
]
