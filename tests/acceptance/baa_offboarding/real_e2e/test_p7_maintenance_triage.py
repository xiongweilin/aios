"""P7 read-only maintenance decision tests, no services or credentials."""
from __future__ import annotations

import unittest
from unittest.mock import patch

import p7_maintenance_experiment as experiment
from p7_maintenance_triage import TriageStatus, assess_maintenance
from p7_shadow_readonly import Observation, SOURCES


def rows(
    *,
    rounds: int = 4,
    anomaly: tuple[int, str, str] | None = None,
    drift: bool = False,
) -> tuple[Observation, ...]:
    values = []
    for number in range(rounds):
        for source in SOURCES:
            result = "ok"
            error = None
            if anomaly and (number, source) == anomaly[:2]:
                result = anomaly[2]
                error = "injected_observer_test"
            fingerprint = (
                ("baseline" if number < 2 else "changed")
                if drift else "baseline"
            ) if source == "runtime_capabilities" and result == "ok" else None
            values.append(
                Observation(
                    source=source, round_number=number,
                    started_ns=number * 1_000_000 + len(values) * 100,
                    completed_ns=number * 1_000_000 + len(values) * 100 + 20,
                    result=result,
                    capability_fingerprint=fingerprint,
                    error_class=error,
                )
            )
    return tuple(values)


class MaintenanceTriageTests(unittest.TestCase):
    def test_stable_fully_observed_multi_service(self):
        result = assess_maintenance(rows())
        self.assertEqual(result.status, TriageStatus.VERIFIED_STABLE)
        self.assertEqual(result.observed_probes, 16)
        self.assertFalse(result.observation_unknown_encountered)
        self.assertFalse(result.terminal_unresolved)
        self.assertFalse(result.public()["principal_attention_measured"])

    def test_probe_loss_requires_two_fresh_complete_rounds(self):
        evidence = rows(anomaly=(1, "keycloak_realm", "transport_unknown"))
        result = assess_maintenance(evidence)
        self.assertEqual(result.status, TriageStatus.VERIFIED_RECOVERED)
        self.assertEqual(result.evidence_reacquisition_rounds, 2)
        self.assertTrue(result.observation_unknown_encountered)
        self.assertFalse(result.terminal_unresolved)

        truncated = assess_maintenance(evidence[:-len(SOURCES)])
        self.assertEqual(truncated.status, TriageStatus.UNRESOLVED)
        self.assertTrue(truncated.terminal_unresolved)

    def test_missing_initial_baseline_never_silently_becomes_healthy(self):
        result = assess_maintenance(rows(anomaly=(0, "odoo_root", "transport_unknown")))
        self.assertEqual(result.status, TriageStatus.UNRESOLVED)
        self.assertEqual(result.reason, "no_qualified_initial_baseline")

    def test_contract_schema_weakening_requires_escalation_even_if_recovered(self):
        result = assess_maintenance(rows(anomaly=(1, "runtime_capabilities", "schema_unknown")))
        self.assertEqual(result.status, TriageStatus.ESCALATE)
        self.assertTrue(result.contract_escalation)
        self.assertFalse(result.terminal_unresolved)
        self.assertTrue(result.observation_unknown_encountered)

    def test_fingerprint_drift_is_escalation_without_modifying_services(self):
        result = assess_maintenance(rows(drift=True))
        self.assertEqual(result.status, TriageStatus.ESCALATE)

    def test_incomplete_duplicate_reordered_evidence_is_rejected(self):
        baseline = rows()
        with self.assertRaisesRegex(ValueError, "complete"):
            assess_maintenance(baseline[:-1])
        reordered = baseline[:1] + (baseline[2], baseline[1]) + baseline[3:]
        with self.assertRaisesRegex(ValueError, "ordering"):
            assess_maintenance(reordered)
        with self.assertRaises(ValueError):
            assess_maintenance(baseline, required_clean_recovery_rounds=1)

    def test_frozen_scenarios_use_live_readonly_probe_except_declared_injection(self):
        calls = []
        def fake_probe(**kwargs):
            calls.append(kwargs["source"])
            source = kwargs["source"]
            return "ok", "baseline" if source == "runtime_capabilities" else None, None

        with patch.object(experiment, "read_only_probe", side_effect=fake_probe):
            result_normal = experiment.run_scenario(
                "normal", runtime_base="fixture",
                keycloak_base="fixture", odoo_base="fixture", runtime_token="not-recorded",
            )
            result_gap = experiment.run_scenario(
                "observer_transport_gap", runtime_base="fixture",
                keycloak_base="fixture", odoo_base="fixture", runtime_token="not-recorded",
            )
            result_contract = experiment.run_scenario(
                "observer_contract_anomaly", runtime_base="fixture",
                keycloak_base="fixture", odoo_base="fixture", runtime_token="not-recorded",
            )

        for case, expected in (
            (result_normal, TriageStatus.VERIFIED_STABLE.value),
            (result_gap, TriageStatus.VERIFIED_RECOVERED.value),
            (result_contract, TriageStatus.ESCALATE.value),
        ):
            self.assertTrue(case["qualified"])
            self.assertEqual(case["assessment"]["status"], expected)
            self.assertEqual(len(case["records"]), 16)
            self.assertNotIn("not-recorded", str(case))
        self.assertEqual(
            [result_normal["real_http_get_attempts"],
             result_gap["real_http_get_attempts"],
             result_contract["real_http_get_attempts"]],
            [16, 15, 15],
        )
        self.assertEqual(len(calls), 46)


if __name__ == "__main__":
    unittest.main()
