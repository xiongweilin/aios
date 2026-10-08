"""One bounded real service outage on the disposable P7 Docker test stack.

Only a fixture controller changes a local container's process scheduling;
the observer continues to make read-only GETs. No production endpoints,
business effects, agent decisions or credentials appear in the evidence.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from p7_maintenance_triage import TriageStatus, assess_maintenance
from p7_shadow_readonly import ShadowMonitor, read_only_probe

COMPOSE_PATH = Path(__file__).resolve().with_name("compose.yaml")
MAX_REACQUISITION_ROUNDS = 8
WAIT_BETWEEN_RECOVERY_ROUNDS_S = 2.0


def _control_isolated_service(verb: str) -> None:
    if verb not in {"pause", "unpause"}:
        raise ValueError("unsupported bounded fault operation")
    if (
        os.environ.get("P7_ALLOW_EPHEMERAL_KEYCLOAK_PAUSE") != "approved-ci-only"
        or os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("RUNNER_OS") != "Linux"
    ):
        raise RuntimeError("isolated fault controller not authorized")
    # Fixed CI-owned compose project and fixed target service. Output is not
    # logged: provider and CLI error text may disclose infrastructure data.
    subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_PATH), verb, "keycloak"],
        check=True,
        capture_output=True,
        timeout=30,
    )


def execute_isolated_recovery(
    poll: Callable[[str], tuple[str, str | None, str | None]],
    *,
    pause: Callable[[], None],
    unpause: Callable[[], None],
    sleep: Callable[[float], None] = time.sleep,
    clock_ns: Callable[[], int] = time.monotonic_ns,
) -> dict[str, Any]:
    """Fail qualification if the induced outage is not actually observed."""
    monitor = ShadowMonitor(poll, max_rounds=2 + MAX_REACQUISITION_ROUNDS)
    phase = "baseline"
    failure_class: str | None = None
    failure_reason: str | None = None
    pause_attempted = False
    unpause_attempted = False
    unpause_ok = False
    outage_observed = False
    controls_unchanged = False
    after_resume_ns: int | None = None
    verified_at_ns: int | None = None
    recovery_samples = 0

    try:
        baseline = monitor.sample_round()
        if (
            not all(row.result == "ok" for row in baseline)
            or not baseline[1].capability_fingerprint
        ):
            failure_reason = "pre_fault_baseline_not_qualified"
        else:
            phase = "pause_disposable_keycloak"
            pause_attempted = True
            try:
                pause()
                phase = "paused_real_service_observation"
                during = monitor.sample_round()
                outage_observed = (
                    during[2].source == "keycloak_realm"
                    and during[2].result == "transport_unknown"
                )
                controls_unchanged = (
                    all(during[i].result == "ok" for i in (0, 1, 3))
                    and during[1].capability_fingerprint
                    == baseline[1].capability_fingerprint
                )
                if not outage_observed or not controls_unchanged:
                    failure_reason = "outage_or_control_discrimination_failed"
            finally:
                # Always attempt recovery even if pause() timed out/raised.
                phase = "restore_disposable_keycloak"
                unpause_attempted = True
                try:
                    unpause()
                    unpause_ok = True
                    after_resume_ns = clock_ns()
                except Exception as exc:
                    failure_class = type(exc).__name__
                    failure_reason = "failed_to_unpause_isolated_service"

            if (
                failure_reason is None
                and outage_observed and controls_unchanged and unpause_ok
            ):
                phase = "independently_reacquire_readonly_evidence"
                for idx in range(MAX_REACQUISITION_ROUNDS):
                    if idx:
                        sleep(WAIT_BETWEEN_RECOVERY_ROUNDS_S)
                    monitor.sample_round()
                    recovery_samples += 1
                    try:
                        decision = assess_maintenance(tuple(monitor.rows))
                    except ValueError:
                        failure_reason = "malformed_reacquisition_evidence"
                        break
                    if decision.status == TriageStatus.VERIFIED_RECOVERED:
                        verified_at_ns = clock_ns()
                        break
                    if decision.status == TriageStatus.ESCALATE:
                        failure_reason = "new_authorization_or_contract_anomaly"
                        break
                if verified_at_ns is None and failure_reason is None:
                    failure_reason = "bounded_reacquisition_exhausted"
    except Exception as exc:
        failure_class = type(exc).__name__
        if failure_reason is None:
            failure_reason = "unexpected_fixture_or_observer_error"

    assessment: dict[str, object] | None = None
    if monitor.rows:
        try:
            assessment = assess_maintenance(tuple(monitor.rows)).public()
        except ValueError:
            failure_reason = "malformed_observation_sequence"

    qualified = bool(
        outage_observed
        and controls_unchanged
        and pause_attempted
        and unpause_attempted
        and unpause_ok
        and verified_at_ns is not None
        and failure_reason is None
        and assessment is not None
        and assessment["status"] == TriageStatus.VERIFIED_RECOVERED.value
        and assessment["observation_unknown_encountered"] is True
        and assessment["evidence_reacquisition_rounds"] >= 2
    )
    return {
        "schema": "aios-p7-real-isolated-keycloak-outage-v1",
        "grade": "one reversible actual isolated-process pause; GET-only observation",
        "preregistered_expected_result": TriageStatus.VERIFIED_RECOVERED.value,
        "qualified": qualified,
        "stage_at_completion": "qualified" if qualified else phase,
        "failure_reason": failure_reason,
        "failure_class": failure_class,
        "pause_attempted": pause_attempted,
        "unpause_attempted": unpause_attempted,
        "unpause_succeeded": unpause_ok,
        "actual_keycloak_outage_observed": outage_observed,
        "other_three_sources_remained_ok_in_fault_round": controls_unchanged,
        "recovery_observation_rounds": recovery_samples,
        "max_recovery_rounds": MAX_REACQUISITION_ROUNDS,
        "post_unpause_to_two_clean_rounds_seconds": (
            round((verified_at_ns - after_resume_ns) / 1e9, 6)
            if verified_at_ns is not None and after_resume_ns is not None
            else None
        ),
        "elapsed_measurement": "same-host monotonic; observation completion only",
        "principal_attention_measured": False,
        "agent_or_BAA_action_involved": False,
        "real_business_effect_count": 0,
        "assessment": assessment,
        "snapshot": monitor.report(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-base", required=True)
    parser.add_argument("--keycloak-base", required=True)
    parser.add_argument("--odoo-base", required=True)
    parser.add_argument("--evidence-path", required=True)
    args = parser.parse_args()
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("RUNNER_OS") != "Linux"
        or os.environ.get("P7_ALLOW_EPHEMERAL_KEYCLOAK_PAUSE") != "approved-ci-only"
    ):
        raise SystemExit("real isolated fault exercise requires explicit CI authorization")

    token = os.environ["BAA_REAL_RUNTIME_TOKEN"]

    def poll(source: str) -> tuple[str, str | None, str | None]:
        return read_only_probe(
            source=source,
            runtime_base=args.runtime_base,
            keycloak_base=args.keycloak_base,
            odoo_base=args.odoo_base,
            runtime_token=token,
            delegation_id="delegation:baa-real-products-administrative",
            timeout_s=2.0,
        )

    evidence = execute_isolated_recovery(
        poll,
        pause=lambda: _control_isolated_service("pause"),
        unpause=lambda: _control_isolated_service("unpause"),
    )
    path = Path(args.evidence_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    if not evidence["qualified"]:
        raise SystemExit("real isolated Keycloak outage recovery NOT qualified")


if __name__ == "__main__":
    main()
