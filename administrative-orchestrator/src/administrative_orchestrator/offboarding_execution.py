from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from .authority_lifecycle import AuthorityLifecycleRepository
from .completion import assess_administrative_completion
from .domain import (
    AdministrativeCase,
    CaseStatus,
    EffectReversibility,
    ReopenReason,
    RoleAssignment,
    utcnow,
)
from .effect_provider import EffectProvider
from .governance import GovernanceValidation
from .obligations import (
    AdministrativeObligation,
    ObligationDomainStateFulfillment,
    ObligationFulfillmentKind,
)
from .offboarding_obligations import derive_offboarding_obligations
from .onboarding_execution import OnboardingExecutionEngine
from .policy_plane import PolicyRepository, compile_offboarding_policy
from .service import (
    TransitionError,
    authoritative_effective_time,
    begin_waiting_for_effective_time,
    mint_execution_authorization_from_approval,
    plan_effect,
    require_reopen,
    resume_from_waiting,
)
from .transfer import (
    TransferRequirementRepository,
    TransferRequirementStatus,
    derive_transfer_requirements,
)


class OffboardingExecutionEngine(OnboardingExecutionEngine):
    """Carry an authorized employee-offboarding case through verified closure."""

    def __init__(
        self,
        store,
        provider: EffectProvider,
        *,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        super().__init__(store, provider)
        self.clock = clock
        self.lifecycle = AuthorityLifecycleRepository(store)
        self.transfers = TransferRequirementRepository(store)
        self.policies = PolicyRepository(store)

    def run(self, case_id: UUID) -> AdministrativeCase:
        case = self._require_case(case_id)
        if case.case_kind != "employee-offboarding":
            raise TransitionError("offboarding engine requires employee-offboarding case")
        if case.status is CaseStatus.AUTHORIZED:
            effective_at = authoritative_effective_time(case)
            if effective_at is None:
                raise TransitionError(
                    "offboarding execution requires authoritative effective time"
                )
            if effective_at > self.clock():
                waiting = begin_waiting_for_effective_time(case, now=self.clock())
                self._persist_case_transition(
                    case,
                    waiting,
                    "case.waiting_for_effective_time",
                    {"effective_at": effective_at.isoformat()},
                )
                return waiting
        elif case.status is CaseStatus.WAITING:
            effective_at = authoritative_effective_time(case)
            if effective_at is None:
                raise TransitionError("waiting offboarding lost effective time")
            if effective_at > self.clock():
                return case
            validation = self._validate_current_governance(case)
            if validation is not None and not validation.valid:
                return self._reopen_for_governance(case, validation)
            resumed = resume_from_waiting(case, now=self.clock())
            self._persist_case_transition(
                case,
                resumed,
                "case.effective_time_reached",
                {"effective_at": effective_at.isoformat()},
            )
        return super().run(case_id)

    def _plan_current_effects(self, case: AdministrativeCase) -> None:
        if case.fact_snapshot is None or case.policy_ref is None:
            raise TransitionError("offboarding execution requires current governed facts")
        evaluation = self.store.get_latest_policy_evaluation(case.case_id)
        if evaluation is None or evaluation.policy_ref != case.policy_ref:
            raise TransitionError("offboarding execution requires current policy evaluation")
        record = self.policies.get_version(case.policy_ref.policy_id, case.policy_ref.version)
        if record is None:
            raise TransitionError("offboarding policy version is not persisted")
        policy = compile_offboarding_policy(record)
        satisfaction = self.authority.get_approval_satisfaction(
            case.case_id, case.authority_epoch
        )
        if satisfaction is None or satisfaction.policy_ref != case.policy_ref:
            raise TransitionError("offboarding execution requires current approval satisfaction")
        if not set(evaluation.required_decision_roles).issubset(
            set(satisfaction.satisfied_roles)
        ):
            raise TransitionError(
                "offboarding approval satisfaction does not cover required roles"
            )
        basis = self.governance.get_for_approval(satisfaction.satisfaction_id)
        if basis is None:
            raise TransitionError("offboarding execution requires governance basis")
        validation = self.governance.revalidate(basis, case)
        if not validation.valid:
            raise TransitionError("governance basis is stale: " + "; ".join(validation.reasons))

        existing_obligation_set = self.obligations.get_current(
            case.case_id, case.authority_epoch
        )
        if existing_obligation_set is not None:
            # Planning can partially fulfill Administrative domain-state
            # obligations before a later Kernel Work admission fails. Reuse
            # the immutable set for this authority epoch on replay; deriving
            # from the already-mutated authority graph would produce a
            # different set and incorrectly block recovery.
            obligation_set = existing_obligation_set
            transfers = tuple(
                self.transfers.list_for_case(case.case_id, case.authority_epoch)
            )
        else:
            transfers = derive_transfer_requirements(
                case,
                policy,
                self.authority,
                governance_basis_id=basis.basis_id,
            )
            self.transfers.put_all(transfers)
            obligation_set = derive_offboarding_obligations(
                case,
                evaluation,
                policy,
                self.authority,
                governance_basis_id=basis.basis_id,
                transfer_requirements=transfers,
            )
            self.obligations.put(obligation_set)
        self._fulfill_domain_state(
            case, obligation_set, transfers, transfer_phase=False
        )

        for obligation in obligation_set.obligations:
            if (
                obligation.fulfillment_kind
                is not ObligationFulfillmentKind.EXTERNAL_EFFECT_VERIFIED
            ):
                continue
            authorization = mint_execution_authorization_from_approval(
                case,
                satisfaction,
                issuer_principal_id="service:administrative-orchestrator",
                target_system=obligation.target_system,
                allowed_operations=(obligation.required_operation,),
                authority_class=obligation.authority_class,
            ).model_copy(
                update={
                    "authorization_id": self._stable_id(
                        "authorization",
                        case,
                        obligation.target_system,
                        obligation.required_operation,
                    ),
                    "issued_at": case.updated_at,
                }
            )
            authorization = self.repository.put_authorization(authorization)
            effect = plan_effect(
                case,
                authorization,
                operation=obligation.required_operation,
                reversibility=EffectReversibility.IRREVERSIBLE,
            ).model_copy(
                update={
                    "effect_id": self._stable_id(
                        "effect",
                        case,
                        obligation.target_system,
                        obligation.required_operation,
                    ),
                    "obligation_id": obligation.obligation_id,
                    "governance_basis_id": basis.basis_id,
                    "created_at": case.updated_at,
                    "updated_at": case.updated_at,
                }
            )
            effect = self.repository.put_effect(effect)
            self.obligations.link_effect(effect, obligation)

    def _fulfill_domain_state(
        self, case, obligation_set, transfers, *, transfer_phase: bool
    ) -> None:
        effective_at = authoritative_effective_time(case)
        if effective_at is None:
            raise TransitionError("domain revocation requires effective time")
        actor = "service:administrative-orchestrator"
        reason = "employee offboarding effective time reached"
        transfer_by_id = {str(item.requirement_id): item for item in transfers}
        for obligation in obligation_set.obligations:
            if (
                obligation.fulfillment_kind
                is not ObligationFulfillmentKind.DOMAIN_STATE_VERIFIED
            ):
                continue
            if self.obligations.get_domain_state_fulfillment(obligation.obligation_id):
                continue
            expected = obligation.expected_postcondition
            evidence_ref: str | None = None
            is_transfer = obligation.required_operation == "role_assignment.transfer"
            if is_transfer != transfer_phase:
                continue
            if obligation.required_operation == "identity_binding.expire":
                event = self.lifecycle.expire_identity_binding(
                    UUID(str(expected["binding_id"])),
                    actor_principal_id=actor,
                    reason=reason,
                    at=effective_at,
                )
                evidence_ref = f"authority-event:{event.event_id}"
            elif obligation.required_operation == "role_assignment.expire":
                event = self.lifecycle.expire_role_assignment(
                    UUID(str(expected["assignment_id"])),
                    actor_principal_id=actor,
                    reason=reason,
                    at=effective_at,
                )
                evidence_ref = f"authority-event:{event.event_id}"
            elif obligation.required_operation == "delegation.expire":
                event = self.lifecycle.expire_delegation(
                    UUID(str(expected["delegation_id"])),
                    actor_principal_id=actor,
                    reason=reason,
                    at=effective_at,
                )
                evidence_ref = f"authority-event:{event.event_id}"
            elif obligation.required_operation == "role_assignment.transfer":
                requirement = transfer_by_id[str(expected["transfer_requirement_id"])]
                if requirement.status is not TransferRequirementStatus.SUCCESSOR_QUALIFIED:
                    continue
                assert requirement.successor_principal_id is not None
                if (
                    self.authority.get_principal(requirement.successor_principal_id)
                    is None
                    or requirement.successor_principal_id
                    == requirement.departing_principal_id
                    or not self.authority.roles_for(
                        requirement.successor_principal_id,
                        organization_scope=requirement.organization_scope,
                        at=self.clock(),
                    )
                ):
                    continue
                assignment = self.authority.put_role_assignment(
                    RoleAssignment(
                        assignment_id=uuid5(
                            NAMESPACE_URL,
                            f"administrative:offboarding-successor-role:"
                            f"{requirement.requirement_id}",
                        ),
                        principal_id=requirement.successor_principal_id,
                        role=requirement.role,
                        organization_scope=requirement.organization_scope,
                        valid_from=effective_at,
                    )
                )
                self.transfers.mark_fulfilled(
                    requirement.requirement_id,
                    successor_principal_id=requirement.successor_principal_id,
                )
                evidence_ref = f"role-assignment:{assignment.assignment_id}"
            elif obligation.required_operation == "principal.deactivate":
                event = self.lifecycle.deactivate_principal(
                    str(expected["principal_id"]),
                    actor_principal_id=actor,
                    reason=reason,
                    at=effective_at,
                )
                evidence_ref = f"authority-event:{event.event_id}"
            else:
                raise TransitionError(
                    f"unsupported offboarding domain obligation {obligation.required_operation}"
                )
            self._record_domain_fulfillment(
                case, obligation, expected, evidence_ref=evidence_ref
            )

    def _drive_dispatch(self, case, effects, obligation_set, links):
        ordered = sorted(effects, key=self._effect_order)
        return super()._drive_dispatch(case, ordered, obligation_set, links)

    def _verify_all(self, case, effects, obligation_set, links):
        result = super()._verify_all(case, effects, obligation_set, links)
        if result == "verified" and obligation_set is not None:
            transfers = self.transfers.list_for_case(
                case.case_id, case.authority_epoch
            )
            self._fulfill_domain_state(
                case, obligation_set, transfers, transfer_phase=True
            )
        return result

    @staticmethod
    def _effect_order(effect) -> tuple[int, str]:
        order = {
            "identity.disable": 0,
            "sessions.revoke": 1,
            "employee.deactivate": 2,
        }
        return order.get(effect.operation, 99), str(effect.effect_id)

    def _record_domain_fulfillment(
        self,
        case: AdministrativeCase,
        obligation: AdministrativeObligation,
        observed: dict,
        *,
        evidence_ref: str | None,
    ) -> None:
        payload = json.dumps(observed, sort_keys=True, separators=(",", ":"))
        self.obligations.record_domain_state_fulfillment(
            ObligationDomainStateFulfillment(
                fulfillment_id=uuid5(
                    NAMESPACE_URL,
                    f"administrative:domain-fulfillment:{obligation.obligation_id}",
                ),
                obligation_id=obligation.obligation_id,
                case_id=case.case_id,
                authority_epoch=case.authority_epoch,
                governance_basis_id=obligation.governance_basis_id,
                verified_by="service:administrative-orchestrator",
                reason="verified Administrative lifecycle state",
                observed_state_digest=hashlib.sha256(payload.encode()).hexdigest(),
                evidence_ref=evidence_ref,
                observed_at=self.clock(),
            )
        )

    def _assess_completion(
        self, obligation_set, effects, outcomes, realizations, links
    ):
        completion = assess_administrative_completion(
            obligation_set,
            effects,
            outcomes,
            realizations=realizations,
            links=links,
            fulfillments=self.obligations.list_domain_state_fulfillments(
                obligation_set.case_id, obligation_set.authority_epoch
            ),
        )
        return completion

    def _handle_completion_blocked(self, case, completion):
        obligation_set = self.obligations.get_current(
            case.case_id, case.authority_epoch
        )
        transfer_ids = {
            item.obligation_id
            for item in (obligation_set.obligations if obligation_set else ())
            if item.required_operation == "role_assignment.transfer"
        }
        if transfer_ids & set(completion.missing_domain_state_obligation_ids):
            reopened = require_reopen(case, ReopenReason.AUTHORITY_UNRESOLVED)
            self._persist_case_transition(
                case,
                reopened,
                "case.transfer_reassessment_required",
                self._completion_blocker_payload(completion),
            )
            return reopened
        return super()._handle_completion_blocked(case, completion)

    @staticmethod
    def _reversibility_for(operation: str):
        del operation
        return EffectReversibility.IRREVERSIBLE


class ProductionTrustOffboardingExecutionEngine(OffboardingExecutionEngine):
    def __init__(
        self,
        store,
        provider: EffectProvider,
        *,
        hris_source,
        max_fact_age_seconds: int,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        super().__init__(store, provider, clock=clock)
        from .fact_acquisition import AuthoritativeFactRevalidator

        self.external_facts = AuthoritativeFactRevalidator(
            hris_source, max_age_seconds=max_fact_age_seconds
        )

    def _validate_current_governance(
        self, case: AdministrativeCase
    ) -> GovernanceValidation | None:
        domain = super()._validate_current_governance(case)
        if domain is not None and not domain.valid:
            return domain
        satisfaction = self.authority.get_approval_satisfaction(
            case.case_id, case.authority_epoch
        )
        basis = (
            self.governance.get_for_approval(satisfaction.satisfaction_id)
            if satisfaction is not None
            else None
        )
        expected_change_keys = basis.expected_change_keys if basis is not None else ()
        external = self.external_facts.validate_with_dependencies(
            case, expected_change_keys=expected_change_keys
        )
        if not external.valid:
            reasons = tuple(domain.reasons if domain else ()) + tuple(
                f"external-authoritative-fact: {item}" for item in external.reasons
            )
            return GovernanceValidation(valid=False, reasons=reasons)
        return domain or GovernanceValidation(valid=True)


__all__ = [
    "OffboardingExecutionEngine",
    "ProductionTrustOffboardingExecutionEngine",
]
