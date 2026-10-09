from __future__ import annotations

import ast
import hashlib
import io
import json
import queue
import tempfile
import unittest
import urllib.error
from datetime import UTC, datetime, timedelta
from pathlib import Path

import p7_internal_readonly_pilot as pilot
import p7_readonly_runtime_proxy as runtime_proxy
import p7_shadow_readonly as legacy_shadow

FINGERPRINT_A = "a" * 64
FINGERPRINT_B = "b" * 64
PILOT_START = datetime(2035, 1, 1, tzinfo=UTC)


def make_activation() -> pilot.Activation:
    resources = {
        "runtime_health": "https://runtime.example/healthz",
        "runtime_capabilities": "https://runtime.example/v1/capabilities",
        "keycloak_realm": "https://keycloak.example/realms/staging",
        "odoo_root": "https://odoo.example/",
    }
    inventory = json.dumps(resources, sort_keys=True, separators=(",", ":")).encode("utf-8")
    references = {key: f"ref-{key}" for key in pilot.REFERENCE_KEYS}
    return pilot.Activation(
        references=references,
        resources=resources,
        auth_modes={
            "runtime_capabilities": "bearer",
            "keycloak_realm": "none",
            "odoo_root": "none",
        },
        runtime_delegation_id="delegation:p7-internal-readonly-pilot-test",
        approved_realm="staging",
        preflight_start=PILOT_START - timedelta(minutes=20),
        preflight_end=PILOT_START - timedelta(minutes=10),
        pilot_start=PILOT_START,
        pilot_end=PILOT_START + timedelta(seconds=pilot.PILOT_WINDOW_SECONDS),
        resource_inventory_sha256=hashlib.sha256(inventory).hexdigest(),
    )


class FakeClock:
    def __init__(self, wall_start: datetime = PILOT_START, monotonic_start_ns: int = 5_000_000_000) -> None:
        self.anchor_wall = wall_start
        self.anchor_mono_ns = monotonic_start_ns
        self.now_ns = monotonic_start_ns

    def monotonic_ns(self) -> int:
        return self.now_ns

    def wall_clock(self) -> datetime:
        elapsed = (self.now_ns - self.anchor_mono_ns) / 1_000_000_000
        return self.anchor_wall + timedelta(seconds=elapsed)

    def advance_ns(self, duration_ns: int) -> None:
        self.now_ns += max(0, duration_ns)

    def advance_seconds(self, seconds: float) -> None:
        self.advance_ns(int(seconds * 1_000_000_000))

    def at_seconds(self, seconds: float) -> int:
        return self.anchor_mono_ns + int(seconds * 1_000_000_000)


class FakeOperator:
    def __init__(self, clock: FakeClock, scheduled: list[tuple[float, str]] | None = None) -> None:
        self.clock = clock
        self.events: queue.Queue[tuple[str, int, datetime]] = queue.Queue()
        self.events.put(("ON-DUTY", clock.monotonic_ns(), clock.wall_clock()))
        self.scheduled = sorted(
            (clock.at_seconds(second), command) for second, command in (scheduled or [])
        )

    def drain(self) -> list[tuple[str, int, datetime]]:
        drained = []
        while True:
            try:
                drained.append(self.events.get_nowait())
            except queue.Empty:
                return drained

    def next_event(self, timeout_s: float) -> tuple[str, int, datetime] | None:
        deadline_ns = self.clock.monotonic_ns() + int(timeout_s * 1_000_000_000)
        if self.scheduled and self.scheduled[0][0] <= deadline_ns:
            scheduled_ns, command = self.scheduled.pop(0)
            event_ns = max(self.clock.monotonic_ns(), scheduled_ns)
            self.clock.now_ns = event_ns
            return command, event_ns, self.clock.wall_clock()
        self.clock.advance_ns(deadline_ns - self.clock.monotonic_ns())
        return None


class FakeResponse:
    def __init__(self, status: int = 200, body: bytes = b"") -> None:
        self.status = status
        self.body = body
        self.closed = False

    def read(self, _limit: int) -> bytes:
        return self.body

    def close(self) -> None:
        self.closed = True


