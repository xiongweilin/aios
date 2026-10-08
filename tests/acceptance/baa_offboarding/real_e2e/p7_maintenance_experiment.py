"""P7 prospective, read-only maintenance diagnostic cases over real isolated GETs.

Three frozen cases share the SAME actual disposable Keycloak/Odoo/Runtime
endpoints. Simulated faults change ONLY the *local observation channel* at
round 1, never the product state or its capability contract. They qualify
triage/recovery logic; they cannot prove real fault recovery or LLM usefulness.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from p7_maintenance_triage import TriageStatus, assess_maintenance
from p7_shadow_readonly import SOURCES, ShadowMonitor, read_only_probe

SCENARIOS = (
    "normal",
    "observer_transport_gap",
    "observer_contract_anomaly",
)
EXPECTED = {
    "normal": TriageStatus.VERIFIED_STABLE,
    "observer_transport_gap": TriageStatus.VERIFIED_RECOVERED,
    "observer_contract_anomaly": TriageStatus.ESCALATE,
}
FROZEN_ROUNDS = 4


def run_scenario(
    name: str,
    *,
    runtime_base: str,
    keycloak_base: str,
    odoo_base: str,
    runtime_token: str,
) -> dict[str, Any]:
    if name not in SCENARIOS:
        raise ValueError("scenario not registered")
    current_round = 0
    injected = 0
    real_get_attempts = 0

    def poll(source: str) -> tuple[str, str | None, str | None]:
        nonlocal injected, real_get_attempts
        if current_round == 1:
            if name == "observer_transport_gap" and source == "keycloak_realm":
                injected += 1
                return "transport_unknown", None, "injected_observer_transport_gap"
            if name == "observer_contract_anomaly" and source == "runtime_capabilities":
                injected += 1
                return "schema_unknown", None, "injected_observer_contract_anomaly"
        real_get_attempts += 1
        return read_only_probe(
            source=source,
            runtime_base=runtime_base,
            keycloak_base=keycloak_base,
            odoo_base=odoo_base,
            runtime_token=runtime_token,
            delegation_id="delegation:baa-real-products-administrative",
        )

    monitor = ShadowMonitor(poll, max_rounds=FROZEN_ROUNDS)
    for number in range(FROZEN_ROUNDS):
        current_round = number
        monitor.sample_round()

    result = assess_maintenance(tuple(monitor.rows))
    expected = EXPECTED[name]
    qualified = (
        result.status == expected
        and result.complete_rounds == FROZEN_ROUNDS
        and real_get_attempts + injected == len(SOURCES) * FROZEN_ROUNDS
        and injected == (0 if name == "normal" else 1)
        and (
            result.observation_unknown_encountered
            == (name != "normal")
        )
    )
    return {
        "case": name,
        "expected_status": expected.value,
        "qualified": qualified,
        "assessment": result.public(),
        "simulated_instrument_faults": injected,
        "real_http_get_attempts": real_get_attempts,
        "records": [row.public() for row in monitor.rows],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-base", required=True)
    parser.add_argument("--keycloak-base", required=True)
    parser.add_argument("--odoo-base", required=True)
    parser.add_argument("--evidence-path", required=True)
    args = parser.parse_args()

    token = os.environ["BAA_REAL_RUNTIME_TOKEN"]
    results: list[dict[str, Any]] = []
    payload = {
        "schema": "aios-p7-maintenance-readonly-triage-v1",
        "workload": "three fixed cases, same live test products, four rounds per case",
        "environment": "isolated disposable real services only",
        "probe_method": "GET",
        "effect_dispatch_count": 0,
        "instrument_fault_scope": "local observation responses, not product state",
        "decision_endpoints_frozen_before_run": {
            k: v.value for k, v in EXPECTED.items()
        },
        "required_clean_reacquisition_rounds": 2,
        "attention_measured": False,
        "assurance_labor_measured": False,
        "model_or_agent_involved": False,
        "causal_BAA_effect_measured": False,
        "results": results,
    }
    try:
        for scenario in SCENARIOS:
            results.append(
                run_scenario(
                    scenario,
                    runtime_base=args.runtime_base,
                    keycloak_base=args.keycloak_base,
                    odoo_base=args.odoo_base,
                    runtime_token=token,
                )
            )
    finally:
        path = Path(args.evidence_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    if len(results) != len(SCENARIOS) or not all(r["qualified"] for r in results):
        raise SystemExit("P7 maintenance triage qualification failed")


if __name__ == "__main__":
    main()
