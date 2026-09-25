from __future__ import annotations

from typing import Any

from .candidate_admission import (
    CandidateAdministrativeAdmissionService,
    CandidateAdmissionResult,
)
from .intake.models import CandidateAdministrativeRequest
from .policy import OnboardingFacts
from .policy_plane import PolicyVersionRecord, compile_onboarding_policy


class OnboardingAdmissionError(ValueError):
    """Candidate data cannot safely enter the existing onboarding path."""


OnboardingAdmissionResult = CandidateAdmissionResult


class CandidateOnboardingAdmissionService(CandidateAdministrativeAdmissionService):
    """Bridge an admitted candidate into the existing M5 onboarding semantics."""

    case_kind = 'employee-onboarding'
    policy_id = 'employee-onboarding'
    description = 'onboarding'
    error_type = OnboardingAdmissionError
    snapshot_source_version = 'm6-human-confirmed-v1'

    _FACT_KEYS = frozenset(
        {
            'employee_ref',
            'department_ref',
            'manager_principal_id',
            'start_date',
            'employment_type',
            'requested_systems',
            'requires_privileged_access',
        }
    )

    def _candidate_facts(
        self, candidate: CandidateAdministrativeRequest, *, subject_ref: str
    ) -> OnboardingFacts:
        assertions = self.repository.list_candidate_facts(candidate.candidate_id)
        values: dict[str, Any] = {}
        for assertion in assertions:
            if assertion.fact_key not in self._FACT_KEYS:
                raise OnboardingAdmissionError(
                    f"candidate fact {assertion.fact_key!r} is not allowed for onboarding"
                )
            if assertion.fact_key in values:
                raise OnboardingAdmissionError(
                    f"candidate contains duplicate onboarding fact {assertion.fact_key!r}"
                )
            values[assertion.fact_key] = assertion.value

        supplied_employee = values.get('employee_ref')
        if supplied_employee is not None and str(supplied_employee).strip() != subject_ref:
            raise OnboardingAdmissionError(
                "candidate employee_ref does not match the human-selected subject_ref"
            )
        values["employee_ref"] = subject_ref
        try:
            return OnboardingFacts.model_validate(values)
        except ValueError as exc:
            raise OnboardingAdmissionError(
                "admitted candidate facts do not satisfy the onboarding fact contract"
            ) from exc

    def _compile_policy(self, record: PolicyVersionRecord) -> Any:
        return compile_onboarding_policy(record)


__all__ = [
    "CandidateOnboardingAdmissionService",
    "OnboardingAdmissionError",
    "OnboardingAdmissionResult",
]

