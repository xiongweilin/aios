from __future__ import annotations

from uuid import uuid4

import pytest
from administrative_orchestrator.domain import (
    AuthorityClass,
    EffectRecord,
    EffectReversibility,
)
from administrative_orchestrator.effect_provider import RealityObservation
from administrative_orchestrator.verification import (
    VerificationDisposition,
    verify_onboarding_observation,
)


@pytest.mark.parametrize(
    ("operation", "field", "expected_value", "actual_value"),
    [
        ("identity.disable", "enabled", False, True),
        ("sessions.revoke", "active_sessions", 0, 1),
    ],
)
def test_offboarding_verification_rejects_unmet_iam_state(
    operation: str,
    field: str,
    expected_value: object,
    actual_value: object,
) -> None:
    subject_ref = "odoo:hr.employee:42"
    effect = EffectRecord(
        case_id=uuid4(),
        case_version=5,
        authority_epoch=1,
        authorization_id=uuid4(),
        target_system="iam",
        operation=operation,
        subject_ref=subject_ref,
        reversibility=EffectReversibility.IRREVERSIBLE,
        authority_class=AuthorityClass.PRIVILEGED_ACCESS,
    )
    observation = RealityObservation(
        found=True,
        target_system="iam",
        operation=operation,
        subject_ref=subject_ref,
        state={
            field: actual_value,
            "payload": {"employee_ref": subject_ref},
        },
    )
    expected = {
        "target_system": "iam",
        "operation": operation,
        "subject_ref": subject_ref,
        field: expected_value,
        "payload": {"employee_ref": subject_ref},
    }

    result = verify_onboarding_observation(
        effect,
        observation,
        expected_postcondition=expected,
    )

    assert result.disposition is VerificationDisposition.MISMATCH
    assert result.differences[field] == {
        "expected": expected_value,
        "actual": actual_value,
    }


@pytest.mark.parametrize(
    ("operation", "field", "value"),
    [
        ("identity.disable", "enabled", False),
        ("sessions.revoke", "active_sessions", 0),
    ],
)
def test_offboarding_verification_accepts_observed_iam_state(
    operation: str,
    field: str,
    value: object,
) -> None:
    subject_ref = "odoo:hr.employee:42"
    effect = EffectRecord(
        case_id=uuid4(),
        case_version=5,
        authority_epoch=1,
        authorization_id=uuid4(),
        target_system="iam",
        operation=operation,
        subject_ref=subject_ref,
        reversibility=EffectReversibility.IRREVERSIBLE,
        authority_class=AuthorityClass.PRIVILEGED_ACCESS,
    )
    expected = {
        "target_system": "iam",
        "operation": operation,
        "subject_ref": subject_ref,
        field: value,
        "payload": {"employee_ref": subject_ref},
    }

    result = verify_onboarding_observation(
        effect,
        RealityObservation(
            found=True,
            target_system="iam",
            operation=operation,
            subject_ref=subject_ref,
            state={
                field: value,
                "payload": {"employee_ref": subject_ref},
            },
        ),
        expected_postcondition=expected,
    )

    assert result.disposition is VerificationDisposition.VERIFIED
