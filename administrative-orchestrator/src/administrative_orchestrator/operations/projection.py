from __future__ import annotations

from typing import Any

from sqlalchemy.exc import OperationalError

from ..completion import CompletionAssessment, assess_administrative_completion
from ..domain import AdministrativeCase, utcnow
from ..inspection import list_authorizations, list_decisions, list_realizations
from ..integrations.world_runtime import WorldRuntimeBoundaryError, WorldRuntimeBridge
from ..responsibility_discharge import (
    AdministrativeResponsibilityDischargeService,
    ResponsibilityDischargeBlocked,
)
from ..transfer import TransferRequirementRepository
from .runtime import OperationsRuntime


def case_completion_assessment(
    obligation_set,
    effects,
    outcomes,
    *,
    realizations,
    links,
    fulfillments,
) -> CompletionAssessment:
    if obligation_set is None:
        return CompletionAssessment(
            requirement_id="missing-current-obligation-set",
            satisfied=False,
            blocking_reasons=("missing current obligation set",),
        )
    return assess_administrative_completion(
        obligation_set,
        effects,
        outcomes,
        realizations=realizations,
        links=links,
        fulfillments=fulfillments,
    )


def termination_snapshot(case: AdministrativeCase) -> dict[str, Any]:
    facts = case.fact_snapshot.facts if case.fact_snapshot is not None else {}
    return {
        "termination_status": facts.get("termination_status"),
        "termination_effective_at": facts.get("termination_effective_at"),
        "employment_episode_ref": facts.get("employment_episode_ref"),
        "authoritative_fact_snapshot": (
            case.fact_snapshot.model_dump(mode="json") if case.fact_snapshot else None
        ),
    }


def authority_snapshot(
    runtime: OperationsRuntime,
    case: AdministrativeCase,
) -> dict[str, list[dict[str, Any]]]:
    facts = case.fact_snapshot.facts if case.fact_snapshot is not None else {}
    principal_ids = {
        str(value)
        for key, value in facts.items()
        if key.endswith("principal_id") and isinstance(value, str) and value.strip()
    }
    principal_ids.add(case.requester_principal_id)
    bindings: list[dict[str, Any]] = []
    roles: list[dict[str, Any]] = []
    delegations: list[dict[str, Any]] = []
    observed_at = utcnow()
    for principal_id in sorted(principal_ids):
        bindings.extend(
            item.model_dump(mode="json")
            for item in runtime.authority.list_current_identity_bindings(
                principal_id, at=observed_at
            )
        )
        roles.extend(
            item.model_dump(mode="json")
            for item in runtime.authority.list_current_role_assignments(
                principal_id, at=observed_at
            )
        )
        delegations.extend(
            item.model_dump(mode="json")
            for item in runtime.authority.list_current_delegations_involving(
                principal_id, at=observed_at
            )
        )
    return {
        "bindings": dedupe_json_records(bindings),
        "role_assignments": dedupe_json_records(roles),
        "delegations": dedupe_json_records(delegations),
    }


def responsibility_snapshot(
    runtime: OperationsRuntime,
    case: AdministrativeCase,
    obligation_set,
    completion: CompletionAssessment,
    *,
    discharge_service_factory=AdministrativeResponsibilityDischargeService,
) -> dict[str, Any]:
    if obligation_set is None:
        return {
            "status": "pending",
            "blocker": "missing_current_obligation_set",
            "responsibilities": [],
            "completion_satisfied": completion.satisfied,
        }
    if not completion.satisfied:
        return {
            "status": "pending",
            "blocker": "completion_assessment_not_satisfied",
            "responsibilities": [],
            "completion_satisfied": False,
        }
    if runtime.settings.world_runtime_mode != "cutover":
        return {
            "status": "pending",
            "blocker": "world_runtime_cutover_required",
            "responsibilities": [],
            "completion_satisfied": completion.satisfied,
        }

    bridge = WorldRuntimeBridge(runtime.store, runtime.settings)
    try:
        service = discharge_service_factory(runtime.store, bridge)
        try:
            handles = service.project_responsibility_set(case, obligation_set)
        except ResponsibilityDischargeBlocked as exc:
            return {
                "status": "pending",
                "blocker": str(exc),
                "responsibilities": [],
                "completion_satisfied": completion.satisfied,
            }

        observations: list[dict[str, Any]] = []
        for handle in handles:
            current_status = "unknown"
            blocker = None
            try:
                current_status = bridge.responsibility_status(handle.responsibility_ref)
            except WorldRuntimeBoundaryError:
                blocker = "world_runtime_responsibility_status_unavailable"
            observations.append(
                {
                    "responsibility_ref": handle.responsibility_ref,
                    "responsibility_version": handle.responsibility_version,
                    "obligation_ids": [str(item) for item in handle.obligation_ids],
                    "current_status": current_status,
                    "blocker": blocker,
                }
            )
    finally:
        bridge.close()

    statuses = {item["current_status"] for item in observations}
    if not observations or statuses == {"discharged"}:
        overall = "discharged"
        blocker = None
    else:
        overall = "pending"
        blocker = next(
            (item["blocker"] for item in observations if item["blocker"]),
            "responsibility_set_not_discharged",
        )
    return {
        "status": overall,
        "blocker": blocker,
        "completion_satisfied": completion.satisfied,
        "responsibilities": observations,
    }