class InternalReadonlyPilotTests(unittest.TestCase):
    def make_runner(
        self,
        root: Path,
        clock: FakeClock,
        probe,
        operator: FakeOperator,
    ) -> tuple[pilot.PilotRunner, pilot.EvidenceJournal]:
        journal = pilot.EvidenceJournal(root / "run", "test-run")
        runner = pilot.PilotRunner(
            make_activation(),
            journal,
            probe,
            operator,
            monotonic_ns=clock.monotonic_ns,
            wall_clock=clock.wall_clock,
        )
        return runner, journal

    def test_frozen_contract_and_legacy_observer_limit_are_unchanged(self) -> None:
        contract = json.loads(pilot.CONTRACT.read_text(encoding="utf-8"))
        self.assertEqual(pilot.validate_contract(contract), [])
        self.assertEqual(legacy_shadow.MAX_ROUNDS, 300)
        self.assertEqual(pilot.PILOT_WINDOW_SECONDS, contract["horizon"]["supervised_window_seconds"])
        self.assertEqual(pilot.INTERVAL_SECONDS, contract["horizon"]["interval_seconds"])
        self.assertEqual(pilot.PLANNED_ROUNDS, contract["horizon"]["planned_rounds"])
        self.assertEqual(pilot.PLANNED_SLOTS, contract["horizon"]["planned_slots"])
        self.assertEqual(pilot.REQUEST_TIMEOUT_SECONDS, contract["horizon"]["per_request_timeout_seconds"])
        self.assertEqual(contract["status"], "design_frozen_not_authorized")

    def test_activation_requires_exact_paths_and_https_for_bearer_credentials(self) -> None:
        activation_data = {
            "schema": pilot.ACTIVATION_SCHEMA,
            "references": {key: f"ref-{key}" for key in pilot.REFERENCE_KEYS},
            "attestations": {key: True for key in pilot.ATTESTATION_KEYS},
            "approved_realm": "staging",
            "resources": {
                "runtime_health": "https://runtime.example/healthz",
                "runtime_capabilities": "https://runtime.example/v1/capabilities",
                "keycloak_realm": "https://keycloak.example/realms/staging",
                "odoo_root": "https://odoo.example/",
            },
            "auth_modes": {
                "runtime_capabilities": "bearer",
                "keycloak_realm": "none",
                "odoo_root": "none",
            },
            "runtime_delegation_id": "delegation:p7-internal-readonly-pilot-test",
            "preflight_window": {
                "start_utc": pilot.utc_text(PILOT_START - timedelta(minutes=20)),
                "end_utc": pilot.utc_text(PILOT_START - timedelta(minutes=10)),
            },
            "pilot_window": {
                "start_utc": pilot.utc_text(PILOT_START),
                "end_utc": pilot.utc_text(PILOT_START + timedelta(seconds=pilot.PILOT_WINDOW_SECONDS)),
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            activation_path = Path(directory) / "activation.json"
            activation_path.write_text(json.dumps(activation_data), encoding="utf-8")
            self.assertEqual(pilot.load_activation(activation_path).resources["odoo_root"], "https://odoo.example/")

            activation_data["resources"]["runtime_capabilities"] = "http://runtime.example/v1/capabilities"
            activation_path.write_text(json.dumps(activation_data), encoding="utf-8")
            with self.assertRaisesRegex(pilot.PilotError, "authenticated_resource_requires_https"):
                pilot.load_activation(activation_path)

            activation_data["resources"]["runtime_capabilities"] = "http://127.0.0.1:28086/v1/capabilities"
            activation_path.write_text(json.dumps(activation_data), encoding="utf-8")
            self.assertEqual(
                pilot.load_activation(activation_path).resources["runtime_capabilities"],
                "http://127.0.0.1:28086/v1/capabilities",
            )

            activation_data["resources"]["runtime_capabilities"] = "https://runtime.example/admin"
            activation_path.write_text(json.dumps(activation_data), encoding="utf-8")
            with self.assertRaisesRegex(pilot.PilotError, "resource_scope_change"):
                pilot.load_activation(activation_path)

    def test_probe_is_single_get_and_redacts_terminal_http_details(self) -> None:
        activation = make_activation()
        headers = {source: {} for source in pilot.SOURCES}
        calls = []

        def opener(request, *, timeout):
            calls.append((request.get_method(), timeout))
            return FakeResponse()

        outcome = pilot.probe_once("runtime_health", activation, headers, open_request=opener)
        self.assertEqual(outcome.result, "ok")
        self.assertEqual(calls, [("GET", pilot.REQUEST_TIMEOUT_SECONDS)])

        outcome = pilot.probe_once(
            "runtime_health",
            activation,
            headers,
            open_request=lambda _request, timeout: FakeResponse(status=302),
        )
        self.assertEqual(outcome.terminal_reason, "unexpected_redirect")

        def unauthorized(_request, *, timeout):
            raise urllib.error.HTTPError(
                "https://private.invalid/secret-path",
                401,
                "unauthorized",
                None,
                io.BytesIO(b"private response body"),
            )

        outcome = pilot.probe_once("runtime_health", activation, headers, open_request=unauthorized)
        self.assertEqual(outcome.error_class, "http_401")
        self.assertEqual(outcome.terminal_reason, "http_401")
        self.assertNotIn("private.invalid", repr(outcome))
        self.assertNotIn("private response body", repr(outcome))

    def test_readonly_runtime_proxy_only_allows_scoped_gets(self) -> None:
        allow = runtime_proxy.request_is_allowed
        self.assertTrue(allow("GET", "/healthz", None, None, "p7-token", "delegation:p7"))
        self.assertTrue(allow(
            "GET", "/v1/capabilities", "Bearer p7-token", "delegation:p7", "p7-token", "delegation:p7"
        ))
        self.assertFalse(allow(
            "POST", "/v1/capabilities", "Bearer p7-token", "delegation:p7", "p7-token", "delegation:p7"
        ))
        self.assertFalse(allow(
            "GET", "/admin/realms", "Bearer p7-token", "delegation:p7", "p7-token", "delegation:p7"
        ))
        self.assertFalse(allow(
            "GET", "/v1/capabilities", "Bearer wrong", "delegation:p7", "p7-token", "delegation:p7"
        ))
        self.assertFalse(allow(
            "GET", "/v1/capabilities", "Bearer p7-token", "delegation:other", "p7-token", "delegation:p7"
        ))
        self.assertFalse(allow(
            "GET",
            "/v1/capabilities",
            "Bearer p7-token",
            "delegation:p7",
            "p7-token",
            "delegation:p7",
            now=PILOT_START + timedelta(seconds=1),
            expires_at=PILOT_START,
        ))

    def test_p7_local_fixture_imports_no_users_and_keeps_runtime_loopback_only(self) -> None:
        fixture_root = Path(__file__).resolve().parent
        realm = json.loads(
            (fixture_root / "p7-local" / "realm" / "baa-real-e2e-realm.json").read_text(
                encoding="utf-8"
            )
        )
        compose_overlay = (fixture_root / "p7-local-compose.yaml").read_text(encoding="utf-8")
        odoo_root = (
            fixture_root
            / "p7-local"
            / "odoo-addons"
            / "p7_root_health"
            / "controllers"
            / "main.py"
        ).read_text(encoding="utf-8")
        manifest_path = (
            fixture_root
            / "p7-local"
            / "odoo-addons"
            / "p7_root_health"
            / "__manifest__.py"
        )
        manifest_tree = ast.parse(manifest_path.read_text(encoding="utf-8"))
        manifest = ast.literal_eval(manifest_tree.body[0].value)
        self.assertEqual(realm["realm"], "baa-real-e2e")
        self.assertEqual(realm["users"], [])
        self.assertEqual(realm["clients"], [])
        self.assertIn("ports: !reset []", compose_overlay)
        self.assertIn("disable: true", compose_overlay)
        self.assertIn('127.0.0.1:${BAA_P7_RUNTIME_HOST_PORT', compose_overlay)
        self.assertIn("hr,p7_root_health", compose_overlay)
        self.assertIn("./p7-local/odoo-addons:/mnt/extra-addons:ro", compose_overlay)
        self.assertIn('methods=["GET"]', odoo_root)
        self.assertIn("save_session=False", odoo_root)
        self.assertIn("readonly=True", odoo_root)
        self.assertIn('"p7-local-odoo-root-ready\\n"', odoo_root)
        self.assertNotIn("request.env", odoo_root)
        self.assertNotIn("request.session", odoo_root)
        self.assertEqual(manifest["depends"], ["web"])
        self.assertFalse(manifest["application"])
        self.assertTrue(manifest["installable"])

    def test_preflight_proof_is_hash_bound_to_activation_and_instrument(self) -> None:
        activation = make_activation()
        records = []
        for index, source in enumerate(pilot.SOURCES):
            start = activation.preflight_start + timedelta(seconds=index * 2)
            end = start + timedelta(milliseconds=20)
            records.append(pilot.SlotRecord(
                slot_index=index,
                sample_round=0,
                source=source,
                method="GET",
                attempted=True,
                started_ns=index * 2_000_000_000,
                completed_ns=index * 2_000_000_000 + 20_000_000,
                started_at_utc=pilot.utc_text(start),
                completed_at_utc=pilot.utc_text(end),
                classified_result="ok",
                fingerprint_or_null=FINGERPRINT_A if source == "runtime_capabilities" else None,
                error_class_or_null=None,
            ))

        payload = pilot._preflight_payload(activation, records, True)
        with tempfile.TemporaryDirectory() as directory:
            proof_path = Path(directory) / "preflight.json"
            proof_path.write_text(json.dumps(payload), encoding="utf-8")
            digest = hashlib.sha256(proof_path.read_bytes()).hexdigest()
            proof_path.with_name("preflight.json.sha256").write_text(
                f"{digest}  preflight.json\n", encoding="ascii"
            )
            self.assertEqual(pilot.verify_preflight(proof_path, activation)["status"], "qualified")
            proof_path.write_text(proof_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
            with self.assertRaisesRegex(pilot.PilotError, "preflight_evidence_integrity_failure"):
                pilot.verify_preflight(proof_path, activation)

    def test_observation_event_chains_and_checkpoint_reconcile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            journal = pilot.EvidenceJournal(Path(directory) / "run", "chain-test")
            journal.append_event({
                "event": "operator_presence_ack",
                "at_utc": pilot.utc_text(PILOT_START),
                "monotonic_ns": 1,
            })
            journal.append_slot(pilot.SlotRecord(
                slot_index=0,
                sample_round=0,
                source=pilot.SOURCES[0],
                method="GET",
                attempted=True,
                started_ns=1,
                completed_ns=2,
                started_at_utc=pilot.utc_text(PILOT_START),
                completed_at_utc=pilot.utc_text(PILOT_START + timedelta(milliseconds=1)),
                classified_result="ok",
                fingerprint_or_null=None,
                error_class_or_null=None,
            ))
            observation = pilot.verify_observation_chain(journal.records_path)
            events = pilot.verify_event_chain(journal.events_path)
            checkpoint = pilot.verify_checkpoint(journal.checkpoint_path, "chain-test", observation, events)
            self.assertTrue(observation["valid"])
            self.assertTrue(events["valid"])
            self.assertTrue(checkpoint["valid"])

            journal.records_path.write_text(
                journal.records_path.read_text(encoding="utf-8").replace('"method":"GET"', '"method":"POST"'),
                encoding="utf-8",
            )
            self.assertFalse(pilot.verify_observation_chain(journal.records_path)["valid"])

    def test_manual_stop_preserves_full_denominator_without_more_requests(self) -> None:
        clock = FakeClock()
        operator = FakeOperator(clock, [(1, "STOP")])
        calls = []

        def probe(source: str) -> pilot.ProbeResult:
            calls.append(source)
            return pilot.ProbeResult("ok", fingerprint=FINGERPRINT_A if source == "runtime_capabilities" else None)

        with tempfile.TemporaryDirectory() as directory:
            runner, journal = self.make_runner(Path(directory), clock, probe, operator)
            manifest, qualification = runner.run()
            self.assertEqual(manifest["status"], "stopped")
            self.assertEqual(manifest["stop_reason"], "manual_stop")
            self.assertEqual(len(calls), 4)
            self.assertEqual(qualification["recorded_slots"], pilot.PLANNED_SLOTS)
            self.assertEqual(qualification["attempted_get_count"], 4)
            self.assertFalse(qualification["acceptance_passed"])
            self.assertTrue(pilot.verify_observation_chain(journal.records_path)["valid"])

    def test_capability_drift_stops_before_the_next_source(self) -> None:
        clock = FakeClock()
        operator = FakeOperator(clock, [(61, "ACK")])
        calls = []
        capability_count = 0

        def probe(source: str) -> pilot.ProbeResult:
            nonlocal capability_count
            calls.append(source)
            if source == "runtime_capabilities":
                capability_count += 1
                return pilot.ProbeResult("ok", fingerprint=FINGERPRINT_A if capability_count == 1 else FINGERPRINT_B)
            return pilot.ProbeResult("ok")

        with tempfile.TemporaryDirectory() as directory:
            runner, _journal = self.make_runner(Path(directory), clock, probe, operator)
            manifest, qualification = runner.run()
            self.assertEqual(manifest["stop_reason"], "security_contract_fingerprint_drift")
            self.assertEqual(calls, [
                "runtime_health", "runtime_capabilities", "keycloak_realm", "odoo_root",
                "runtime_health", "runtime_capabilities",
            ])
            self.assertFalse(qualification["checks"]["contract_drift"])
            self.assertEqual(qualification["terminal_unresolved_count"], 1)

    def test_unclassified_probe_details_are_redacted_and_stop_sampling(self) -> None:
        clock = FakeClock()
        operator = FakeOperator(clock, [(1, "ACK")])
        calls = []
        sensitive_text = "secret-bearer-value"

        def probe(source: str) -> pilot.ProbeResult:
            calls.append(source)
            return pilot.ProbeResult(
                "transport_unknown",
                error_class=sensitive_text,
                terminal_reason="https://private.invalid/token",
            )

        with tempfile.TemporaryDirectory() as directory:
            runner, journal = self.make_runner(Path(directory), clock, probe, operator)
            manifest, qualification = runner.run()
            evidence = "".join(
                path.read_text(encoding="utf-8")
                for path in journal.directory.iterdir()
                if path.is_file() and path.name != "SHA256SUMS"
            )
            self.assertEqual(calls, ["runtime_health"])
            self.assertEqual(manifest["stop_reason"], "uncategorized_observation")
            self.assertIn('"error_class_or_null":"uncategorized_observation"', evidence)
            self.assertNotIn(sensitive_text, evidence)
            self.assertNotIn("private.invalid", evidence)
            self.assertFalse(qualification["acceptance_passed"])

    def test_operator_loss_and_cost_overrun_stop_sampling(self) -> None:
        clock = FakeClock()
        scheduled = [(1, "ATTENTION START")]
        scheduled.extend((second, "ACK") for second in (600, 1200))
        operator = FakeOperator(clock, scheduled)
        calls = []

        def probe(source: str) -> pilot.ProbeResult:
            calls.append(source)
            return pilot.ProbeResult("ok", fingerprint=FINGERPRINT_A if source == "runtime_capabilities" else None)

        with tempfile.TemporaryDirectory() as directory:
            runner, _journal = self.make_runner(Path(directory), clock, probe, operator)
            manifest, qualification = runner.run()
            self.assertEqual(manifest["status"], "stopped")
            self.assertEqual(manifest["stop_reason"], "cost_budget_exceeded")
            self.assertLess(len(calls), pilot.PLANNED_SLOTS)
            self.assertGreater(qualification["principal_attention_minutes"], 30)
            self.assertFalse(qualification["checks"]["principal_attention"])

        clock = FakeClock()
        operator = FakeOperator(clock)
        calls.clear()
        with tempfile.TemporaryDirectory() as directory:
            runner, _journal = self.make_runner(Path(directory), clock, probe, operator)
            manifest, qualification = runner.run()
            self.assertEqual(manifest["stop_reason"], "operator_unavailable")
            self.assertLess(len(calls), pilot.PLANNED_SLOTS)
            self.assertFalse(qualification["acceptance_passed"])

    def test_unrecovered_unknown_stops_after_frozen_reacquisition_budget(self) -> None:
        clock = FakeClock()
        operator = FakeOperator(clock, [(second + 1, "ACK") for second in (60, 120, 180, 240, 300, 360)])
        health_count = 0
        calls = []

        def probe(source: str) -> pilot.ProbeResult:
            nonlocal health_count
            calls.append(source)
            if source == "runtime_health":
                health_count += 1
                if 2 <= health_count <= 7:
                    return pilot.ProbeResult("transport_unknown", error_class="transport_unavailable")
            if source == "runtime_capabilities":
                return pilot.ProbeResult("ok", fingerprint=FINGERPRINT_A)
            return pilot.ProbeResult("ok")

        with tempfile.TemporaryDirectory() as directory:
            runner, _journal = self.make_runner(Path(directory), clock, probe, operator)
            manifest, qualification = runner.run()
            self.assertEqual(manifest["stop_reason"], "observation_reacquisition_over_300_seconds")
            self.assertLess(len(calls), pilot.PLANNED_SLOTS)
            self.assertEqual(qualification["terminal_unresolved_count"], 1)
            self.assertEqual(qualification["observation_reacquisition_count"], 0)
            self.assertGreater(qualification["unresolved_observation_gap_seconds"], 300)
            self.assertFalse(qualification["acceptance_passed"])

    def test_full_simulated_window_reacquires_unknown_and_separates_costs(self) -> None:
        clock = FakeClock()
        scheduled = [(301, "ACK"), (30, "ATTENTION START"), (45, "ATTENTION STOP"),
                     (50, "ASSURANCE START"), (65, "ASSURANCE STOP")]
        scheduled.extend((second, "ACK") for second in range(600, pilot.PILOT_WINDOW_SECONDS, 600))
        operator = FakeOperator(clock, scheduled)
        health_count = 0
        calls = []

        def probe(source: str) -> pilot.ProbeResult:
            nonlocal health_count
            calls.append(source)
            clock.advance_seconds(0.01)
            if source == "runtime_health":
                health_count += 1
                if health_count == 6:
                    return pilot.ProbeResult("transport_unknown", error_class="transport_unavailable")
            if source == "runtime_capabilities":
                return pilot.ProbeResult("ok", fingerprint=FINGERPRINT_A)
            return pilot.ProbeResult("ok")

        with tempfile.TemporaryDirectory() as directory:
            runner, journal = self.make_runner(Path(directory), clock, probe, operator)
            manifest, qualification = runner.run()
            self.assertEqual(manifest["status"], "completed")
            self.assertEqual(manifest["stop_reason"], "approved_window_complete")
            self.assertEqual(len(calls), pilot.PLANNED_SLOTS)
            self.assertEqual(manifest["approved_window_end_monotonic_ns"] - manifest["approved_window_start_monotonic_ns"],
                             pilot.PILOT_WINDOW_SECONDS * 1_000_000_000)
            self.assertTrue(qualification["acceptance_passed"], qualification["checks"])
            self.assertEqual(qualification["recorded_slots"], pilot.PLANNED_SLOTS)
            self.assertEqual(qualification["attempted_get_count"], pilot.PLANNED_SLOTS)
            self.assertEqual(qualification["observation_reacquisition_count"], 1)
            self.assertLessEqual(qualification["max_observation_reacquisition_seconds"], 300)
            self.assertAlmostEqual(qualification["principal_attention_minutes"], 0.25, places=3)
            self.assertAlmostEqual(qualification["third_party_assurance_labor_minutes"], 0.25, places=3)
            self.assertEqual(qualification["automated_monitor_runtime_seconds"], pilot.PILOT_WINDOW_SECONDS)
            self.assertTrue(manifest["evidence_integrity"]["checkpoint"]["valid"])

            checksum_lines = (journal.directory / "SHA256SUMS").read_text(encoding="ascii").splitlines()
            for line in checksum_lines:
                expected, filename = line.split("  ", 1)
                self.assertEqual(hashlib.sha256((journal.directory / filename).read_bytes()).hexdigest(), expected)


if __name__ == "__main__":
    unittest.main()
