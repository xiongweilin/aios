"""P3 point-sampling timeline tests; no continuous outcome is assumed."""
from __future__ import annotations

import unittest

from baa_protocol.temporal_outcome import AccessProbe
from p3_probe_timeline import (
    AccessTimelineSampler,
    ProbeRecord,
    ProbeTarget,
    access_cutover_candidate,
)


def record(
    seq: int,
    access: AccessProbe,
    label: str = "target",
) -> ProbeRecord:
    return ProbeRecord(
        label=label,
        phase="fixture",
        sequence=seq,
        mono_start_ns=seq * 1_000_000_000,
        mono_end_ns=seq * 1_000_000_000 + 30_000_000,
        wall_start_ns=seq * 1_000_000_000,
        wall_end_ns=seq * 1_000_000_000 + 30_000_000,
        access=access,
    )


class ProbeTimelineTests(unittest.TestCase):
    def test_cutover_bracket_includes_request_envelopes(self):
        records = (
            record(1, AccessProbe.ALLOW),
            record(2, AccessProbe.UNKNOWN),
            record(3, AccessProbe.DENY),
            record(4, AccessProbe.DENY),
        )
        result = access_cutover_candidate(records, "target")
        bracket = result["candidate_single_change_bracket"]
        self.assertIsNotNone(bracket)
        assert isinstance(bracket, dict)
        self.assertEqual(bracket["earliest_monotonic_ns"], 1_000_000_000)
        self.assertEqual(bracket["latest_monotonic_ns"], 3_030_000_000)
        self.assertEqual(result["unknown_count"], 1)
        self.assertFalse(result["single_change_assumption_qualified"])
        self.assertFalse(result["continuous_outcome_identified"])

    def test_reversal_is_reported_not_suppressed(self):
        records = (
            record(1, AccessProbe.ALLOW),
            record(2, AccessProbe.DENY),
            record(3, AccessProbe.ALLOW),
            record(4, AccessProbe.DENY),
        )
        result = access_cutover_candidate(records, "target")
        self.assertEqual(result["observed_deny_to_allow_reversals"], 1)
        self.assertFalse(result["continuous_outcome_identified"])

    def test_no_allow_before_deny_means_no_transition_bracket(self):
        result = access_cutover_candidate(
            (record(1, AccessProbe.UNKNOWN), record(2, AccessProbe.DENY)),
            "target",
        )
        self.assertIsNone(result["candidate_single_change_bracket"])

    def test_collector_is_bounded_and_keeps_failures_unknown(self):
        states = iter((AccessProbe.ALLOW, RuntimeError("secret detail")))
        def sample():
            item = next(states)
            if isinstance(item, Exception):
                raise item
            return item

        times = iter(range(100, 400))
        sampler = AccessTimelineSampler(
            (ProbeTarget("target", sample),),
            max_rounds=2,
            monotonic_ns=lambda: next(times),
            wall_ns=lambda: next(times),
        )
        first = sampler.capture_once()
        second = sampler.capture_once()
        third = sampler.capture_once()
        self.assertEqual(first[0].access, AccessProbe.ALLOW)
        self.assertEqual(second[0].access, AccessProbe.UNKNOWN)
        self.assertEqual(second[0].error_type, "RuntimeError")
        self.assertEqual(third, ())
        data = sampler.evidence()
        self.assertTrue(data["capacity_reached"])
        self.assertEqual(data["rounds_sampled"], 2)
        self.assertNotIn("secret detail", str(data))
        self.assertEqual(len(data["records"]), 2)

    def test_two_subjects_and_background_thread_can_stop(self):
        sampler = AccessTimelineSampler(
            (
                ProbeTarget("target", lambda: AccessProbe.DENY),
                ProbeTarget("control", lambda: AccessProbe.ALLOW),
            ),
            interval_s=0.01,
            max_rounds=8,
        )
        sampler.capture_once("before_driver")
        sampler.start()
        sampler.stop()
        report = sampler.evidence()
        self.assertGreaterEqual(report["rounds_sampled"], 1)
        self.assertEqual(
            report["cutover_candidates"]["control"]["unknown_count"], 0
        )
        self.assertEqual(len(sampler.snapshot()) % 2, 0)

    def test_reject_bad_target_set_and_backward_request_time(self):
        with self.assertRaises(ValueError):
            AccessTimelineSampler(())
        with self.assertRaises(ValueError):
            AccessTimelineSampler((
                ProbeTarget("target", lambda: AccessProbe.ALLOW),
                ProbeTarget("target", lambda: AccessProbe.DENY),
            ))
        with self.assertRaises(ValueError):
            ProbeRecord(
                "target", "bad", 1, 100, 90, 100, 90, AccessProbe.UNKNOWN
            )

    def test_wrong_type_is_unknown_not_denial(self):
        sampler = AccessTimelineSampler(
            (ProbeTarget("target", lambda: False),)
        )
        readings = sampler.capture_once()
        self.assertEqual(readings[0].access, AccessProbe.UNKNOWN)
        self.assertEqual(readings[0].error_type, "TypeError")


if __name__ == "__main__":
    unittest.main()