def assemble_case_detail(
    runtime: OperationsRuntime,
    case: AdministrativeCase,
    *,
    include_audit: bool,
) -> dict[str, Any]:
    obligation_set = runtime.obligations.get_current(case.case_id, case.authority_epoch)
    effects = runtime.execution.list_effects(case.case_id, case.authority_epoch)
    outcomes = runtime.execution.list_outcomes(case.case_id, case.authority_epoch)
    realizations = runtime.execution.list_realizations(case.case_id, case.authority_epoch)
    links = runtime.obligations.list_links(case.case_id, case.authority_epoch)
    fulfillments = runtime.obligations.list_domain_state_fulfillments(
        case.case_id, case.authority_epoch
    )
    completion = case_completion_assessment(
        obligation_set,
        effects,
        outcomes,
        realizations=realizations,
        links=links,
        fulfillments=fulfillments,
    )
    transfers = TransferRequirementRepository(runtime.store).list_for_case(
        case.case_id, case.authority_epoch
    )
    authority = authority_snapshot(runtime, case)
    audit = runtime.store.list_audit_events(case.case_id) if include_audit else None
    commitment = None
    communications = []
    try:
        commitment = runtime.commitments.get_commitment(case.case_id)
        communications = runtime.commitments.list_communications(case.case_id)
    except OperationalError:
        commitment = None
        communications = []
    investigations = []
    reopen_history = []
    try:
        investigations = runtime.investigation_service.repository.list_requests(case.case_id)
        reopen_history = runtime.investigation_service.repository.list_reopen_records(case.case_id)
    except OperationalError:
        investigations = []
        reopen_history = []
    return {
        "case": case.model_dump(mode="json"),
        "commitment": commitment.model_dump(mode="json") if commitment is not None else None,
        "communications": [item.model_dump(mode="json") for item in communications],
        "policy": (
            evaluation.model_dump(mode="json")
            if (evaluation := runtime.store.get_latest_policy_evaluation(case.case_id)) is not None
            else None
        ),
        "governance": (
            basis.model_dump(mode="json")
            if (
                basis := runtime.governance.get_current_for_case(
                    case.case_id, case.authority_epoch
                )
            )
            is not None
            else None
        ),
        "obligations": obligation_set.model_dump(mode="json") if obligation_set else None,
        "effects": [item.model_dump(mode="json") for item in effects],
        "realizations": [
            item.model_dump(mode="json")
            for item in list_realizations(runtime.store, case.case_id)
        ],
        "outcomes": [item.model_dump(mode="json") for item in outcomes],
        "decisions": [
            item.model_dump(mode="json") for item in list_decisions(runtime.store, case.case_id)
        ],
        "authorizations": [
            item.model_dump(mode="json")
            for item in list_authorizations(runtime.store, case.case_id)
        ],
        "termination": termination_snapshot(case),
        "authority": authority,
        "transfers": [item.model_dump(mode="json") for item in transfers],
        "domain_fulfillments": [item.model_dump(mode="json") for item in fulfillments],
        "evidence_links": [
            item.model_dump(mode="json")
            for item in runtime.transactions.list_evidence_links(
                case.case_id, case.authority_epoch
            )
        ],
        "qualification_assessments": [
            item.model_dump(mode="json")
            for item in runtime.transactions.list_assessments(
                case.case_id, case.authority_epoch
            )
        ],
        "completion_assessment": completion.model_dump(mode="json"),
        "responsibility_discharge": responsibility_snapshot(
            runtime,
            case,
            obligation_set,
            completion,
        ),
        "investigations": [item.model_dump(mode="json") for item in investigations],
        "reopen_history": [item.model_dump(mode="json") for item in reopen_history],
        "audit": audit,
    }


def dedupe_json_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for record in records:
        key = repr(sorted(record.items()))
        unique[key] = record
    return [unique[key] for key in sorted(unique)]


__all__ = [
    "assemble_case_detail",
    "authority_snapshot",
    "case_completion_assessment",
    "dedupe_json_records",
    "responsibility_snapshot",
    "termination_snapshot",
]
