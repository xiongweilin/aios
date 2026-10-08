# P7 read-only shadow precursor (isolated)

This target **does not certify a P7 long-duration unattended deployment**. It is a bounded, nonwriting observability drill using disposable AIOS World Runtime, Keycloak and Odoo products. It is separate from experiments that actually dispatch offboarding effects.

## Execution and authority

- CI pull-request runs use a frozen **40-second observation window**, every 5 seconds, after explicit fixture-readiness qualification. The window measures `GET` only.
- A manual workflow dispatch can select 1, 5 or 15 minutes, but is not scheduled automatically. This avoids creating recurring cost or contacting an unapproved internal endpoint.
- All services run in a disposable GitHub-hosted Docker environment with generated credentials; no real accounts/tenants or external tokens.
- The code has no provider execute method and issues only HTTP `GET` to `World Runtime /healthz`, `World Runtime /v1/capabilities`, `Keycloak /realms/master` and Odoo root.
- It checks the three covered offboarding capability rules for `authorization_required`, `resource_required` and `version_required`; a missing/malformed/weakened contract becomes `schema_unknown`, not a stable successful fingerprint.
- Any observed non-200 response, network failure or rule drift causes the run to fail *after writing bounded evidence*. Sampling gaps remain unknown.

## Evidence and limits

Each run archives `observations.json` with monotonic request envelopes, source label, one of `ok/http_error/transport_unknown/schema_unknown`, fingerprint count, failure counts and the sampled sequence. No raw HTTP response body, bearer token, client secret, URL with credentials, user ID or exception message is recorded. `provenance.json` pins the run SHA.

This only samples surface health and a narrow *declared* authorization contract. It does not prove product access semantics, complete mediation, effective error-free continuous operation, restart survival, delegated work delivery, principal attention cost, or a production reliability SLO. It does not measure BAA admission latency, effect recovery, or assurance labor.

A P7 acceptance trial still requires a preregistered meaningful workload, externally bounded losses, failure and maintenance rotation schedule, version drift controls, state persistence, operator intervention budget, independent recovery/reconciliation validation, and explicit authorization. **No production write rights are inferred from passing this drill.**

## Running

Use the GitHub Actions workflow `P7 Isolated Read-Only Shadow` on the AIOS repository. The isolated PR test is automatic; longer **manual** runs are available only when explicitly dispatched. All disposable Docker volumes are removed after the run.

Offline qualification:

```bash
python -m unittest discover -s tests/acceptance/baa_offboarding/real_e2e -p "test_p7_shadow_readonly.py" -v
```
