# P7 Internal Read-Only Maintenance Pilot v1 — Frozen Acceptance Contract

> English | [简体中文](P7-INTERNAL-READONLY-PILOT.zh-CN.md)

**State: design frozen; execution NOT authorized.** This contract is a prospective **P6+P7 internal staging pilot** boundary, not an instruction to probe a real environment now. It is deliberately separate from the historical 40-second disposable P7 shadow, the three-case triage fixture, and the isolated Keycloak pause experiment. Their passing CI does not grant staging privileges.

Machine-readable canonical parameters: [`p7_internal_readonly_pilot_v1.json`](p7_internal_readonly_pilot_v1.json). Static validator: [`scripts/check_p7_internal_readonly_pilot.py`](../../../scripts/check_p7_internal_readonly_pilot.py).

## 1. Research objective and claim boundary

Can a fixed four-source, **GET-only**, supervised internal-staging maintenance observer run predictably over an extended **four-hour** window, identify observable transport/contract degradation, retain unknowns, and stop or hand control to an on-duty human without effectful action or hidden labor?

It does **not** measure autonomous Agent delivery, BAA's causal delegation advantage, continuous authorization correctness, production availability, actual access loss `Y`, or complete runtime mediation. There is no AI model invocation. Report whether the observer met *this pilot's* prospective measurement and operational thresholds; do not label this as a production SLO.

## 2. Activation and access controls — hard prerequisite

The public repository contains **no staging URLs, tokens, names, on-call contacts, or secrets**. An operator must establish and independently approve the following **outside the repository before any run**:

1. Named accountable owner and on-duty operator available for the *entire* supervised interval, plus a private contact/acknowledgement route.
2. Written, time-bounded, scoped **internal staging** read-only authorization; a four-source resource inventory with exact scheme/host/port/realm/tenant and safe credential scope, reviewed outside the repo.
3. A verifiable read-only identity (Runtime capability catalog, Keycloak realm, Odoo HTTP root, Runtime health); no escalation path to write APIs, administration or production data.
4. Fixed UTC start/end time, controlled rollout and independent means to stop sampling/revoke pilot credentials even if the observer crashes.
5. Artifact ACL/retention approval and a plan to redact sensitive payloads.

**Default is DENY.** No cron, workflow-dispatch against internal staging, runner network access, or product-effect capability is authorized by merging this document. A GitHub runner being able to reach a host does not constitute permission to interrogate it.

## 3. Frozen duration and scope

- Window: **4 hours supervised**; stop at the fixed end. This is an initial pilot, not P7 long-term acceptance.
- Cadence: one complete, ordered four-source round per **60 seconds**; 240 planned rounds / **960 planned GET slots**. Every missed or failed slot must appear in the assigned denominator with a classified result; do not silently discard gaps.
- One attempt per slot; network request timeout **3 seconds**. No blind retries, even for GET, in this measurement contract.
- Allowed endpoints (operator-approved exact hosts only): Runtime `GET /healthz`; Runtime `GET /v1/capabilities`; Keycloak `GET /realms/{approved_realm}`; Odoo `GET /`.
- Catalog qualification requires the three existing offboarding effect capabilities to declare `authorization_required`, `resource_required`, and `version_required` true. The observer **only reads** these rules; it does not request those effects.
- **Prohibited:** POST/PUT/PATCH/DELETE, provider dispatch, account/session changes, Docker pause/restart, credential rotation, auto-repair, automatic write fallback, model generation and accessing live employee records.
- No failure injection in the first internal pilot. A future injection experiment requires a separate frozen, scoped and approved contract.

The existing `p7_shadow_readonly.py` is capped at **900 seconds / 300 rounds**. It cannot directly execute the four-hour design unchanged. A separate opt-in long-window driver, safe bounded storage, independent approval checks and operator stop mechanism must be qualified before activation. **Do not relax or silently reuse the 900-second safety cap.**

## 4. Prospective operational acceptance thresholds

These are **pilot acceptance limits chosen before the first internal-staging run**, not statistical estimates or production-grade promises. A single four-hour observation cannot establish tail reliability.

