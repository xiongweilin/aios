from __future__ import annotations

from uuid import NAMESPACE_URL, UUID, uuid5

from .authority import AuthorityRepository
from .completion import assess_administrative_completion, assess_onboarding_completion
from .config import get_settings
from .domain import (
    AdministrativeCase,
    DecisionDisposition,
    EffectStatus,
    ReopenReason,
)
from .effect_provider import EffectProvider
from .execution_repository import ExecutionRepository
from .execution_transitions import begin_reconciliation
from .financial import TransactionQualificationResult
from .financial_obligations import derive_financial_obligations
from .governance import GovernanceRepository, GovernanceValidation
from .obligations import (
    AdministrativeObligation,
    ObligationRepository,
    OnboardingObligationSet,
)
from .onboarding_obligations import derive_onboarding_obligations
from .persistence import SqlStore
from .service import (
    TransitionError,
    mint_execution_authorization,
    mint_execution_authorization_from_approval,
    plan_effect,
    require_reopen,
)
from .transaction_repository import TransactionRecordConflict, TransactionRepository
from .verification import verify_financial_observation, verify_onboarding_observation
from .verified_obligation_execution import VerifiedObligationExecutor


class FinancialQualificationPending(TransitionError):
    """Execution is authorized but must wait for current qualification evidence."""

    def __init__(self, missing: tuple[str, ...]) -> None:
        self.missing = missing
        super().__init__(
            "financial execution requires current qualified assessments: "
            + ", ".join(missing)
        )


