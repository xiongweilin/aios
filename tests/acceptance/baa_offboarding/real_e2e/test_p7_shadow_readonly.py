"""Offline P7 shadow conformance; no network or write operations."""
from __future__ import annotations

import json
import unittest

from p7_shadow_readonly import (
    EXPECTED_EFFECTS,
    SOURCES,
    ShadowMonitor,
    qualified_contract_fingerprint,
)


def capability_rules():
    return [
        {
            "capability": name,
            "authorization_required": True,
            "resource_required": True,
            "version_required": True,
        }
        for name in sorted(EXPECTED_EFFECTS)
    ]


class ShadowTests(unittest.TestCase):
    def test_fingerprint_requires_complete_enforced_contracts(self):
        rules = capability_rules()
        correct = qualified_contract_fingerprint({"effect_rules": rules})
        self.assertIsInstance(correct, str)
        self.assertEqual(len(correct), 64)
        self.assertEqual(
            correct,
            qualified_contract_fingerprint({"effect_rules": list(reversed(rules))}),
        )
        self.assertIsNone(qualified_contract_fingerprint({"effect_rules": rules[:-1]}))
        weakened = [dict(item) for item in rules]
        weakened[0]["authorization_required"] = False
        self.assertIsNone(qualified_contract_fingerprint({"effect_rules": weakened}))
        malformed = [dict(item) for item in rules]
        malformed[0]["version_required"] = "true"
        self.assertIsNone(qualified_contract_fingerprint({"effect_rules": malformed}))
        self.assertIsNone(qualified_contract_fingerprint({"effect_rules": rules + rules[:1]}))
        self.assertIsNone(qualified_contract_fingerprint({"effect_rules": []}))

    def test_polling_records_complete_round_and_no_raw_payloads(self):
        seen = []
        def poll(source):
            seen.append(source)
            if source == "runtime_capabilities":
                return "ok", "safe-hash", None
            return "ok", None, None

        monotonic = iter(range(100, 150))
        monitor = ShadowMonitor(poll, monotonic_ns=lambda: next(monotonic))
        rows = monitor.sample_round()
        self.assertEqual(tuple(seen), SOURCES)
        self.assertEqual(len(rows), 4)
        report = monitor.report()
        self.assertEqual(report["rounds"], 1)
        self.assertEqual(report["samples"], 4)
        self.assertEqual(report["failure_counts"]["runtime_capabilities"], 0)
        self.assertTrue(report["contract_completeness_all_rounds"])
        self.assertFalse(report["eligible_for_long_horizon_claim"])

    def test_drift_and_missingness_are_not_hidden(self):
        fingerprints = iter(("first", "second"))
        def poll(source):
            if source == "runtime_capabilities":
                return "ok", next(fingerprints), None
            if source == "keycloak_realm":
                return "transport_unknown", None, "transport_unavailable"
            return "ok", None, None

        ticks = iter(range(100, 300))
        monitor = ShadowMonitor(poll, monotonic_ns=lambda: next(ticks))
        monitor.sample_round()
        monitor.sample_round()
        report = monitor.report()
        self.assertTrue(report["contract_drift_observed"])
        self.assertEqual(report["failure_counts"]["keycloak_realm"], 2)
        self.assertFalse(report["qualified_production_slo"])
        self.assertEqual(report["contract_fingerprint_count"], 2)

    def test_exception_class_not_secret_text_in_report(self):
        def poll(source):
            if source == "odoo_root":
                raise RuntimeError("SECRET_TOKEN_NEVER_ARCHIVE")
            return "ok", "contract" if source == "runtime_capabilities" else None, None
        monitor = ShadowMonitor(poll)
        monitor.sample_round()
        data = json.dumps(monitor.report())
        self.assertNotIn("SECRET_TOKEN", data)
        self.assertIn("RuntimeError", data)
        self.assertEqual(monitor.report()["failure_counts"]["odoo_root"], 1)

    def test_invalid_capacity_and_overflow_do_not_disappear(self):
        with self.assertRaises(ValueError):
            ShadowMonitor(lambda _: ("ok", None, None), max_rounds=0)
        monitor = ShadowMonitor(lambda _: ("ok", None, None), max_rounds=1)
        monitor.sample_round()
        with self.assertRaisesRegex(RuntimeError, "capacity reached"):
            monitor.sample_round()
        self.assertEqual(monitor.report()["rounds"], 1)

    def test_unknown_result_cannot_be_promoted_to_success(self):
        monitor = ShadowMonitor(lambda _: ("not-verifiable", None, None))
        monitor.sample_round()
        result = monitor.report()
        self.assertEqual(result["failure_counts"]["runtime_capabilities"], 1)
        self.assertFalse(result["contract_completeness_all_rounds"])


if __name__ == "__main__":
    unittest.main()
