# ADR 0004 — Employee lifecycle responsibility

Status: Accepted

Date: 2026-09-10

## Context

M0–M6 proved one Administrative vertical end to end: non-structured organizational
input becomes trusted intake, a candidate, human-confirmed admission,
authoritative facts, policy, authority, obligations, Kernel-owned effects,
independent verification, and completion. That vertical creates relations.

The next real question is harder: an existing relationship must become invalid,
some responsibilities must transfer, some history must remain traceable, and
some authority must end exactly at a qualified time. This is the first
Administrative transaction whose subject is a *terminating* relationship rather
than a new one.

The naive model — "offboarding is deleting a user" — is wrong in every direction:
it destroys the audit history, it conflates request/claim with authoritative
truth, it cannot express effective-time qualification, and it cannot carry
unresolved continuity work.

## Decision

### 1. One product repository, one new case kind

M7 lives in the `administrative-orchestrator` monorepo and adds exactly one
case kind, `employee-offboarding`. No offboarding service repository, no
employee-lifecycle repository, no identity-revocation repository.

### 2. Termination truth comes from an authoritative HR source

```text
Feishu: "X leaves today"                        → CLAIM
HRIS:   termination_status / effective_at       → AUTHORITATIVE
```

An offboarding case never writes its own termination truth and then cites that
truth as evidence. The staging/acceptance termination schedule is written by an
independent HR administrator action, not by the case's own execution path.

### 3. Effective time is a qualification, not a delay

Approval may happen before the termination becomes effective. The case then
`WAITING`s until the qualified effective time. DBOS owns waiting, waking,
timeout, and durable replay; DBOS does **not** own authority. A fired timer is
not authorization: at wake the system revalidates authoritative termination,
effective time, policy currency, approval/governance currency, subject identity,
and successor requirements before any action. Long sleeps and provider-held
threads are forbidden.

### 4. Phase model

```text
SAFETY_REVOCATION      roles/delegations/bindings expire; IAM disabled; sessions revoked
CONTINUITY_TRANSFER    transfer-required relationships receive a qualified successor
EMPLOYMENT_FINALIZATION HRIS reflects the post-employment reality
```

Security cutoff must not be later than the external access cutoff, and a missing
successor must never keep the departing subject's access alive: revocation
proceeds, the transfer obligation remains open, the case does not complete, and
responsibility stays ACTIVE.

### 5. Administrative authority ends at the effective time

Existing role assignments and delegations already carry `valid_from`/`valid_until`.
M7 ends current authority by ending validity and appending an authority-lifecycle
audit event — not by inventing `RevokedRoleAssignment`/`DeletedRoleAssignment`
types and not by deleting history. Both directions of delegation (departing
principal as source and as recipient) must stop producing current authority.
Principal deactivation is sequenced after binding/role/delegation expiry, IAM
disable, session revoke, and the remaining transfer/finalization work.

### 6. Transfer is an explicit typed requirement

Transfer-required relationships are policy-owned, not hardcoded in the execution
engine:

```text
AdministrativeTransferRequirement
  requirement_id, case_id, authority_epoch, departing_principal_id,
  relationship_kind, role, organization_scope, transfer_mode,
  successor_principal_id | None, effective_at, status
```

with `transfer_mode` in {`REVOKE_ONLY`, `TRANSFER_REQUIRED`}. A successor must
exist, be active, be inside the correct organization scope, be policy-eligible,
and differ from the departing principal. A name mentioned in a message never
creates successor authority.

### 7. Two fulfillment sources, one completion contract

External obligations are fulfilled by Kernel-owned effects plus independent
readback; Administrative domain-state obligations are fulfilled by verified
Administrative domain state. Both are first-class, neither is simulated as the
other, and human attestation is never a material security proof. Completion is
generalized to a second case kind with compatibility wrappers preserving M5/M6
behavior.

### 8. Governance: pre-effect basis vs expected post-effect reality

A frozen pre-effect governance basis must not treat the *expected* effect result
as a dependency. HRIS `active: true → false` is the intended self-induced
reality change, not governance drift:

```text
Decision dependency truth   != expected effect target state
Pre-effect basis            != post-effect observation
Expected self-induced change != governance drift
```

The minimal mechanism (dependency-scoped basis keys or explicit pre/post
separation) is chosen during implementation; historical records keep whole
snapshot semantics and are not migrated for tidiness.

### 9. Completion and responsibility discharge stay separate facts

```text
case COMPLETED
!=
responsibility DISCHARGED

CompletionAssessment
→ ResponsibilityAssessment
→ ResponsibilityDischargeDecision
→ ResponsibilityLifecycleTransition ACTIVE → DISCHARGED
```

The decision records a fact and does not itself mutate lifecycle state. Missing
successor, unverified session revocation, unknown outcome, stale governance,
HRIS still active, departing authority still current, or unresolved
reconciliation each block discharge.

### 10. Kernel boundary

Agent Kernel owns distinctions; the domain owns interpretation. M7 capabilities
are deployment-owned typed capability strings with provider bindings,
independent verifiers, and reconciliation contracts:

```text
administrative.iam.identity.disable.v1
administrative.iam.sessions.revoke.v1
administrative.hris.employee.deactivate.v1
```

Kernel never learns employee, termination, HRIS, IAM, successor, or
AdministrativeCase semantics. If the Kernel lacks a *public generic seam* for
persistent-responsibility assessment/decision/transition, the only allowed
Kernel change is a narrow generic contract exposing those existing internal
semantics; if the seam already exists, Administrative adds a typed client and
the supported pin is upgraded under the compatibility policy.

### 11. Recovery discipline

`execution_unknown` is never retry permission, even for seemingly idempotent
operations such as disable or session revoke. Kernel canonical recovery
reconciles the exact historical request and independently verifies reality.
Responsibility discharge is blocked until the outcome is resolved.

### 12. Employment episodes and rebound protection

A stale offboarding replay must not mutate a newly re-activated employment
relationship. Reuse identity, authority epoch, and authoritative source version
where they already prove the episode change; add an explicit
`employment_episode_ref`-style durable identity only if the current model cannot
distinguish the same person under a different episode.

## Consequences

- M7 adds durable models from migration `0019`; M0–M6 migrations are untouched.
- A second case kind forces the smallest honest generalization of obligations,
  completion, and governance; no universal workflow engine is introduced.
- Staging gains an isolated `administrative-m7-staging` topology; the accepted M6
  environment, records, volumes, and tag are preserved unchanged.
- Operations Console may expose observation, human admission, authorized
  decisions, reassessment, and policy-permitted successor selection, but never
  force-offboard, skip-effective-time, mark-verified, retry-provider, or
  force-discharge controls.
- M7 acceptance requires real intake, real HR authority, real Kernel effects,
  real session revocation evidence, real readback, and explicit discharge
  evidence; mocks cannot substitute.