| Measure | Pilot acceptance |
|---|---|
| Complete, ordered rounds | Exactly 240 planned rounds represented; 960/960 slots accounted, including classified failures |
| Unclassified slots, missing evidence rounds | 0; any gap must be explicit and disqualifies complete coverage |
| Unscheduled sample gap | No gap over 120 s |
| Empirical GET request P95 | ≤2,000 ms; `n` reported |
| Empirical full-round P95 | ≤10,000 ms; `n` reported |
| Non-OK probe fraction | ≤1% of 960 assigned slots; including UNKNOWN |
| Contract/auth drift or weakening | 0 tolerated |
| Unauthorized/effectful API calls | 0 tolerated |
| Terminal unresolved diagnostic | 0; unknown encountered retained separately |
| Actual principal attention | ≤30 minutes total, observed intervals required |
| Actual third-party assurance labor | ≤60 minutes total, observed intervals required; **not merged** with principal time |
| Operator acknowledgement after an escalation | Within 900 s *during covered on-duty hours*, otherwise stop |
| Evidence reacquisition following a transient observation gap | Two full clean rounds within 300 s; does not assert underlying service recovery |
| External business effects | Exactly 0 |

A **failure, refusal, hold, missingness, premature stop, unqualified setup, or operator takeover stays in the report**. A zero count is not inferred from missing instrumentation. Start-up failures before qualified baseline are marked unqualified, not admitted as good health windows. Exact slot accounting is distinct from 100% healthy service results. P95s are descriptive percentiles over their explicit denominators.

## 5. Escalation, recovery, stop, handback

- **Immediate fail-closed stop + operator escalation:** 401/403, missing/weakened/changed protected capability flags/fingerprint, unexpected host or scope, any non-GET call, absent on-duty operator, stale authorization, evidence integrity loss, failure to stop collector, suspected secret exposure, or expired window.
- **Transport unknown:** record a classified unknown. It does not imply service is healthy, broken, or recovered. Two *subsequent complete clean* four-source rounds are required to classify evidence as reacquired; if the 300-second recovery budget expires, stop and hand back. Any protected contract anomaly remains **sticky escalation**, even if later reads succeed.
- The operator must be able to halt the pilot sampler and revoke its *pilot-only read credentials* independently. Never compensate by calling effect endpoints, restarting real services or granting broader permissions.
- If no operator is available, do **not** continue a nominally supervised study.
- Unresolved events at terminal time remain visible. A successful process exit, or GitHub Actions "green", does not mean the observations were sound or the human cost was zero.

## 6. Evidence, cost and acceptance decision

Every assigned round and source slot needs source/method, monotonic request start/end, classified result, timestamp context, allowlisted capability fingerprint/error class and sampling configuration. Retain full-window start/stop, version pins, provenance, SHA-256 digest, actual operator acknowledgement/takeover timestamps, separately timed principal-attention and third-party assurance-labor intervals, monitoring runtime and readback call counts. Do not publish credentials, raw response bodies, hostnames/tenant identifiers, or personal ticket content; retention **14 days**, access-restricted.

An independent reviewer must check scope authorization, evidence integrity, completeness, the frozen threshold table, deviations and every triggered stop/escalation. **ALL must pass** for this pilot to be called operationally accepted; otherwise retain the failed result and do not promote privileges. A completed observer window is not useful Agent task delivery.

The readiness gate is currently **not satisfied**, because internal staging inventory, scoped operator approval, staffed time and independent stop/access controls have not been supplied or verified. The next implementation work is a separate opt-in observer runner + qualification tests, not scheduling a live run.

## 7. No automatic extension

Passing this pilot does not authorize P7 unattended operation, periodic background deployment, write operations, production onboarding/offboarding, or an external SDK. Any longer interval, real maintenance ticket, Agent participation, randomized three-regime trial, or mutation requires a new pre-execution contract and a separate approval.

**Revision policy:** v1 parameters and thresholds must not be retroactively edited after the first qualified run. Change the contract version and preserve both positive and negative evidence.
