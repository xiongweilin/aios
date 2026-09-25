from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from .config import get_settings
from .domain import (
    AdministrativeCase,
    CaseStatus,
    ConfirmedOutcome,
    EffectRealizationAssessment,
    EffectStatus,
    EvidenceRef,
    RealizationDisposition,
)
from .effect_provider import ProviderExecutionStatus
from .execution_transitions import (
    begin_reconciliation,
    complete_verified_case,
    fail_execution,
    resume_verification,
)
from .service import TransitionError, begin_execution, begin_verification
from .verification import VerificationDisposition

if TYPE_CHECKING:
    from .onboarding_execution import OnboardingExecutionEngine


class VerifiedObligationExecutor:
    """Drive the generic verified-effect lifecycle through domain-owned hooks.

    This collaborator owns only the post-authorization execution state machine,
    effect dispatch/reconciliation, realization evidence, and confirmed outcome
    recording. The owner retains domain planning, semantic verification,
    completion interpretation, ordering/payload dependencies, and reopen policy.
    """

    def __init__(self, owner: OnboardingExecutionEngine) -> None:
        self.owner = owner

    def run(self, case_id: UUID) -> AdministrativeCase:
        owner = self.owner
        case = owner._require_case(case_id)
        if case.status in {CaseStatus.COMPLETED, CaseStatus.CANCELLED, CaseStatus.FAILED}:
            return case
        if case.status in {
            CaseStatus.RECEIVED,
            CaseStatus.GATHERING_FACTS,
            CaseStatus.READY_FOR_POLICY,
            CaseStatus.AWAITING_DECISION,
            CaseStatus.REOPEN_REQUIRED,
            CaseStatus.WAITING,
        }:
            return case

        governance = owner._validate_current_governance(case)
        if governance is not None and not governance.valid:
            return owner._reopen_for_governance(case, governance)

        if case.status == CaseStatus.AUTHORIZED:
            owner._plan_current_effects(case)
            executing = begin_execution(case)
            owner._persist_case_transition(case, executing, "case.execution_started")
            case = executing

        effects = owner.repository.list_effects(case.case_id, case.authority_epoch)
        if not effects:
            # Preserve the historical message while the public execution
            # engines retain their existing compatibility surface.
            raise TransitionError("authorized onboarding case has no planned effects")

        obligation_set = owner.obligations.get_current(case.case_id, case.authority_epoch)
        links = owner.obligations.list_links(case.case_id, case.authority_epoch)

        if case.status == CaseStatus.EXECUTING:
            dispatch_state = owner._drive_dispatch(case, effects, obligation_set, links)
            case = owner._require_case(case_id)
            if dispatch_state == "failed":
                failed = fail_execution(case)
                owner._persist_case_transition(
                    case,
                    failed,
                    "case.execution_failed",
                    {"reason": "one or more effects failed definitively"},
                )
                return failed
            if dispatch_state == "outcome_unknown":
                reconciling = begin_reconciliation(case)
                owner._persist_case_transition(
                    case,
                    reconciling,
                    "case.reconciliation_started",
                    {"reason": "one or more effect outcomes are unknown or not observable"},
                )
                case = reconciling
            else:
                verifying = begin_verification(case)
                owner._persist_case_transition(case, verifying, "case.verification_started")
                case = verifying

        governance = owner._validate_current_governance(case)
        if governance is not None and not governance.valid:
            return owner._reopen_for_governance(case, governance)

        if case.status == CaseStatus.RECONCILING:
            result = owner._verify_all(case, effects, obligation_set, links)
            if result == "mismatch":
                return owner._reopen_for_mismatch(case)
            if result == "incomplete":
                return owner._require_case(case_id)
            resumed = resume_verification(case)
            owner._persist_case_transition(case, resumed, "case.reconciliation_resolved")
            case = resumed

        if case.status == CaseStatus.VERIFYING:
            result = owner._verify_all(case, effects, obligation_set, links)
            if result == "mismatch":
                return owner._reopen_for_mismatch(case)
            if result == "incomplete":
                reconciling = begin_reconciliation(case)
                owner._persist_case_transition(
                    case,
                    reconciling,
                    "case.reconciliation_started",
                    {"reason": "fresh authoritative read-back did not verify every obligation"},
                )
                return reconciling

            governance = owner._validate_current_governance(case)
            if governance is not None and not governance.valid:
                return owner._reopen_for_governance(case, governance)

            outcomes = owner.repository.list_outcomes(case.case_id, case.authority_epoch)
            realizations = owner.repository.list_realizations(
                case.case_id, case.authority_epoch
            )
            if obligation_set is None:
                if get_settings().authority_enforcement_enabled:
                    raise TransitionError("governed completion requires an obligation set")
                completion = owner._assess_completion_without_obligations(
                    effects,
                    outcomes,
                    realizations,
                )
            else:
                completion = owner._assess_completion(
                    obligation_set, effects, outcomes, realizations, links
                )
            if not completion.satisfied:
                return owner._handle_completion_blocked(case, completion)

            completed = complete_verified_case(
                case,
                expected_effect_count=len(effects),
                verified_outcome_count=len(outcomes),
            )
            owner._persist_case_transition(
                case,
                completed,
                "case.completed",
                {
                    "completion_requirement_id": completion.requirement_id,
                    "governance_basis_id": (
                        str(completion.governance_basis_id)
                        if completion.governance_basis_id
                        else None
                    ),
                },
            )
            return completed

        return owner._require_case(case_id)

    def drive_dispatch(self, case, effects, obligation_set, links) -> str:
        owner = self.owner
        payload = case.fact_snapshot.facts if case.fact_snapshot else {}
        saw_unknown = False
        for planned in sorted(effects, key=owner._effect_dispatch_order):
            effect = owner.repository.get_effect(planned.effect_id) or planned
            obligation = owner._obligation_for_effect(effect.effect_id, obligation_set, links)
            if effect.status == EffectStatus.FAILED:
                return "failed"
            if effect.status == EffectStatus.SUCCEEDED:
                continue
            if effect.status in {EffectStatus.DISPATCHED, EffectStatus.OUTCOME_UNKNOWN}:
                observation = owner.provider.observe(effect)
                verification = owner._verify_observation(
                    case,
                    effect,
                    observation,
                    payload,
                    expected_postcondition=(
                        obligation.expected_postcondition if obligation is not None else None
                    ),
                )
                if verification.disposition == VerificationDisposition.VERIFIED:
                    owner.repository.set_effect_status(
                        effect.effect_id,
                        status=EffectStatus.SUCCEEDED,
                        provider_ref=observation.provider_ref,
                    )
                    continue
                if verification.disposition == VerificationDisposition.MISMATCH:
                    owner.repository.set_effect_status(
                        effect.effect_id,
                        status=EffectStatus.OUTCOME_UNKNOWN,
                        provider_ref=observation.provider_ref,
                    )
                    saw_unknown = True
                    continue
                if verification.disposition in {
                    VerificationDisposition.UNAVAILABLE,
                    VerificationDisposition.UNKNOWN,
                    VerificationDisposition.STALE,
                }:
                    saw_unknown = True
                    continue
                if effect.status == EffectStatus.OUTCOME_UNKNOWN:
                    # Even authoritative ABSENT is not permission to blindly
                    # repeat an effect whose prior provider outcome was unknown.
                    saw_unknown = True
                    continue

            owner.repository.set_effect_status(effect.effect_id, status=EffectStatus.DISPATCHED)
            dispatch_payload = owner._payload_for_effect(effect, effects, payload)
            if dispatch_payload is None:
                saw_unknown = True
                continue
            result = owner.provider.execute(effect, dispatch_payload)
            if result.status == ProviderExecutionStatus.SUCCEEDED:
                owner.repository.set_effect_status(
                    effect.effect_id,
                    status=EffectStatus.SUCCEEDED,
                    provider_ref=result.provider_ref,
                )
            elif result.status == ProviderExecutionStatus.OUTCOME_UNKNOWN:
                owner.repository.set_effect_status(
                    effect.effect_id,
                    status=EffectStatus.OUTCOME_UNKNOWN,
                    provider_ref=result.provider_ref,
                )
                saw_unknown = True
            else:
                owner.repository.set_effect_status(
                    effect.effect_id,
                    status=EffectStatus.FAILED,
                    provider_ref=result.provider_ref,
                )
                return "failed"
        return "outcome_unknown" if saw_unknown else "succeeded"

    def verify_all(self, case, effects, obligation_set, links) -> str:
        owner = self.owner
        incomplete = False
        facts = case.fact_snapshot.facts if case.fact_snapshot else {}
        for planned in effects:
            effect = owner.repository.get_effect(planned.effect_id) or planned
            obligation = owner._obligation_for_effect(effect.effect_id, obligation_set, links)
            if obligation_set is not None and obligation is None:
                return "mismatch"

            outcome_id = owner._stable_id("outcome", case, str(effect.effect_id))
            existing_outcome = owner.repository.get_outcome(outcome_id)
            if existing_outcome is not None:
                if (
                    existing_outcome.case_id != case.case_id
                    or existing_outcome.authority_epoch != case.authority_epoch
                    or existing_outcome.effect_id != effect.effect_id
                ):
                    raise TransitionError("persisted outcome does not match current effect authority")
                continue

            realization_id = owner._stable_id("realization", case, str(effect.effect_id))
            existing_realization = owner.repository.get_realization(realization_id)
            if existing_realization is not None:
                if (
                    existing_realization.effect_id != effect.effect_id
                    or existing_realization.disposition != RealizationDisposition.VERIFIED
                ):
                    raise TransitionError("persisted realization does not verify the current effect")
                owner.repository.put_outcome(
                    ConfirmedOutcome(
                        outcome_id=outcome_id,
                        case_id=case.case_id,
                        case_version=effect.case_version,
                        authority_epoch=case.authority_epoch,
                        effect_id=effect.effect_id,
                        realization_assessment_id=existing_realization.assessment_id,
                        outcome_kind=f"{effect.target_system}.{effect.operation}.verified",
                        evidence=existing_realization.evidence,
                        confirmed_at=existing_realization.assessed_at,
                    )
                )
                continue

            observation = owner.provider.observe(effect)
            verification = owner._verify_observation(
                case,
                effect,
                observation,
                facts,
                expected_postcondition=(
                    obligation.expected_postcondition if obligation is not None else None
                ),
            )
            if verification.disposition == VerificationDisposition.MISMATCH:
                return "mismatch"
            if verification.disposition != VerificationDisposition.VERIFIED:
                incomplete = True
                continue

            evidence = EvidenceRef(
                evidence_id=owner._stable_id("evidence", case, str(effect.effect_id)),
                source=f"reality:{effect.target_system}",
                owner=effect.target_system,
                observed_at=observation.observed_at,
                version=observation.provider_ref,
                digest=observation.digest,
                metadata={
                    "state": observation.state,
                    "availability": observation.availability.value,
                    "presence": observation.presence.value,
                    "freshness": observation.freshness.value,
                    "semantic_verification": verification.model_dump(mode="json"),
                    "obligation_id": (
                        str(obligation.obligation_id) if obligation is not None else None
                    ),
                    "governance_basis_id": (
                        str(obligation.governance_basis_id) if obligation is not None else None
                    ),
                },
            )
            assessment = EffectRealizationAssessment(
                assessment_id=realization_id,
                effect_id=effect.effect_id,
                disposition=RealizationDisposition.VERIFIED,
                evidence=[evidence],
                assessed_at=observation.observed_at,
            )
            assessment = owner.repository.put_realization(assessment, case_id=case.case_id)
            outcome = ConfirmedOutcome(
                outcome_id=outcome_id,
                case_id=case.case_id,
                case_version=effect.case_version,
                authority_epoch=case.authority_epoch,
                effect_id=effect.effect_id,
                realization_assessment_id=assessment.assessment_id,
                outcome_kind=f"{effect.target_system}.{effect.operation}.verified",
                evidence=assessment.evidence,
                confirmed_at=assessment.assessed_at,
            )
            owner.repository.put_outcome(outcome)
        return "incomplete" if incomplete else "verified"


__all__ = ["VerifiedObligationExecutor"]