class OnboardingExecutionEngine:
    """Recoverable onboarding driver over governed domain facts and reality."""

    def __init__(self, store: SqlStore, provider: EffectProvider) -> None:
        self.store = store
        self.repository = ExecutionRepository(store)
        self.provider = provider
        self.authority = AuthorityRepository(store)
        self.governance = GovernanceRepository(store)
        self.obligations = ObligationRepository(store)
        self._verified_executor = VerifiedObligationExecutor(self)

    def run(self, case_id: UUID) -> AdministrativeCase:
        try:
            return self._verified_executor.run(case_id)
        except FinancialQualificationPending:
            # Qualification is an expected asynchronous prerequisite. Keep
            # the authorization intact and let the durable workflow wait;
            # the qualification repository emits a case_changed wake-up
            # when the evidence is committed.
            return self._require_case(case_id)

    def _plan_current_effects(self, case: AdministrativeCase) -> None:
        if case.fact_snapshot is None:
            raise TransitionError("onboarding execution requires a current fact snapshot")
        if case.case_kind in {
            "procurement-request",
            "invoice-ap-preparation",
        }:
            self._require_financial_qualifications(case)
        evaluation = self.store.get_latest_policy_evaluation(case.case_id)
        if evaluation is None or evaluation.policy_ref != case.policy_ref:
            raise TransitionError("onboarding execution requires the current policy evaluation")

        satisfaction = self.authority.get_approval_satisfaction(
            case.case_id,
            case.authority_epoch,
        )
        decision = None
        governance_basis_id: UUID
        if satisfaction is not None:
            if satisfaction.policy_ref != case.policy_ref:
                raise TransitionError("approval satisfaction policy is stale")
            required_roles = set(evaluation.required_decision_roles)
            if not required_roles.issubset(set(satisfaction.satisfied_roles)):
                raise TransitionError(
                    "approval satisfaction does not cover current required decision roles"
                )
            basis = self.governance.get_for_approval(satisfaction.satisfaction_id)
            if basis is None:
                if get_settings().authority_enforcement_enabled:
                    raise TransitionError("governed execution requires a governance basis")
                governance_basis_id = self._stable_id("legacy-governance", case)
            else:
                validation = self.governance.revalidate(basis, case)
                if not validation.valid:
                    raise TransitionError(
                        "governance basis is stale: " + "; ".join(validation.reasons)
                    )
                if case.case_kind in {
                    "procurement-request",
                    "invoice-ap-preparation",
                }:
                    basis = self.governance.bind_current_transaction_qualifications(basis, case)
                governance_basis_id = basis.basis_id
        else:
            if get_settings().authority_enforcement_enabled:
                raise TransitionError("governed execution requires current approval satisfaction")
            decision = self.repository.get_latest_decision(case.case_id)
            if decision is None:
                raise TransitionError("onboarding execution requires an approving decision")
            if decision.disposition != DecisionDisposition.APPROVE:
                raise TransitionError("latest onboarding decision is not approving")
            if decision.authority_epoch != case.authority_epoch:
                raise TransitionError("latest onboarding decision is stale")
            governance_basis_id = self._stable_id("legacy-governance", case)

        if case.case_kind == "employee-onboarding":
            obligation_set = derive_onboarding_obligations(
                case,
                evaluation,
                governance_basis_id=governance_basis_id,
            )
        elif case.case_kind in {
            "procurement-request",
            "invoice-ap-preparation",
            "expense-reimbursement",
        }:
            obligation_set = derive_financial_obligations(
                case,
                evaluation,
                governance_basis_id=governance_basis_id,
            )
        else:
            raise TransitionError(
                f"execution engine does not support case kind {case.case_kind!r}"
            )
        self.obligations.put(obligation_set)

        for obligation in obligation_set.obligations:
            authorization_id = self._stable_id(
                "authorization",
                case,
                obligation.target_system,
                obligation.required_operation,
            )
            if satisfaction is not None:
                authorization = mint_execution_authorization_from_approval(
                    case,
                    satisfaction,
                    issuer_principal_id="service:administrative-orchestrator",
                    target_system=obligation.target_system,
                    allowed_operations=(obligation.required_operation,),
                    authority_class=obligation.authority_class,
                )
            else:
                assert decision is not None
                authorization = mint_execution_authorization(
                    case,
                    decision,
                    issuer_principal_id="service:administrative-orchestrator",
                    target_system=obligation.target_system,
                    allowed_operations=(obligation.required_operation,),
                    authority_class=obligation.authority_class,
                )
            authorization = authorization.model_copy(
                update={
                    "authorization_id": authorization_id,
                    "issued_at": case.updated_at,
                }
            )
            authorization = self.repository.put_authorization(authorization)
            effect_id = self._stable_id(
                "effect",
                case,
                obligation.target_system,
                obligation.required_operation,
            )
            effect = plan_effect(
                case,
                authorization,
                operation=obligation.required_operation,
                reversibility=self._reversibility_for(obligation.required_operation),
            ).model_copy(
                update={
                    "effect_id": effect_id,
                    "obligation_id": obligation.obligation_id,
                    "governance_basis_id": governance_basis_id,
                    "created_at": case.updated_at,
                    "updated_at": case.updated_at,
                }
            )
            effect = self.repository.put_effect(effect)
            self.obligations.link_effect(effect, obligation)

    def _require_financial_qualifications(self, case: AdministrativeCase) -> None:
        required_by_case = {
            "procurement-request": {"vendor_qualification"},
            "invoice-ap-preparation": {
                "vendor_qualification",
                "duplicate_invoice_check",
                "three_way_match",
            },
        }
        required = required_by_case.get(case.case_kind, set())
        try:
            assessments = TransactionRepository(self.store).list_current_assessments(
                case.case_id, case.authority_epoch
            )
        except TransactionRecordConflict as exc:
            raise TransitionError(str(exc)) from exc
        qualified = {
            item.assessment_kind
            for item in assessments
            if item.result is TransactionQualificationResult.QUALIFIED
        }
        missing = sorted(required - qualified)
        if missing:
            raise FinancialQualificationPending(tuple(missing))

    def _drive_dispatch(
        self,
        case: AdministrativeCase,
        effects,
        obligation_set: OnboardingObligationSet | None,
        links,
    ) -> str:
        return self._verified_executor.drive_dispatch(
            case,
            effects,
            obligation_set,
            links,
        )

    def _payload_for_effect(self, effect, effects, payload):
        """Add only a prior durable draft identity to a confirm operation."""
        if effect.operation != "purchase_order.confirm":
            return payload
        draft = None
        for item in effects:
            current = self.repository.get_effect(item.effect_id) or item
            if (
                current.operation == "purchase_order.create_draft"
                and current.status == EffectStatus.SUCCEEDED
                and current.provider_ref
            ):
                draft = current
                break
        if draft is None:
            return None
        return {**payload, "purchase_order_ref": draft.provider_ref}

    @staticmethod
    def _effect_dispatch_order(effect):
        if effect.operation == "purchase_order.create_draft":
            return (0, "", "", str(effect.effect_id))
        if effect.operation == "purchase_order.confirm":
            return (1, "", "", str(effect.effect_id))
        # Preserve the caller's established order for onboarding/offboarding;
        # only procurement draft/confirm has a new dependency order.
        return (2, "", "", "")

    def _verify_all(
        self,
        case: AdministrativeCase,
        effects,
        obligation_set: OnboardingObligationSet | None,
        links,
    ) -> str:
        return self._verified_executor.verify_all(
            case,
            effects,
            obligation_set,
            links,
        )

    def _validate_current_governance(
        self,
        case: AdministrativeCase,
    ) -> GovernanceValidation | None:
        satisfaction = self.authority.get_approval_satisfaction(case.case_id, case.authority_epoch)
        if satisfaction is None:
            if get_settings().authority_enforcement_enabled:
                return GovernanceValidation(
                    valid=False,
                    reasons=("current authority epoch has no approval satisfaction",),
                )
            return None
        basis = self.governance.get_for_approval(satisfaction.satisfaction_id)
        if basis is None:
            if get_settings().authority_enforcement_enabled:
                return GovernanceValidation(
                    valid=False,
                    reasons=("current approval has no governance basis",),
                )
            return None
        return self.governance.revalidate(basis, case)

    def _assess_completion(
        self, obligation_set, effects, outcomes, realizations, links
    ):
        if self._require_case(obligation_set.case_id).case_kind in {
            "procurement-request",
            "invoice-ap-preparation",
            "expense-reimbursement",
        }:
            return assess_administrative_completion(
                obligation_set,
                effects,
                outcomes,
                realizations=realizations,
                links=links,
            )
        return assess_onboarding_completion(
            obligation_set,
            effects,
            outcomes,
            realizations=realizations,
            links=links,
        )

    @staticmethod
    def _assess_completion_without_obligations(effects, outcomes, realizations):
        return assess_onboarding_completion(
            effects,
            outcomes,
            realizations=realizations,
        )

    @staticmethod
    def _verify_observation(
        case: AdministrativeCase,
        effect,
        observation,
        facts,
        *,
        expected_postcondition,
    ):
        if case.case_kind in {
            "procurement-request",
            "invoice-ap-preparation",
            "expense-reimbursement",
        }:
            return verify_financial_observation(
                effect,
                observation,
                facts,
                expected_postcondition=expected_postcondition,
            )
        return verify_onboarding_observation(
            effect,
            observation,
            facts,
            expected_postcondition=expected_postcondition,
        )

    def _handle_completion_blocked(self, case, completion):
        reconciling = begin_reconciliation(case)
        self._persist_case_transition(
            case,
            reconciling,
            "case.completion_blocked",
            self._completion_blocker_payload(completion),
        )
        return reconciling

    @staticmethod
    def _completion_blocker_payload(completion):
        return {
            "requirement_id": completion.requirement_id,
            "blocking_reasons": list(completion.blocking_reasons),
            "missing_effect_ids": [str(item) for item in completion.missing_effect_ids],
            "missing_outcome_kinds": list(completion.missing_outcome_kinds),
            "missing_obligation_ids": [
                str(item) for item in completion.missing_obligation_ids
            ],
            "missing_realization_obligation_ids": [
                str(item)
                for item in completion.missing_realization_obligation_ids
            ],
            "uncovered_obligation_ids": [
                str(item) for item in completion.uncovered_obligation_ids
            ],
            "missing_domain_state_obligation_ids": [
                str(item) for item in completion.missing_domain_state_obligation_ids
            ],
            "governance_basis_id": (
                str(completion.governance_basis_id)
                if completion.governance_basis_id
                else None
            ),
        }

    @staticmethod
    def _obligation_for_effect(
        effect_id: UUID,
        obligation_set: OnboardingObligationSet | None,
        links,
    ) -> AdministrativeObligation | None:
        if obligation_set is None:
            return None
        obligation_id = next(
            (item.obligation_id for item in links if item.effect_id == effect_id),
            None,
        )
        if obligation_id is None:
            return None
        return next(
            (item for item in obligation_set.obligations if item.obligation_id == obligation_id),
            None,
        )

    def _reopen_for_governance(
        self,
        case: AdministrativeCase,
        validation: GovernanceValidation,
    ) -> AdministrativeCase:
        reopened_required = require_reopen(case, ReopenReason.GOVERNANCE_STALE)
        self._persist_case_transition(
            case,
            reopened_required,
            "case.governance_revalidation_required",
            {"reasons": list(validation.reasons)},
        )
        return reopened_required

    def _reopen_for_mismatch(self, case: AdministrativeCase) -> AdministrativeCase:
        reopened_required = require_reopen(case, ReopenReason.REALITY_MISMATCH)
        self._persist_case_transition(
            case,
            reopened_required,
            "case.reopen_required",
            {"reason": ReopenReason.REALITY_MISMATCH.value},
        )
        return reopened_required

    def _persist_case_transition(
        self,
        before: AdministrativeCase,
        after: AdministrativeCase,
        event_type: str,
        payload: dict | None = None,
    ) -> None:
        self.store.update_case(
            after,
            expected_previous_version=before.version,
            event_type=event_type,
            payload=payload,
        )

    def _require_case(self, case_id: UUID) -> AdministrativeCase:
        case = self.store.get_case(case_id)
        if case is None:
            raise KeyError(f"case {case_id} not found")
        return case

    @staticmethod
    def _stable_id(kind: str, case: AdministrativeCase, *parts: str) -> UUID:
        suffix = ":".join(parts)
        return uuid5(
            NAMESPACE_URL,
            f"administrative:{kind}:{case.case_id}:{case.authority_epoch}:{suffix}",
        )

    @staticmethod
    def _reversibility_for(operation: str):
        from .domain import EffectReversibility

        if operation in {"employee.create", "identity.create", "account.provision"}:
            return EffectReversibility.CORRECTABLE
        return EffectReversibility.UNKNOWN
