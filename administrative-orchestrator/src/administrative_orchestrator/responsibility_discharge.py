from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from .completion import CompletionAssessment, assess_administrative_completion
from .domain import AdministrativeCase, CaseStatus
from .execution_repository import ExecutionRepository
from .integrations.world_runtime import WorldRuntimeBoundaryError, WorldRuntimeBridge
from .obligations import ObligationFulfillmentKind, ObligationRepository
from .persistence import SqlStore


class ResponsibilityDischargeStatus(StrEnum):
    PENDING = "pending"
    DISCHARGED = "discharged"


class ResponsibilityDischargeBlocked(RuntimeError):
    """Structural discharge invariant failure; no Runtime mutation is attempted."""


@dataclass(frozen=True, slots=True)
class ResponsibilityHandle:
    responsibility_ref: str
    responsibility_version: int
    obligation_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class ResponsibilityDischargeResult:
    status: ResponsibilityDischargeStatus
    responsibility_refs: tuple[str, ...]
    discharged_refs: tuple[str, ...]
    assessment_refs: tuple[tuple[str, str], ...]
    decision_refs: tuple[tuple[str, str], ...]
    transition_refs: tuple[tuple[str, str], ...]
    completion: CompletionAssessment
    blocker: str | None = None


class AdministrativeResponsibilityDischargeService:
    """Discharge Runtime responsibilities only after Administrative completion is proven."""

    def __init__(self, store: SqlStore, bridge: WorldRuntimeBridge) -> None:
        self.store = store
        self.bridge = bridge
        self.obligations = ObligationRepository(store)
        self.execution = ExecutionRepository(store)

    def project_responsibility_set(
        self,
        case: AdministrativeCase,
        obligation_set,
    ) -> tuple[ResponsibilityHandle, ...]:
        return self._project_responsibility_set(case, obligation_set)

    @staticmethod
    def discharge_chain_refs(
        case: AdministrativeCase,
        handle: ResponsibilityHandle,
    ) -> tuple[str, str, str]:
        prefix = (
            f"{case.case_id}:{case.version}:{case.authority_epoch}:"
            f"{handle.responsibility_ref}:{handle.responsibility_version}"
        )
        return (
            f"assessment_admin_discharge_{uuid5(NAMESPACE_URL, f'assessment:{prefix}').hex}",
            f"decision_admin_discharge_{uuid5(NAMESPACE_URL, f'decision:{prefix}').hex}",
            f"transition_admin_discharge_{uuid5(NAMESPACE_URL, f'transition:{prefix}').hex}",
        )

    def discharge(self, case: AdministrativeCase) -> ResponsibilityDischargeResult:
        obligation_set = self.obligations.get_current(case.case_id, case.authority_epoch)
        if obligation_set is None:
            return self._blocked(
                "missing_current_obligation_set",
                responsibility_refs=(),
                completion=self._unsatisfied_completion("missing_current_obligation_set"),
            )

        effects = self.execution.list_effects(case.case_id, case.authority_epoch)
        outcomes = self.execution.list_outcomes(case.case_id, case.authority_epoch)
        realizations = self.execution.list_realizations(case.case_id, case.authority_epoch)
        links = self.obligations.list_links(case.case_id, case.authority_epoch)
        fulfillments = self.obligations.list_domain_state_fulfillments(
            case.case_id, case.authority_epoch
        )
        completion = assess_administrative_completion(
            obligation_set,
            effects,
            outcomes,
            realizations=realizations,
            links=links,
            fulfillments=fulfillments,
        )
        if case.status is not CaseStatus.COMPLETED:
            return self._blocked(
                "case_not_completed",
                responsibility_refs=(),
                completion=completion,
            )
        if not completion.satisfied:
            return self._blocked(
                "completion_assessment_not_satisfied",
                responsibility_refs=(),
                completion=completion,
            )
        if not self.bridge.cutover:
            return self._blocked(
                "world_runtime_cutover_required",
                responsibility_refs=(),
                completion=completion,
            )

        try:
            handles = self._project_responsibility_set(case, obligation_set)
        except ResponsibilityDischargeBlocked as exc:
            return self._blocked(
                str(exc),
                responsibility_refs=(),
                completion=completion,
            )

        responsibility_refs = tuple(item.responsibility_ref for item in handles)
        if not handles:
            return ResponsibilityDischargeResult(
                status=ResponsibilityDischargeStatus.DISCHARGED,
                responsibility_refs=(),
                discharged_refs=(),
                assessment_refs=(),
                decision_refs=(),
                transition_refs=(),
                completion=completion,
            )

        discharged: list[str] = []
        assessment_refs: list[tuple[str, str]] = []
        decision_refs: list[tuple[str, str]] = []
        transition_refs: list[tuple[str, str]] = []

        for handle in handles:
            try:
                status = self.bridge.responsibility_status(handle.responsibility_ref)
                if status == "discharged":
                    discharged.append(handle.responsibility_ref)
                    continue
                if status != "active":
                    return self._pending_result(
                        "responsibility_not_active",
                        responsibility_refs,
                        discharged,
                        assessment_refs,
                        decision_refs,
                        transition_refs,
                        completion,
                    )
                basis_refs = self._basis_refs(
                    case,
                    handle,
                    completion,
                    effects=effects,
                    outcomes=outcomes,
                    links=links,
                    fulfillments=fulfillments,
                )
                _legacy_assessment_ref, decision_ref, _legacy_transition_ref = (
                    self.discharge_chain_refs(case, handle)
                )
                assessment_ref, decision_ref, transition_ref = (
                    self.bridge.discharge_responsibility(
                        handle.responsibility_ref,
                        decision_ref=decision_ref,
                        decided_by="service:administrative-orchestrator",
                        subject_ref=case.subject_ref,
                        basis_refs=basis_refs,
                    )
                )
                assessment_refs.append((handle.responsibility_ref, assessment_ref))
                decision_refs.append((handle.responsibility_ref, decision_ref))
                transition_refs.append((handle.responsibility_ref, transition_ref))
                if self.bridge.responsibility_status(handle.responsibility_ref) != "discharged":
                    return self._pending_result(
                        "runtime_discharge_not_confirmed",
                        responsibility_refs,
                        discharged,
                        assessment_refs,
                        decision_refs,
                        transition_refs,
                        completion,
                    )
                discharged.append(handle.responsibility_ref)
            except WorldRuntimeBoundaryError as exc:
                return self._pending_result(
                    f"world_runtime_discharge_unavailable:{type(exc).__name__}",
                    responsibility_refs,
                    discharged,
                    assessment_refs,
                    decision_refs,
                    transition_refs,
                    completion,
                )

        return ResponsibilityDischargeResult(
            status=ResponsibilityDischargeStatus.DISCHARGED,
            responsibility_refs=responsibility_refs,
            discharged_refs=tuple(discharged),
            assessment_refs=tuple(assessment_refs),
            decision_refs=tuple(decision_refs),
            transition_refs=tuple(transition_refs),
            completion=completion,
        )

    def _project_responsibility_set(
        self,
        case: AdministrativeCase,
        obligation_set,
    ) -> tuple[ResponsibilityHandle, ...]:
        current_external = tuple(
            item
            for item in obligation_set.obligations
            if item.required
            and item.fulfillment_kind is ObligationFulfillmentKind.EXTERNAL_EFFECT_VERIFIED
        )
        links = self.obligations.list_links(case.case_id, case.authority_epoch)
        effects = {
            item.effect_id: item
            for item in self.execution.list_effects(case.case_id, case.authority_epoch)
        }
        handles: list[ResponsibilityHandle] = []
        for obligation in current_external:
            matching_effect_ids = [
                link.effect_id for link in links if link.obligation_id == obligation.obligation_id
            ]
            if len(matching_effect_ids) != 1:
                raise ResponsibilityDischargeBlocked(
                    "missing_or_duplicate_current_runtime_effect"
                )
            effect = effects.get(matching_effect_ids[0])
            if effect is None:
                raise ResponsibilityDischargeBlocked("runtime_effect_not_persisted")
            handles.append(
                ResponsibilityHandle(
                    responsibility_ref=self.bridge.responsibility_ref_for_effect(
                        effect.effect_id
                    ),
                    responsibility_version=1,
                    obligation_ids=(obligation.obligation_id,),
                )
            )
        return tuple(sorted(handles, key=lambda item: item.responsibility_ref))

    def _basis_refs(
        self,
        case: AdministrativeCase,
        handle: ResponsibilityHandle,
        completion: CompletionAssessment,
        *,
        effects: list[Any],
        outcomes: list[Any],
        links: list[Any],
        fulfillments: list[Any],
    ) -> tuple[str, ...]:
        refs = {
            f"administrative-case:{case.case_id}:version:{case.version}:epoch:{case.authority_epoch}",
            f"completion-assessment:{completion.requirement_id}",
            f"responsibility:{handle.responsibility_ref}:version:{handle.responsibility_version}",
            self._policy_ref(case),
        }
        for obligation_id in handle.obligation_ids:
            refs.add(f"administrative-obligation:{obligation_id}")
        effect_by_id = {item.effect_id: item for item in effects}
        covered_effect_ids = {
            link.effect_id
            for link in links
            if link.obligation_id in handle.obligation_ids and link.effect_id in effect_by_id
        }
        for effect_id in covered_effect_ids:
            refs.add(f"administrative-effect:{effect_id}")
        for outcome in outcomes:
            if outcome.effect_id in covered_effect_ids:
                refs.add(f"confirmed-outcome:{outcome.outcome_id}")
        for fulfillment in fulfillments:
            if fulfillment.obligation_id in handle.obligation_ids:
                refs.add(f"domain-fulfillment:{fulfillment.fulfillment_id}")
        return tuple(sorted(refs))

    @staticmethod
    def _policy_ref(case: AdministrativeCase) -> str:
        if case.policy_ref is None:
            raise ResponsibilityDischargeBlocked("missing_current_policy")
        return f"policy:{case.policy_ref.policy_id}:{case.policy_ref.version}"

    @staticmethod
    def _unsatisfied_completion(reason: str) -> CompletionAssessment:
        return CompletionAssessment(
            requirement_id=f"blocked:{reason}",
            satisfied=False,
            blocking_reasons=(reason,),
        )

    @staticmethod
    def _blocked(
        blocker: str,
        *,
        responsibility_refs: tuple[str, ...],
        completion: CompletionAssessment,
    ) -> ResponsibilityDischargeResult:
        return ResponsibilityDischargeResult(
            status=ResponsibilityDischargeStatus.PENDING,
            responsibility_refs=responsibility_refs,
            discharged_refs=(),
            assessment_refs=(),
            decision_refs=(),
            transition_refs=(),
            completion=completion,
            blocker=blocker,
        )

    @staticmethod
    def _pending_result(
        blocker: str,
        responsibility_refs: tuple[str, ...],
        discharged: list[str],
        assessment_refs: list[tuple[str, str]],
        decision_refs: list[tuple[str, str]],
        transition_refs: list[tuple[str, str]],
        completion: CompletionAssessment,
    ) -> ResponsibilityDischargeResult:
        return ResponsibilityDischargeResult(
            status=ResponsibilityDischargeStatus.PENDING,
            responsibility_refs=responsibility_refs,
            discharged_refs=tuple(discharged),
            assessment_refs=tuple(assessment_refs),
            decision_refs=tuple(decision_refs),
            transition_refs=tuple(transition_refs),
            completion=completion,
            blocker=blocker,
        )


__all__ = [
    "AdministrativeResponsibilityDischargeService",
    "ResponsibilityDischargeBlocked",
    "ResponsibilityDischargeResult",
    "ResponsibilityDischargeStatus",
    "ResponsibilityHandle",
]
