from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, ClassVar

from pydantic import BaseModel

from .admission import IntakePromotionService, PromotionResult
from .domain import AdministrativeCase, FactAssertion, FactAuthority, FactSnapshot
from .intake.models import CandidateAdministrativeRequest, IntakeAssessment
from .intake.repository import IntakeRepository
from .persistence import ConcurrencyConflict, SqlStore
from .policy import PolicyEvaluation
from .policy_plane import PolicyRepository
from .service import (
    TransitionError,
    apply_policy_evaluation,
    replace_fact_snapshot,
    start_policy_evaluation,
)
from .unit_of_work import AdministrativeUnitOfWork


class CandidateAdmissionError(ValueError):
    """Candidate data cannot safely enter the requested Administrative case kind."""


@dataclass(frozen=True, slots=True)
class CandidateAdmissionResult:
    promotion: PromotionResult
    case: AdministrativeCase
    policy_evaluation: PolicyEvaluation
    created: bool


class CandidateAdministrativeAdmissionService:
    """Bridge an admitted candidate into a typed Administrative case kind.

    This bridge keeps candidate claims as FactAuthority.CLAIM. Human admission
    authorizes the request/case transition; it does not turn an inbox
    interpretation into an authoritative system-of-record fact.

    Subclasses own the candidate fact contract, the policy they evaluate, and
    the persisted case kind they create.
    """

    case_kind: ClassVar[str] = 'employee-onboarding'
    policy_id: ClassVar[str] = 'employee-onboarding'
    description: ClassVar[str] = 'onboarding'
    error_type: ClassVar[type[ValueError]] = CandidateAdmissionError
    snapshot_source_version: ClassVar[str] = 'administrative-human-confirmed-v1'

    def __init__(
        self,
        store: SqlStore,
        repository: IntakeRepository,
        promotions: IntakePromotionService | None = None,
        *,
        policies: PolicyRepository | None = None,
        uow: AdministrativeUnitOfWork | None = None,
    ) -> None:
        self.store = store
        self.repository = repository
        self.promotions = promotions or IntakePromotionService(store, repository)
        self.policies = policies or PolicyRepository(store)
        self.uow = uow or AdministrativeUnitOfWork(store)

    def _fail(self, message: str) -> ValueError:
        return self.error_type(message)

    def promote_and_evaluate(
        self,
        candidate: CandidateAdministrativeRequest,
        assessment: IntakeAssessment,
        *,
        source_system: str,
        tenant_ref: str,
        source_event_id: str,
        requester_principal_id: str,
        subject_ref: str,
        channel: str = 'intake',
        promotion_policy_ref: str = 'm6-human-confirmed-v1',
    ) -> CandidateAdmissionResult:
        subject_ref = subject_ref.strip()
        if not subject_ref:
            raise self._fail(
                f"{self.case_kind} promotion requires a non-blank subject_ref"
            )

        # Validate the candidate facts against the case kind contract before
        # any promotion/request/case row exists so a rejected candidate leaves
        # no partial state behind.
        facts = self._candidate_facts(candidate, subject_ref=subject_ref)

        promotion = self.promotions.promote(
            candidate,
            assessment,
            source_system=source_system,
            tenant_ref=tenant_ref,
            source_event_id=source_event_id,
            requester_principal_id=requester_principal_id,
            channel=channel,
            case_kind=self.case_kind,
            subject_ref=subject_ref,
            promotion_policy_ref=promotion_policy_ref,
        )

        current = self.store.get_case(promotion.case.case_id)
        if current is None:
            raise self._fail("promotion created a case that cannot be reloaded")
        existing_evaluation = self.store.get_latest_policy_evaluation(current.case_id)
        if existing_evaluation is not None:
            return CandidateAdmissionResult(
                promotion=promotion,
                case=current,
                policy_evaluation=existing_evaluation,
                created=promotion.created,
            )

        snapshot = self._fact_snapshot(
            candidate,
            assessment,
            facts,
            source_system=source_system,
            source_event_id=source_event_id,
        )
        changed = replace_fact_snapshot(current, snapshot)
        ready = start_policy_evaluation(changed)
        policy_record = self.policies.resolve_current(self.policy_id)
        evaluation = self._compile_policy(policy_record).evaluate(facts)
        updated = apply_policy_evaluation(ready, evaluation)
        try:
            self.uow.replace_facts_and_apply_policy(current, updated, evaluation)
        except (ConcurrencyConflict, TransitionError, ValueError) as exc:
            replayed = self.store.get_latest_policy_evaluation(current.case_id)
            if replayed is None:
                raise
            stored = self.store.get_case(current.case_id)
            if stored is None:
                raise self._fail(
                    f"{self.description} policy transition committed without a readable case"
                ) from exc
            return CandidateAdmissionResult(
                promotion=promotion,
                case=stored,
                policy_evaluation=replayed,
                created=promotion.created,
            )
        return CandidateAdmissionResult(
            promotion=promotion,
            case=updated,
            policy_evaluation=evaluation,
            created=promotion.created,
        )

    def _candidate_facts(
        self, candidate: CandidateAdministrativeRequest, *, subject_ref: str
    ) -> BaseModel:
        raise NotImplementedError

    def _compile_policy(self, record: Any) -> Any:
        raise NotImplementedError

    def _fact_snapshot(
        self,
        candidate: CandidateAdministrativeRequest,
        assessment: IntakeAssessment,
        facts: BaseModel,
        *,
        source_system: str,
        source_event_id: str,
    ) -> FactSnapshot:
        source = f'intake:{source_system}'
        source_ref = f'intake:{source_system}/{source_event_id}'
        owner = assessment.reviewer_principal_id or 'service:administrative-orchestrator'
        candidate_assertions = {
            assertion.fact_key: assertion
            for assertion in self.repository.list_candidate_facts(candidate.candidate_id)
        }
        flattened = facts.model_dump(mode='json')
        assertions: dict[str, FactAssertion] = {}
        for key, value in flattened.items():
            candidate_assertion = candidate_assertions.get(key)
            assertions[key] = FactAssertion(
                value=value,
                authority=FactAuthority.CLAIM,
                source=source,
                owner=owner,
                source_ref=(
                    f'candidate-fact:{candidate_assertion.candidate_fact_id}'
                    if candidate_assertion is not None
                    else source_ref
                ),
                source_version=(
                    str(candidate_assertion.interpretation_ref)
                    if candidate_assertion is not None
                    and candidate_assertion.interpretation_ref is not None
                    else self.snapshot_source_version
                ),
                observed_at=assessment.created_at,
                digest=_value_digest(value),
            )
        return FactSnapshot(
            source=source,
            owner=owner,
            authority=FactAuthority.CLAIM,
            source_ref=source_ref,
            source_version=self.snapshot_source_version,
            observed_at=assessment.created_at,
            facts=flattened,
            assertions=assertions,
            digest=_snapshot_digest(flattened, assertions),
        )


def _value_digest(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(',', ':'), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _snapshot_digest(facts: dict[str, Any], assertions: dict[str, FactAssertion]) -> str:
    payload = {
        'facts': facts,
        'assertions': {
            key: assertion.model_dump(mode='json')
            for key, assertion in sorted(assertions.items())
        },
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


__all__ = [
    "CandidateAdministrativeAdmissionService",
    "CandidateAdmissionError",
    "CandidateAdmissionResult",
]

