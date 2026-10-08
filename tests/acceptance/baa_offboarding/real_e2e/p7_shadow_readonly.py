"""P7 precursor: bounded, read-only, isolated AIOS shadow observations.

No admission, effect dispatch, retry, revocation, or production operation is
performed. Sample health and three coverage-critical authorization contract
rules. Observations of health do NOT assert product correctness or unattended
delegation safety. No raw provider payloads or credentials enter the report.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

EXPECTED_EFFECTS = frozenset({
    "administrative.iam.identity.disable.v1",
    "administrative.iam.sessions.revoke.v1",
    "administrative.hris.employee.deactivate.v1",
})
SOURCES = ("runtime_health", "runtime_capabilities", "keycloak_realm", "odoo_root")
RESULTS = frozenset({"ok", "http_error", "transport_unknown", "schema_unknown"})
MAX_ROUNDS = 300


@dataclass(frozen=True)
class Observation:
    source: str
    round_number: int
    started_ns: int
    completed_ns: int
    result: str
    capability_fingerprint: str | None = None
    error_class: str | None = None

    def __post_init__(self) -> None:
        if self.source not in SOURCES or self.result not in RESULTS:
            raise ValueError("unknown shadow source/result")
        if self.completed_ns < self.started_ns:
            raise ValueError("nonmonotonic observation")
        if self.capability_fingerprint is not None and self.source != "runtime_capabilities":
            raise ValueError("unexpected contract fingerprint")

    def public(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "round": self.round_number,
            "started_monotonic_ns": self.started_ns,
            "completed_monotonic_ns": self.completed_ns,
            "duration_ns": self.completed_ns - self.started_ns,
            "result": self.result,
            "capability_fingerprint": self.capability_fingerprint,
            "error_class": self.error_class,
        }


def qualified_contract_fingerprint(catalog: object) -> str | None:
    """Only the three required security attributes of covered actions.

    Missing contracts and incorrectly typed flags are UNKNOWN; never record
    a misleadingly stable fingerprint of a malformed payload.
    """
    if not isinstance(catalog, dict) or not isinstance(catalog.get("effect_rules"), list):
        return None
    rules: dict[str, tuple[bool, bool, bool]] = {}
    for item in catalog["effect_rules"]:
        if not isinstance(item, dict):
            continue
        capability = item.get("capability")
        if capability not in EXPECTED_EFFECTS:
            continue
        fields = (
            item.get("authorization_required"),
            item.get("resource_required"),
            item.get("version_required"),
        )
        if not all(type(flag) is bool for flag in fields):
            return None
        if capability in rules:
            return None
        rules[capability] = fields
    if set(rules) != EXPECTED_EFFECTS or any(not all(fields) for fields in rules.values()):
        return None
    minimized = [(key, list(rules[key])) for key in sorted(rules)]
    return hashlib.sha256(
        json.dumps(minimized, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def read_only_probe(
    *,
    source: str,
    runtime_base: str,
    keycloak_base: str,
    odoo_base: str,
    runtime_token: str,
    delegation_id: str,
    timeout_s: float = 3.0,
) -> tuple[str, str | None, str | None]:
    """One GET only. Do not infer access decisions from health probes."""
    if source == "runtime_health":
        url = runtime_base.rstrip("/") + "/healthz"
    elif source == "runtime_capabilities":
        url = runtime_base.rstrip("/") + "/v1/capabilities"
    elif source == "keycloak_realm":
        url = keycloak_base.rstrip("/") + "/realms/master"
    elif source == "odoo_root":
        url = odoo_base.rstrip("/") + "/"
    else:
        raise ValueError("unknown read-only source")

    headers = {}
    if source == "runtime_capabilities":
        headers["Authorization"] = "Bearer " + runtime_token
        headers["X-World-Runtime-Delegation"] = delegation_id
    request = urllib.request.Request(url, method="GET", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            if response.status != 200:
                return "http_error", None, "non_200"
            if source != "runtime_capabilities":
                return "ok", None, None
            payload = json.load(response)
            fingerprint = qualified_contract_fingerprint(payload)
            if fingerprint is None:
                return "schema_unknown", None, "security_contract_incomplete"
            return "ok", fingerprint, None
    except urllib.error.HTTPError as exc:
        return "http_error", None, f"http_{exc.code}"
    except (urllib.error.URLError, OSError, TimeoutError):
        return "transport_unknown", None, "transport_unavailable"
    except (ValueError, TypeError):
        return "schema_unknown", None, "invalid_contract_response"


class ShadowMonitor:
    """Bounded sampling with no effect API writes and no implicit retries."""

    def __init__(
        self,
        poll: Callable[[str], tuple[str, str | None, str | None]],
        *,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
        max_rounds: int = MAX_ROUNDS,
    ) -> None:
        if not (1 <= max_rounds <= MAX_ROUNDS):
            raise ValueError("invalid finite shadow capacity")
        self.poll = poll
        self.clock_ns = monotonic_ns
        self.max_rounds = max_rounds
        self.rows: list[Observation] = []

    def sample_round(self) -> tuple[Observation, ...]:
        current_round = len(self.rows) // len(SOURCES)
        if current_round >= self.max_rounds:
            raise RuntimeError("shadow capacity reached: stop without suppressing coverage loss")
        measured = []
        for source in SOURCES:
            start = self.clock_ns()
            try:
                result, fingerprint, error_class = self.poll(source)
                if result not in RESULTS:
                    raise ValueError("invalid probe result")
            except Exception as exc:
                result, fingerprint, error_class = (
                    "transport_unknown", None, type(exc).__name__
                )
            end = self.clock_ns()
            entry = Observation(
                source=source,
                round_number=current_round,
                started_ns=start,
                completed_ns=end,
                result=result,
                capability_fingerprint=fingerprint,
                error_class=error_class,
            )
            measured.append(entry)
        self.rows.extend(measured)
        return tuple(measured)

    def report(self) -> dict[str, Any]:
        rounds = len(self.rows) // len(SOURCES)
        failures = {s: 0 for s in SOURCES}
        fingerprints: set[str] = set()
        for row in self.rows:
            if row.result != "ok":
                failures[row.source] += 1
            if row.capability_fingerprint is not None:
                fingerprints.add(row.capability_fingerprint)
        return {
            "schema": "aios-p7-isolated-readonly-shadow-v1",
            "scope": "disposable offline-like test stack; not production, no writes",
            "read_methods": ["GET"],
            "eligible_for_long_horizon_claim": False,
            "qualified_credential_independence": False,
            "qualified_production_slo": False,
            "rounds": rounds,
            "samples": len(self.rows),
            "failure_counts": failures,
            "contract_fingerprint_count": len(fingerprints),
            "contract_drift_observed": len(fingerprints) > 1,
            "contract_completeness_all_rounds": (
                rounds > 0 and failures["runtime_capabilities"] == 0
            ),
            "records": [row.public() for row in self.rows],
            "caveats": [
                "health success is not authorization correctness",
                "sampling gaps may contain unobserved failures",
                "issuer/writer failure domains not independent",
                "no durable delegation, no effects, no attention or risk evidence",
            ],
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-base", required=True)
    parser.add_argument("--keycloak-base", required=True)
    parser.add_argument("--odoo-base", required=True)
    parser.add_argument("--evidence-path", required=True)
    parser.add_argument("--duration-seconds", type=int, default=60)
    parser.add_argument("--interval-seconds", type=int, default=5)
    args = parser.parse_args()
    if not (5 <= args.duration_seconds <= 900):
        parser.error("duration-seconds must be 5..900")
    if not (1 <= args.interval_seconds <= 60):
        parser.error("interval-seconds must be 1..60")

    token = os.environ["BAA_REAL_RUNTIME_TOKEN"]

    def probe(source: str) -> tuple[str, str | None, str | None]:
        return read_only_probe(
            source=source,
            runtime_base=args.runtime_base,
            keycloak_base=args.keycloak_base,
            odoo_base=args.odoo_base,
            runtime_token=token,
            delegation_id="delegation:baa-real-products-administrative",
        )

    monitor = ShadowMonitor(probe)
    start = time.monotonic()
    try:
        while True:
            monitor.sample_round()
            if time.monotonic() - start >= args.duration_seconds:
                break
            sleep_s = min(args.interval_seconds, args.duration_seconds - (time.monotonic() - start))
            if sleep_s > 0:
                time.sleep(sleep_s)
    finally:
        path = Path(args.evidence_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(monitor.report(), sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
    report = monitor.report()
    if any(report["failure_counts"].values()) or report["contract_drift_observed"]:
        raise SystemExit("isolated read-only shadow detected unavailable/changed services")


if __name__ == "__main__":
    main()
