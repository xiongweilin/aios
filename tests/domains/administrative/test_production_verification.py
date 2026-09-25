from __future__ import annotations

from administrative_orchestrator.production_verification import (
    complete_readback_postcondition,
    readback_satisfies_expected,
)


def test_readback_postcondition_carries_context_payload_into_evidence() -> None:
    expected = {
        "target_system": "hris",
        "operation": "employee.deactivate",
        "subject_ref": "odoo:hr.employee:4",
        "active": False,
        "payload": {
            "employee_ref": "odoo:hr.employee:4",
            "employment_episode_ref": "episode:1",
        },
    }
    observed = {
        "target_system": "hris",
        "operation": "employee.deactivate",
        "subject_ref": "odoo:hr.employee:4",
        "active": False,
    }

    assert complete_readback_postcondition(expected, observed) == expected


def test_readback_postcondition_does_not_mask_provider_payload_mismatch() -> None:
    expected = {
        "target_system": "hris",
        "operation": "employee.deactivate",
        "subject_ref": "odoo:hr.employee:4",
        "active": False,
        "payload": {"employment_episode_ref": "episode:1"},
    }
    observed = {
        "target_system": "hris",
        "operation": "employee.deactivate",
        "subject_ref": "odoo:hr.employee:4",
        "active": False,
        "payload": {"employment_episode_ref": "episode:2"},
    }

    assert complete_readback_postcondition(expected, observed) == observed


def test_readback_satisfies_expected_allows_evidence_only_fields() -> None:
    expected = {"delivery_confirmed": True, "read_state": "unknown"}
    observed = {
        **expected,
        "provider_message_ref": "provider-message-ref",
    }

    assert readback_satisfies_expected(expected, observed)


def test_readback_satisfies_expected_rejects_missing_or_mismatched_expectations() -> None:
    expected = {"delivery_confirmed": True, "read_state": "unknown"}

    assert not readback_satisfies_expected(expected, {"delivery_confirmed": True})
    assert not readback_satisfies_expected(
        expected,
        {"delivery_confirmed": False, "read_state": "unknown"},
    )
