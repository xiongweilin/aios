from __future__ import annotations

from typing import Any

from .candidate_admission import (
    CandidateAdministrativeAdmissionService,
    CandidateAdmissionResult,
)
from .intake.models import CandidateAdministrativeRequest
from .policy import OffboardingFacts
from .policy_plane import PolicyVersionRecord, compile_offboarding_policy


class OffboardingAdmissionError(ValueError):
    """Candidate data cannot safely enter the offboarding lifecycle path."""


OffboardingAdmissionResult = CandidateAdmissionResult


class CandidateOffboardingAdmissionService(CandidateAdministrativeAdmissionService):
    """Bridge an admitted candidate into the employee-offboarding lifecycle.

    Candidate extraction may only produce claims about a departure request.
    Termination status and effective time stay absent here and must arrive
    through an authoritative HR source before the policy can qualify the case.
    """

    case_kind = 'employee-offboarding'
    policy_id = 'employee-offboarding'
    description = 'offboarding'
    error_type = OffboardingAdmissionError
    snapshot_source_version = 'm7-human-confirmed-v1'

    _CANDIDATE_FACT_KEYS = frozenset(
        {
            'employee_ref',
            'requested_termination_date',
            'reason',
            'successor_principal_id',
            'requested_systems',
        }
    )

    def _candidate_facts(
        self, candidate: CandidateAdministrativeRequest, *, subject_ref: str
    ) -> OffboardingFacts:
        assertions = self.repository.list_candidate_facts(candidate.candidate_id)
        values: dict[str, Any] = {}
        for assertion in assertions:
            if assertion.fact_key not in self._CANDIDATE_FACT_KEYS:
                raise OffboardingAdmissionError(
                    f"candidate fact {assertion.fact_key!r} is not allowed for offboarding"
                )
            if assertion.fact_key in values:
                raise OffboardingAdmissionError(
                    f"candidate contains duplicate offboarding fact {assertion.fact_key!r}"
                )
            values[assertion.fact_key] = assertion.value

        supplied_employee = values.get('employee_ref')
        if supplied_employee is not None and str(supplied_employee).strip() != subject_ref:
            raise OffboardingAdmissionError(
                "candidate employee_ref does not match the human-selected subject_ref"
            )
        try:
            return OffboardingFacts(
                employee_ref=subject_ref,
                requested_termination_date=values.get('requested_termination_date'),
                reason=values.get('reason'),
                successor_principal_id=values.get('successor_principal_id'),
                requested_systems=values.get('requested_systems', ()),
            )
        except ValueError as exc:
            raise OffboardingAdmissionError(
                "admitted candidate facts do not satisfy the offboarding fact contract"
            ) from exc

    def _compile_policy(self, record: PolicyVersionRecord) -> Any:
        return compile_offboarding_policy(record)


__all__ = [
    "CandidateOffboardingAdmissionService",
    "OffboardingAdmissionError",
    "OffboardingAdmissionResult",
]

