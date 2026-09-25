from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from administrative_orchestrator.domain import (
    AdministrativeCase,
    CaseStatus,
    FactAssertion,
    FactAuthority,
    FactSnapshot,
)
from administrative_orchestrator.service import (
    TransitionError,
    authoritative_effective_time,
    begin_waiting_for_effective_time,
    resume_from_waiting,
)

_NOW = datetime(2026, 9, 10, 9, 0, tzinfo=UTC)
_EFFECTIVE_AT = "2026-09-11T18:00:00Z"


def _snapshot(
    *,
    value: str | None = _EFFECTIVE_AT,
    authority: FactAuthority = FactAuthority.AUTHORITATIVE,
) -> FactSnapshot:
    assertions = {}
    if value is not None:
        assertions["termination_effective_at"] = FactAssertion(
            value=value,
            authority=authority,
            source="odoo",
            owner="service:test",
            source_ref="odoo:hr.employee:42",
            source_version="v1",
            observed_at=_NOW,
            digest="test",
        )
    return FactSnapshot(
        source="composite:employee-offboarding",
        owner="service:test",
        authority=FactAuthority.CLAIM,
        source_ref="odoo:hr.employee:42",
        source_version="v1",
        observed_at=_NOW,
        facts={
            "employee_ref": "odoo:hr.employee:42",
            "termination_effective_at": value,
        },
        assertions=assertions,
    )


def _case(
    *,
    status: CaseStatus = CaseStatus.AUTHORIZED,
    case_kind: str = "employee-offboarding",
    snapshot: FactSnapshot | None = None,
) -> AdministrativeCase:
    return AdministrativeCase(
        case_kind=case_kind,
        requester_principal_id="person:test",
        subject_ref="odoo:hr.employee:42",
        status=status,
        fact_snapshot=_snapshot() if snapshot is None else snapshot,
    )


def test_begin_waiting_requires_authoritative_effective_time() -> None:
    claim_only = _case(snapshot=_snapshot(authority=FactAuthority.CLAIM))
    with pytest.raises(TransitionError, match='authoritative'):
        begin_waiting_for_effective_time(claim_only, now=_NOW)

    missing = _case(snapshot=_snapshot(value=None))
    with pytest.raises(TransitionError, match='authoritative'):
        begin_waiting_for_effective_time(missing, now=_NOW)


def test_begin_waiting_persists_waiting_state() -> None:
    case = _case()
    waiting = begin_waiting_for_effective_time(case, now=_NOW)
    assert waiting.status is CaseStatus.WAITING
    assert waiting.version == case.version + 1
    assert authoritative_effective_time(waiting) == datetime(
        2026, 9, 11, 18, 0, tzinfo=UTC
    )


def test_begin_waiting_rejects_past_effective_time() -> None:
    case = _case()
    with pytest.raises(TransitionError, match='already passed'):
        begin_waiting_for_effective_time(
            case, now=datetime(2026, 9, 12, 0, 0, tzinfo=UTC)
        )


def test_begin_waiting_rejects_other_case_kinds_and_statuses() -> None:
    onboarding = _case(case_kind='employee-onboarding')
    with pytest.raises(TransitionError, match='employee-offboarding'):
        begin_waiting_for_effective_time(onboarding, now=_NOW)

    awaiting = _case(status=CaseStatus.AWAITING_DECISION)
    with pytest.raises(TransitionError, match='cannot wait'):
        begin_waiting_for_effective_time(awaiting, now=_NOW)


def test_resume_from_waiting_requires_effective_time_reached() -> None:
    case = _case()
    waiting = begin_waiting_for_effective_time(case, now=_NOW)

    with pytest.raises(TransitionError, match='not been reached'):
        resume_from_waiting(waiting, now=_NOW + timedelta(hours=1))

    resumed = resume_from_waiting(
        waiting, now=datetime(2026, 9, 11, 18, 0, tzinfo=UTC)
    )
    assert resumed.status is CaseStatus.AUTHORIZED
    assert resumed.version == waiting.version + 1


def test_resume_from_waiting_rejects_wrong_status() -> None:
    with pytest.raises(TransitionError, match='cannot resume'):
        resume_from_waiting(_case(), now=_NOW)


def test_authoritative_effective_time_parses_supported_shapes() -> None:
    assert authoritative_effective_time(_case(snapshot=_snapshot(value=None))) is None
    assert authoritative_effective_time(
        _case(snapshot=_snapshot(authority=FactAuthority.CLAIM))
    ) is None
    assert authoritative_effective_time(
        _case(snapshot=_snapshot(value='2026-10-01'))
    ) == datetime(2026, 10, 1, tzinfo=UTC)
    assert authoritative_effective_time(
        _case(snapshot=_snapshot(value='2026-10-01T20:00:00+02:00'))
    ) == datetime(2026, 10, 1, 18, 0, tzinfo=UTC)
    assert authoritative_effective_time(
        _case(snapshot=_snapshot(value='not-a-time'))
    ) is None

