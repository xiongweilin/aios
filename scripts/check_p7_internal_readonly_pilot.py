"""Static fail-closed qualification for the P7 internal read-only pilot v1.

Validates the preregistered design only. It DOES NOT grant permission to run
against an internal staging endpoint, verify external approval signatures,
or evaluate empirical performance.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CONTRACT = (
    Path(__file__).resolve().parents[1]
    / "tests/acceptance/baa_offboarding/p7_internal_readonly_pilot_v1.json"
)
EXPECTED_SOURCES = (
    ("runtime_health", "/healthz"),
    ("runtime_capabilities", "/v1/capabilities"),
    ("keycloak_realm", "/realms/{approved_realm}"),
    ("odoo_root", "/"),
)
REQUIRED_ACTIVATION = frozenset({
    "named_accountable_owner",
    "named_on_duty_operator",
    "written_scoped_staging_read_authorization",
    "four_source_resource_inventory",
    "read_only_credential_scope_proof",
    "approved_start_end_time",
    "independent_stop_access",
    "private_contact_route",
    "artifact_access_and_retention_review",
})
REQUIRED_EXIT_TRIGGERS = frozenset({
    "auth_401_or_403",
    "security_contract_invalid_or_weakened",
    "security_contract_fingerprint_drift",
    "resource_scope_change",
    "probe_method_not_get",
    "missing_on_duty_operator",
    "missing_or_stale_approval",
    "evidence_integrity_failure",
    "cannot_stop_sampler",
    "secret_leak_suspected",
    "uncategorized_observation",
    "time_budget_exceeded",
})


def _nonnegative_integer(value: Any, *, positive: bool = False) -> bool:
    return type(value) is int and value >= (1 if positive else 0)


def validate_contract(contract: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if contract.get("schema") != "aios-p7-internal-readonly-pilot-contract-v1":
        errors.append("wrong_schema")
    if contract.get("version") != 1 or contract.get("status") != "design_frozen_not_authorized":
        errors.append("not_frozen_unapproved_design")

    activation = contract.get("activation", {})
    if not isinstance(activation, dict):
        return errors + ["missing_activation"]
    if (
        activation.get("default") != "deny"
        or activation.get("approved") is not False
        or activation.get("no_automatic_activation") is not True
        or activation.get("no_cron") is not True
        or activation.get("no_production_write") is not True
    ):
        errors.append("unsafe_activation")
    if not REQUIRED_ACTIVATION.issubset(set(activation.get("requires", []))):
        errors.append("activation_requirements_missing")

    domain = contract.get("domain", {})
    if not isinstance(domain, dict):
        return errors + ["missing_domain"]
    if domain.get("environments") != ["approved_internal_staging_only"]:
        errors.append("unbounded_environment")
    if domain.get("real_access_probe") is not False:
        errors.append("unapproved_access_probe")
    if set(domain.get("fixed_security_contract", [])) != {
        "administrative.iam.identity.disable.v1",
        "administrative.iam.sessions.revoke.v1",
        "administrative.hris.employee.deactivate.v1",
    }:
        errors.append("security_contract_scope_drift")
    sources = domain.get("allowed_sources", [])
    if not isinstance(sources, list) or [
        (s.get("id"), s.get("path")) for s in sources if isinstance(s, dict)
    ] != list(EXPECTED_SOURCES) or len(sources) != 4:
        errors.append("wrong_source_allowlist")
    if any(s.get("method") != "GET" for s in sources if isinstance(s, dict)):
        errors.append("effectful_method")
    if not {"POST", "PUT", "PATCH", "DELETE", "provider_execute", "model_generation", "automatic_repair"}.issubset(
        set(domain.get("prohibited", []))
    ):
        errors.append("prohibited_operations_incomplete")

    horizon = contract.get("horizon", {})
    if not isinstance(horizon, dict):
        return errors + ["missing_horizon"]
    fields = ("supervised_window_seconds", "interval_seconds", "planned_rounds",
              "sources_per_round", "planned_slots", "per_request_timeout_seconds",
              "max_attempts_per_slot", "clean_reacquisition_rounds")
    if not all(_nonnegative_integer(horizon.get(k), positive=True) for k in fields):
        errors.append("invalid_horizon_values")
    else:
        if (
            horizon["supervised_window_seconds"] != 14400
            or horizon["interval_seconds"] != 60
            or horizon["planned_rounds"] != horizon["supervised_window_seconds"] // horizon["interval_seconds"]
            or horizon["sources_per_round"] != 4
            or horizon["planned_slots"] != horizon["planned_rounds"] * 4
            or horizon["per_request_timeout_seconds"] != 3
            or horizon["max_attempts_per_slot"] != 1
            or horizon["clean_reacquisition_rounds"] != 2
            or horizon.get("baseline_required") is not True
            or horizon.get("stop_after_window") is not True
        ):
            errors.append("pilot_horizon_drift")

    thresholds = contract.get("pilot_acceptance_thresholds", {})
    if not isinstance(thresholds, dict):
        return errors + ["missing_thresholds"]
    positive = [
        "planned_slots_accounted_exactly", "min_complete_rounds",
        "max_unscheduled_sample_gap_seconds", "max_probe_p95_ms", "max_round_p95_ms",
        "max_principal_attention_minutes", "max_third_party_assurance_labor_minutes",
        "max_operator_acknowledgement_seconds", "max_observation_reacquisition_seconds",
    ]
    if not all(_nonnegative_integer(thresholds.get(k), positive=True) for k in positive):
        errors.append("invalid_thresholds")
    if (
        thresholds.get("planned_slots_accounted_exactly") != horizon.get("planned_slots")
        or thresholds.get("min_complete_rounds") != horizon.get("planned_rounds")
        or thresholds.get("max_unclassified_slots") != 0
        or thresholds.get("max_missing_evidence_rounds") != 0
        or thresholds.get("max_contract_drift_events") != 0
        or thresholds.get("max_unauthorized_or_effectful_calls") != 0
        or thresholds.get("max_terminal_unresolved") != 0
        or thresholds.get("expected_external_business_effect_count") != 0
        or type(thresholds.get("max_non_ok_probe_fraction")) is not float
        or thresholds.get("max_non_ok_probe_fraction") != 0.01
        or thresholds.get("measurement_kind") != "prospective_initial_pilot_acceptance_not_production_slo"
    ):
        errors.append("unsafe_thresholds")

    expected_thresholds = {
        "measurement_kind": "prospective_initial_pilot_acceptance_not_production_slo",
        "planned_slots_accounted_exactly": 960,
        "min_complete_rounds": 240,
        "max_unclassified_slots": 0,
        "max_missing_evidence_rounds": 0,
        "max_unscheduled_sample_gap_seconds": 120,
        "max_probe_p95_ms": 2000,
        "max_round_p95_ms": 10000,
        "max_non_ok_probe_fraction": 0.01,
        "max_contract_drift_events": 0,
        "max_unauthorized_or_effectful_calls": 0,
        "max_terminal_unresolved": 0,
        "max_principal_attention_minutes": 30,
        "max_third_party_assurance_labor_minutes": 60,
        "max_operator_acknowledgement_seconds": 900,
        "max_observation_reacquisition_seconds": 300,
        "expected_external_business_effect_count": 0,
    }
    if thresholds != expected_thresholds:
        errors.append("frozen_threshold_drift")

    exit_rules = contract.get("escalation_and_exit", {})
    if not isinstance(exit_rules, dict):
        return errors + ["missing_exit_rules"]
    if not REQUIRED_EXIT_TRIGGERS.issubset(set(exit_rules.get("fail_closed_on", []))):
        errors.append("missing_stop_condition")
    if (
        exit_rules.get("unknown_transport") != "record_unknown_no_success_inference"
        or exit_rules.get("allow_recovery_classification_only_after_full_clean_rounds") != 2
        or exit_rules.get("contract_or_authority_discrepancy") != "sticky_human_escalation_no_autoclear"
        or exit_rules.get("operator_unavailable") != "stop_sampling_no_automatic_takeover"
        or exit_rules.get("no_write_recovery") is not True
        or exit_rules.get("do_not_erase_unknown_at_timeout") is not True
    ):
        errors.append("unsafe_exit_semantics")

    measurement = contract.get("measurement", {})
    if not isinstance(measurement, dict):
        return errors + ["missing_measurement"]
    if (
        measurement.get("all_assigned_windows_denominator") is not True
        or measurement.get("require_evidence_sha256") is not True
        or measurement.get("require_operator_approval_reference") is not True
        or measurement.get("require_operator_response_timestamps") is not True
        or measurement.get("require_principal_attention_intervals") is not True
        or measurement.get("require_assurance_labor_intervals") is not True
        or measurement.get("evidence_retention_days") != 14
    ):
        errors.append("incomplete_measurement")

    decisions = contract.get("decisions", {})
    if not isinstance(decisions, dict) or decisions.get("no_agent_or_three_arm_comparison") is not True or decisions.get("reject_or_stop_if_any_requirement_unmet") is not True:
        errors.append("invalid_claim_or_go_rule")

    return errors


def main() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    errors = validate_contract(contract)
    if errors:
        raise SystemExit("P7 pilot contract invalid: " + ", ".join(errors))
    print("P7 pilot design qualified; execution NOT authorized.")


if __name__ == "__main__":
    main()
