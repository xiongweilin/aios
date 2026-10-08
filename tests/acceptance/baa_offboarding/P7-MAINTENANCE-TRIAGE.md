# P7 v1 read-only maintenance triage — preregistered instrument contract

This is a **small operational diagnostic exercise**, not an Agent study and
not evidence that BAA improves delegation value. There are no AI agents, real
employees, production tenants, provider mutations, or production permissions.

## Frozen workload and observation boundary

All three cases operate on the **same disposable live product topology**:
AIOS World Runtime, Keycloak and Odoo. Each case has four complete sequential
rounds with the same four GET-only sources:

1. Runtime `/healthz`;
2. Runtime `/v1/capabilities`, requiring the three covered capability
   authorization/resource/version flags (not only advertised names);
3. Keycloak `/realms/master`;
4. Odoo HTTP root.

There are **16 observed slots per case**. The prospective case sequence is:

| Case | Local instrument perturbation | Expected disposition |
|---|---|---|
| `normal` | none | `verified_stable` |
| `observer_transport_gap` | skip Keycloak GET in round 1, record `transport_unknown` | `verified_recovered_evidence` after rounds 2, 3 are fully clean |
| `observer_contract_anomaly` | substitute `schema_unknown` for Runtime capability observation in round 1 | `escalate_contract_or_authority`, even if rounds 2, 3 are clean |

**Important:** The last two are explicitly **instrument-only perturbations**.
They do not make the actual products fail, weaken the actual capability
contract, or rotate a real credential. The remaining slots hit live GET
endpoints. The denominators are 16 real requests for normal and 15 real
requests + 1 simulated missing observation for each perturbation case.

## Frozen decision semantics and disqualifiers

- Evidence must contain complete, ordered rounds, exactly one record per
  named source per round; missing/duplicated/reordered entries are rejected.
- Without a clean full first round, no stable or recovered decision is
  permitted.
- A non-OK read creates a **known encountered gap**. The terminal episode is
  `unresolved_observation` until **two subsequent full clean rounds** have
  been recorded after the latest gap.
- A missing/malformed/weakened capability contract, fingerprint drift or
  authenticated 401/403 error yields sticky
  `escalate_contract_or_authority`, even if subsequent samples look healthy.
- Unexpected service failure, misclassified recovery, result mismatch,
  incomplete evidence or missing artifact **fails qualification**, retaining
  the failed result. The test does not adjust horizons or success thresholds
  after seeing an output.
- No mutation/restart/retry endpoint, privileged task executor, or
  autonomous agent operates as part of this exercise.

## Accounting and accepted claim

The evidence contains the 48 expected observation slots, actual GET count,
simulated instrument fault count, baseline fingerprint, per-source statuses,
observed unknown, terminal unresolved, escalation flag and the number of
full evidence-reacquisition rounds.

This instrument **does not measure** human principal attention,
post-hoc-assurance labor, model cost, a useful autonomous delivery frontier,
BAA-vs-audit-vs-self-check causal effect, workload throughput, real product
fault recovery, or cross-system joint loss. Observed service health is not
the same as verified system correctness.

Passing only qualifies the **read-only operational diagnostic contract** for
a disposable real-product topology. The next research step would require a
preapproved, non-destructive internal maintenance workload, matched
episode-level randomization, frozen attention/risk/delivery/assurance budgets
and product-independent outcome verification.
