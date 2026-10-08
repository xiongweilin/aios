"""P7 read-only maintenance triage over observed multi-service evidence.

This is a deterministic operational *instrument* and not an LLM agent, a
BAA admission experiment, or proof of production task delegation.

Decision is deliberately sticky:
  - any malformed/weakening protected capability evidence -> ESCALATE;
  - transient read failure -> UNRESOLVED until two full clean rounds;
  - a clean 4-source baseline and all subsequent clean -> VERIFIED_STABLE.
Recovering read-only evidence does not authorize any write/retry/repair.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from p7_shadow_readonly import SOURCES, Observation


class TriageStatus(StrEnum):
    VERIFIED_STABLE = "verified_stable"
    VERIFIED_RECOVERED = "verified_recovered_evidence"
    ESCALATE = "escalate_contract_or_authority"
    UNRESOLVED = "unresolved_observation"


@dataclass(frozen=True)
class TriageAssessment:
    status: TriageStatus
    reason: str
    complete_rounds: int
    observed_probes: int
    observation_unknown_encountered: bool
    terminal_unresolved: bool
    contract_escalation: bool
    evidence_reacquisition_rounds: int
    baseline_fingerprint: str | None

    def public(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "reason": self.reason,
            "complete_rounds": self.complete_rounds,
            "observed_probes": self.observed_probes,
            "observation_unknown_encountered": self.observation_unknown_encountered,
            "terminal_unresolved": self.terminal_unresolved,
            "contract_escalation": self.contract_escalation,
            "evidence_reacquisition_rounds": self.evidence_reacquisition_rounds,
            "baseline_fingerprint": self.baseline_fingerprint,
            "principal_attention_measured": False,
            "real_world_risk_measured": False,
            "BAA_delegation_leverage_measured": False,
        }


def assess_maintenance(
    observations: tuple[Observation, ...],
    *,
    required_clean_recovery_rounds: int = 2,
) -> TriageAssessment:
    """Only complete, canonically ordered rounds are accepted as evidence.

    Descriptive probes can certify this *instrument's* finite decision
    contract, never the underlying service's continuous correctness.
    """
    if required_clean_recovery_rounds != 2:
        raise ValueError("v1 recovery rule is frozen to two full clean rounds")
    if not observations or len(observations) % len(SOURCES):
        raise ValueError("P7 triage requires complete observation rounds")
    n = len(observations) // len(SOURCES)
    for i, row in enumerate(observations):
        if row.round_number != i // len(SOURCES) or row.source != SOURCES[i % len(SOURCES)]:
            raise ValueError("P7 evidence ordering/completeness violation")

    fingerprints = [
        row.capability_fingerprint
        for row in observations if row.source == "runtime_capabilities"
        and row.result == "ok"
    ]
    # An 'ok' without a contract fingerprint can never serve as evidence.
    malformed_ok = any(
        row.source == "runtime_capabilities"
        and row.result == "ok"
        and not row.capability_fingerprint
        for row in observations
    )
    drift = len(set(fingerprints)) > 1
    contract_issue = (
        malformed_ok or drift
        or any(
            row.source == "runtime_capabilities"
            and row.result == "schema_unknown"
            for row in observations
        )
        or any(row.error_class in {"http_401", "http_403"} for row in observations)
    )
    baseline = observations[:len(SOURCES)]
    baseline_valid = all(row.result == "ok" for row in baseline) and bool(fingerprints)
    baseline_fp = (
        next(
            (row.capability_fingerprint
             for row in baseline if row.source == "runtime_capabilities"),
            None,
        )
        if baseline_valid else None
    )
    uncertain = any(row.result != "ok" for row in observations)
    status: TriageStatus
    reason: str
    clean_after_gap = 0
    ever_gap = False
    recovery_rounds = 0
    if contract_issue:
        status, reason = TriageStatus.ESCALATE, "capability_contract_or_auth_discrepancy"
    elif not baseline_valid:
        status, reason = TriageStatus.UNRESOLVED, "no_qualified_initial_baseline"
    else:
        for round_idx in range(1, n):
            rows = observations[round_idx * len(SOURCES):(round_idx + 1) * len(SOURCES)]
            clean = all(row.result == "ok" for row in rows)
            if not clean:
                ever_gap = True
                clean_after_gap = 0
                continue
            if ever_gap:
                clean_after_gap += 1
                recovery_rounds += 1
        if not ever_gap:
            status, reason = TriageStatus.VERIFIED_STABLE, "all_sampled_rounds_ok"
        elif clean_after_gap >= 2:
            status, reason = TriageStatus.VERIFIED_RECOVERED, "two_full_reacquired_rounds"
        else:
            status, reason = TriageStatus.UNRESOLVED, "insufficient_post_gap_evidence"

    return TriageAssessment(
        status=status,
        reason=reason,
        complete_rounds=n,
        observed_probes=len(observations),
        observation_unknown_encountered=uncertain,
        terminal_unresolved=status == TriageStatus.UNRESOLVED,
        contract_escalation=status == TriageStatus.ESCALATE,
        evidence_reacquisition_rounds=recovery_rounds,
        baseline_fingerprint=baseline_fp,
    )
