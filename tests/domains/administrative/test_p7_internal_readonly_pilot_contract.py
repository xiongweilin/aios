"""Fail-closed static regression tests for the unapproved P7 internal pilot.

These tests cannot grant staging access or qualify a live run.
"""
from __future__ import annotations

import copy
import json

from scripts.check_p7_internal_readonly_pilot import CONTRACT, validate_contract


def load_contract() -> dict:
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def test_frozen_contract_is_well_formed_and_execution_is_denied() -> None:
    contract = load_contract()
    assert validate_contract(contract) == []
    assert contract["activation"]["approved"] is False
    assert contract["activation"]["default"] == "deny"
    assert contract["status"] == "design_frozen_not_authorized"
    assert not any("://" in str(item) for item in contract["domain"]["allowed_sources"])


def test_window_slots_are_consistent_and_all_gaps_stay_in_denominator() -> None:
    contract = load_contract()
    horizon = contract["horizon"]
    assert horizon["supervised_window_seconds"] == 4 * 60 * 60
    assert horizon["planned_rounds"] == 240
    assert horizon["planned_slots"] == 960
    assert contract["measurement"]["all_assigned_windows_denominator"] is True


def test_toggle_approval_in_public_contract_fails_closed() -> None:
    changed = copy.deepcopy(load_contract())
    changed["activation"]["approved"] = True
    assert "unsafe_activation" in validate_contract(changed)


def test_broadened_access_method_fails_closed() -> None:
    changed = copy.deepcopy(load_contract())
    changed["domain"]["allowed_sources"][1]["method"] = "POST"
    assert "effectful_method" in validate_contract(changed)


def test_additional_unapproved_source_fails_closed() -> None:
    changed = copy.deepcopy(load_contract())
    changed["domain"]["allowed_sources"].append(
        {"id": "user_accounts", "method": "GET", "path": "/users"}
    )
    assert "wrong_source_allowlist" in validate_contract(changed)


def test_time_or_denominator_mutation_rejected() -> None:
    changed = copy.deepcopy(load_contract())
    changed["horizon"]["supervised_window_seconds"] = 86400
    assert "pilot_horizon_drift" in validate_contract(changed)


def test_missing_operator_and_written_approval_is_rejected() -> None:
    changed = copy.deepcopy(load_contract())
    changed["activation"]["requires"] = ["approved_start_end_time"]
    assert "activation_requirements_missing" in validate_contract(changed)


def test_weakening_fail_closed_exit_is_rejected() -> None:
    changed = copy.deepcopy(load_contract())
    changed["escalation_and_exit"]["fail_closed_on"].remove(
        "security_contract_invalid_or_weakened"
    )
    assert "missing_stop_condition" in validate_contract(changed)


def test_treating_unknown_as_success_fails_closed() -> None:
    changed = copy.deepcopy(load_contract())
    changed["escalation_and_exit"]["unknown_transport"] = "assume_ok"
    assert "unsafe_exit_semantics" in validate_contract(changed)


def test_missing_human_cost_evidence_fails_closed() -> None:
    changed = copy.deepcopy(load_contract())
    changed["measurement"]["require_assurance_labor_intervals"] = False
    assert "incomplete_measurement" in validate_contract(changed)


def test_downgrading_drift_tolerance_is_rejected() -> None:
    changed = copy.deepcopy(load_contract())
    changed["pilot_acceptance_thresholds"]["max_contract_drift_events"] = 1
    assert "unsafe_thresholds" in validate_contract(changed)


def test_probe_threshold_must_not_replace_realistic_scope() -> None:
    changed = copy.deepcopy(load_contract())
    changed["domain"]["environments"] = ["production"]
    assert "unbounded_environment" in validate_contract(changed)
