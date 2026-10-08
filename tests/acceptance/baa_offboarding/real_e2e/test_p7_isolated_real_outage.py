"""P7 actual disposable process-pause recovery controller conformance."""
from __future__ import annotations

import unittest

from p7_isolated_real_outage import execute_isolated_recovery


class Fixture:
    def __init__(self) -> None:
        self.paused = False
        self.was_paused = False
        self.unpause_calls = 0
        self.fail_control = False
        self.fail_baseline = False
        self.calls: list[str] = []

    def poll(self, source):
        self.calls.append(source)
        if self.fail_baseline and not self.was_paused and source == "odoo_root":
            return "transport_unknown", None, "fixture_transport"
        if self.paused and source == "keycloak_realm":
            return "transport_unknown", None, "fixture_paused"
        if self.paused and self.fail_control and source == "odoo_root":
            return "transport_unknown", None, "unexpected_control_failure"
        return (
            "ok",
            "qualified-allowlisted-contract"
            if source == "runtime_capabilities" else None,
            None,
        )

    def pause(self):
        self.was_paused = True
        self.paused = True

    def unpause(self):
        self.unpause_calls += 1
        self.paused = False


class IsolatedRealOutageTests(unittest.TestCase):
    def test_recovery_requires_real_observed_outage_and_two_clean_rounds(self):
        fixture = Fixture()
        tick = iter(range(10_000_000_000, 10_001_000_000, 500))
        result = execute_isolated_recovery(
            fixture.poll,
            pause=fixture.pause,
            unpause=fixture.unpause,
            sleep=lambda _: None,
            clock_ns=lambda: next(tick),
        )
        self.assertTrue(result["qualified"])
        self.assertTrue(result["actual_keycloak_outage_observed"])
        self.assertEqual(result["recovery_observation_rounds"], 2)
        self.assertEqual(result["assessment"]["status"], "verified_recovered_evidence")
        self.assertEqual(result["snapshot"]["rounds"], 4)
        self.assertEqual(result["snapshot"]["samples"], 16)
        self.assertTrue(result["unpause_succeeded"])
        self.assertEqual(fixture.unpause_calls, 1)
        self.assertFalse(fixture.paused)
        self.assertEqual(result["real_business_effect_count"], 0)

    def test_no_observed_outage_is_failure_even_if_all_healthy(self):
        fixture = Fixture()
        result = execute_isolated_recovery(
            fixture.poll, pause=lambda: None, unpause=fixture.unpause,
        )
        self.assertFalse(result["qualified"])
        self.assertFalse(result["actual_keycloak_outage_observed"])
        self.assertEqual(result["failure_reason"], "outage_or_control_discrimination_failed")
        self.assertEqual(fixture.unpause_calls, 1)
        self.assertEqual(result["recovery_observation_rounds"], 0)

    def test_unexpected_control_loss_fails_without_recovery_claim(self):
        fixture = Fixture()
        fixture.fail_control = True
        result = execute_isolated_recovery(
            fixture.poll, pause=fixture.pause, unpause=fixture.unpause,
        )
        self.assertFalse(result["qualified"])
        self.assertTrue(result["actual_keycloak_outage_observed"])
        self.assertFalse(result["other_three_sources_remained_ok_in_fault_round"])
        self.assertFalse(fixture.paused)

    def test_preexisting_failure_is_not_a_qualified_fault_episode(self):
        fixture = Fixture()
        fixture.fail_baseline = True
        result = execute_isolated_recovery(
            fixture.poll, pause=fixture.pause, unpause=fixture.unpause,
        )
        self.assertFalse(result["qualified"])
        self.assertFalse(result["pause_attempted"])
        self.assertEqual(fixture.unpause_calls, 0)
        self.assertEqual(result["failure_reason"], "pre_fault_baseline_not_qualified")

    def test_pause_error_always_attempts_unpause(self):
        fixture = Fixture()
        def broken_pause():
            fixture.paused = True
            raise TimeoutError("never publish docker stderr or credentials")
        result = execute_isolated_recovery(
            fixture.poll, pause=broken_pause, unpause=fixture.unpause,
        )
        self.assertFalse(result["qualified"])
        self.assertTrue(result["unpause_attempted"])
        self.assertEqual(fixture.unpause_calls, 1)
        self.assertFalse(fixture.paused)
        self.assertNotIn("never publish", str(result))
        self.assertEqual(result["failure_class"], "TimeoutError")

    def test_unpause_failure_blocks_qualification(self):
        fixture = Fixture()
        def broken_unpause():
            fixture.unpause_calls += 1
            raise RuntimeError("confidential host diagnostics")
        result = execute_isolated_recovery(
            fixture.poll, pause=fixture.pause, unpause=broken_unpause,
        )
        self.assertFalse(result["qualified"])
        self.assertEqual(result["failure_reason"], "failed_to_unpause_isolated_service")
        self.assertEqual(result["recovery_observation_rounds"], 0)
        self.assertNotIn("confidential host diagnostics", str(result))


if __name__ == "__main__":
    unittest.main()
