"""P6 timing instrument conformance (no network, no production effects)."""
from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from p6_quality import QualityRecorder, TimedEffectProvider


class FixtureProvider:
    def __init__(self) -> None:
        self.payloads: list[dict[str, object]] = []
        self.execute_count = 0
        self.observe_count = 0

    def execute(self, effect, payload):
        self.execute_count += 1
        self.payloads.append(payload)
        return SimpleNamespace(status="succeeded", provider_ref="opaque:1")

    def observe(self, effect):
        self.observe_count += 1
        return SimpleNamespace(availability="available", state={"secret": "never-log-me"})


class QualityTests(unittest.TestCase):
    def test_provider_results_and_dispatch_are_not_changed(self):
        clock = iter((100, 1_100, 2_000, 3_000))
        recorder = QualityRecorder(clock_ns=lambda: next(clock))
        provider = FixtureProvider()
        measured = TimedEffectProvider(provider, recorder)
        effect = SimpleNamespace(operation="identity.disable")
        payload = {"password": "DO_NOT_LOG"}

        executed = measured.execute(effect, payload)
        observed = measured.observe(effect)
        self.assertEqual(executed.status, "succeeded")
        self.assertEqual(observed.availability, "available")
        self.assertEqual(provider.execute_count, 1)
        self.assertEqual(provider.observe_count, 1)
        self.assertEqual(provider.payloads, [payload])

        report = recorder.report(scenario="normal")
        encoded = json.dumps(report)
        self.assertNotIn("DO_NOT_LOG", encoded)
        self.assertNotIn("never-log-me", encoded)
        self.assertNotIn("opaque:1", encoded)
        self.assertEqual(report["sample_count"], 2)
        self.assertEqual(
            report["stage_summaries"]["gate_execute_including_admission_dispatch_readback"]["p50_ms"],
            0.001,
        )
        self.assertFalse(report["percentiles_establish_production_slo"])

    def test_exception_is_rethrown_but_record_is_secret_free(self):
        clock = iter((1, 5))
        recorder = QualityRecorder(clock_ns=lambda: next(clock))
        def fail():
            raise ValueError("sensitive internal provider response")
        with self.assertRaisesRegex(ValueError, "sensitive internal"):
            recorder.measure(
                "gate_execute_including_admission_dispatch_readback",
                "identity.disable",
                fail,
            )
        report = recorder.report(scenario="lost_ack")
        data = json.dumps(report)
        self.assertNotIn("sensitive internal", data)
        self.assertEqual(report["records"][0]["result"], "exception")
        self.assertEqual(report["records"][0]["exception_class"], "ValueError")

    def test_bounded_recording_preserves_overflow_as_disqualification(self):
        clock = iter(range(6))
        recorder = QualityRecorder(max_observations=2, clock_ns=lambda: next(clock))
        for _ in range(3):
            recorder.measure("engine_drive", "secret", lambda: None)
        data = recorder.report(scenario="normal")
        self.assertEqual(data["sample_count"], 2)
        self.assertEqual(data["overflow_count"], 1)
        self.assertFalse(data["instrument_complete"])

    def test_latency_quantiles_are_descriptive_and_empty_stage_not_invented(self):
        clock = iter((0, 1_000_000, 2_000_000, 5_000_000))
        recorder = QualityRecorder(clock_ns=lambda: next(clock))
        for _ in range(2):
            recorder.measure("engine_drive", "", lambda: None)
        data = recorder.report(scenario="normal")
        drive = data["stage_summaries"]["engine_drive"]
        empty = data["stage_summaries"]["gate_observe_including_independent_readback"]
        self.assertEqual(drive["n"], 2)
        self.assertEqual(drive["p50_ms"], 2.0)
        self.assertEqual(drive["p95_ms"], 2.9)
        self.assertEqual(empty["n"], 0)
        self.assertIsNone(empty["p99_ms"])
        self.assertFalse(drive["tail_latency_qualified"])

    def test_untrusted_operation_and_outcome_are_sanitized(self):
        clock = iter((1, 2))
        recorder = QualityRecorder(clock_ns=lambda: next(clock))
        recorder.measure(
            "gate_execute_including_admission_dispatch_readback",
            "secrets-in-operation-name",
            lambda: SimpleNamespace(status="raw-secret"),
            status_from=lambda result: result.status,
        )
        data = recorder.report(scenario="normal")
        item = data["records"][0]
        self.assertEqual(item["operation"], "other")
        self.assertEqual(item["result"], "not_applicable")
        self.assertNotIn("secret", json.dumps(data))

    def test_bad_metric_configuration_fails_before_action(self):
        recorder = QualityRecorder()
        ran = []
        with self.assertRaises(ValueError):
            recorder.measure("not-a-metric", "none", lambda: ran.append(True))
        self.assertEqual(ran, [])
        with self.assertRaises(ValueError):
            QualityRecorder(max_observations=0)


if __name__ == "__main__":
    unittest.main()
