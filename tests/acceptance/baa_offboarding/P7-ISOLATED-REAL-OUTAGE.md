# P7 v2 isolated real Keycloak outage: frozen operational recovery gate

This is an **infrastructure fault experiment** on disposable GitHub-hosted
Linux Docker containers. It is not an autonomous maintenance task, BAA
delegation comparison, sustained availability trial, or production deployment.

## Frozen topology and intervention

Reuse only the existing `tests/acceptance/baa_offboarding/real_e2e/compose.yaml`
disposable test stack, without provisioning staff or invoking business effects.
From the host, after the previous P7 static-shadow/maintenance qualification:

1. Qualify one complete **4-source GET** baseline, including a verified
   Runtime `/v1/capabilities` fingerprint with all required covered flags.
2. Apply exactly one Docker **pause** to the `keycloak` service of this
   disposable Compose project; do not change realm data, clients, tokens,
   Odoo state or World Runtime config.
3. Observe one complete **4-source GET** round while Keycloak is paused.
   Required: Keycloak read is **not OK**, classified as
   `transport_unknown`; all three other sources remain OK.
4. Issue Docker **unpause**, using an unconditional cleanup attempt even if
   sampling fails; then record up to **8 complete rounds**, 2 seconds apart
   until **two consecutive full clean rounds** have been acquired after the
   detected real outage.
5. Run the unchanged `assess_maintenance` v1 logic; the only accepted final
   result is `verified_recovered_evidence`. Any initial baseline failure,
   missing measured failure, contract/auth anomaly, failed unpause,
   incomplete evidence, exhausted bound, or final unresolved status **fails**.

The service pause is an **actual isolated-process outage** instead of the v1
synthetic reader perturbation. It is controlled by the experiment host,
not remotely induced on a production instance or approved as a maintenance
remediation interface. The observer itself issues **GET only**; only the
disposable test controller calls Docker pause/unpause.

## Timing and evidence

- Record per-request monotonic start/end (same host), phase/round/result
  and sanitized error class; neither tokens nor body text are archived.
- Record the monotonic `unpause`-to-two-full-clean-round completion
  **instrument wall duration** (not external product repair timestamp).
- Retain the actually observed Keycloak outage result, control-source
  outcomes, complete round count, false positives, and independent
  filesystem artifact + source SHA/provenance.
- This tests a *single* 1-of-1 intervention. No P95/P99, error rate, MTTR
  distribution, causal BAA efficacy, independent clock synchronization,
  attention-risk accounting, or agent usefulness is inferred.
- A GitHub runner startup or Odoo-init failure **before baseline** is a
  setup qualification failure and remains visible as such.

## Security and teardown

Workflow must run on `ubuntu-latest`, not a self-hosted runner, and must
explicitly pass `P7_ALLOW_EPHEMERAL_KEYCLOAK_PAUSE=approved-ci-only` to the
test script. The compose path and paused service are fixed in code. The
script does not accept arbitrary Docker paths/service names and writes no
production secrets. If pause is attempted, unpause must be attempted in
`finally`; workflow already tears down all disposable volumes with an
unconditional `always()` cleanup.

This experiment can establish observation of a **real, reversible, isolated
service outage** and conservative sample-level recovery evidence; it
cannot establish continuous correctness or general unattended resilience.
