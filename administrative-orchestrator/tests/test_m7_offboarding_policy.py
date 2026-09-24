from __future__ import annotations

import pytest

from administrative_orchestrator.persistence import SqlStore
from administrative_orchestrator.policy import (
    OffboardingFacts,
    OffboardingPolicy,
    OffboardingPolicyDefinition,
    PolicyDisposition,
)
from administrative_orchestrator.policy_plane import (
    PolicyPlaneError,
    PolicyRepository,
    PolicyVersionStatus,
    compile_offboarding_policy,
    default_offboarding_policy_version,
)


def _policy() -> OffboardingPolicy:
    return compile_offboarding_policy(default_offboarding_policy_version())


def test_default_offboarding_policy_registers_and_resolves() -> None:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    repository = PolicyRepository(store)
    record = default_offboarding_policy_version()
    repository.put_version(record)
    current = repository.resolve_current("employee-offboarding")
    assert current == record
    assert current.status is PolicyVersionStatus.ACTIVE


def test_offboarding_policy_requires_authoritative_termination_facts() -> None:
    policy = _policy()
    pending = policy.evaluate(OffboardingFacts(employee_ref="employee:1"))
    assert pending.disposition is PolicyDisposition.NEED_MORE_FACTS
    assert set(pending.missing_facts) == {"termination_status", "termination_effective_at"}

    request_only = policy.evaluate(
        OffboardingFacts(
            employee_ref="employee:1",
            requested_termination_date="2026-10-01",
        )
    )
    assert request_only.disposition is PolicyDisposition.NEED_MORE_FACTS


def test_offboarding_policy_reopens_when_hr_does_not_schedule_termination() -> None:
    policy = _policy()
    for status in ("active", "termination_cancelled"):
        evaluation = policy.evaluate(
            OffboardingFacts(
                employee_ref="employee:1",
                termination_status=status,
                termination_effective_at="2026-10-01T18:00:00Z",
            )
        )
        assert evaluation.disposition is PolicyDisposition.REOPEN_REQUIRED
        assert evaluation.allowed_effects == ()


def test_offboarding_policy_requires_approval_and_revocation_effects() -> None:
    policy = _policy()
    evaluation = policy.evaluate(
        OffboardingFacts(
            employee_ref="employee:1",
            termination_status="termination_scheduled",
            termination_effective_at="2026-10-01T18:00:00Z",
        )
    )
    assert evaluation.disposition is PolicyDisposition.HUMAN_DECISION_REQUIRED
    assert evaluation.required_decision_roles == ("hr_approver",)
    assert {
        (item.target_system, item.operation) for item in evaluation.allowed_effects
    } == {
        ("hris", "employee.deactivate"),
        ("iam", "identity.disable"),
        ("iam", "sessions.revoke"),
    }

    privileged = policy.evaluate(
        OffboardingFacts(
            employee_ref="employee:1",
            termination_status="termination_scheduled",
            termination_effective_at="2026-10-01T18:00:00Z",
            requires_privileged_access=True,
        )
    )
    assert privileged.require_distinct_decision_principals is True
    assert set(privileged.required_decision_roles) == {"manager", "access_approver"}


def test_compile_offboarding_policy_rejects_other_policy_ids() -> None:
    record = default_offboarding_policy_version().model_copy(
        update={"policy_id": "employee-onboarding"}
    )
    with pytest.raises(PolicyPlaneError):
        compile_offboarding_policy(record)


def test_offboarding_policy_rejects_overlapping_transfer_classification() -> None:
    definition = OffboardingPolicy.default_definition()
    definition["revoke_only_roles"].append("manager")
    with pytest.raises(ValueError, match="both transfer-required and revoke-only"):
        OffboardingPolicyDefinition.model_validate(definition)

