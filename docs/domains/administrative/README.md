# administrative-orchestrator

> Component of the [AIOS monorepo](../README.md) at `administrative-orchestrator/`; this directory is not an independent GitHub repository.

![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

Governed administrative automation as an external Domain Controller for
`world-runtime`.

This component owns Administrative meaning: trusted intake, organizational authority,
business obligations, effect intent, authoritative read-back, domain Outcome, completion,
reconciliation qualification, commitments, communication, and governed reopen.

It does not own the generic persistent agency runtime.

## Current execution topology

```text
organizational request / evidence
        |
        v
Administrative domain
  facts / policy / authority
  GovernanceBasis
  AdministrativeObligationSet
  ExecutionAuthorization
  EffectRecord
        |
        | bounded semantic responsibility/effect
        v
World Runtime
  Responsibility
  Work / Run
  Decision / Mandate / Authorization
  durable provider attempt
  provider invocation / reconciliation
        |
        v
external system reality
        |
        v
Administrative independent read-back
  EffectRealizationAssessment
  ConfirmedOutcome
  CompletionAssessment
  responsibility discharge / reopen
```

Provider success is only an execution fact. It never proves a domain Outcome or case
completion.

## Ownership

`administrative-orchestrator` owns:

- Administrative request/case and immutable fact provenance;
- identity projection, roles, delegation, policy, Decisions and approval satisfaction;
- `GovernanceBasis` and business obligations;
- Administrative `ExecutionAuthorization` and `EffectRecord`;
- domain-specific verification, `ConfirmedOutcome`, completion and reopen;
- employee lifecycle, financial transaction, commitment and communication semantics;
- Operations API and Administrative integration contracts.

`world-runtime` owns:

- persistent responsibility and responsibility lifecycle;
- generic Work / Run;
- generic Decision / Mandate / Authorization state;
- capability contracts, provider selection and invocation;
- durable provider-attempt identity, idempotent replay and ambiguous-result reconciliation;
- generic execution evidence and persistent runtime state.

DBOS owns durable workflow scheduling/wait/replay. External systems remain authoritative for
the reality they own.

## Non-substitution invariants

```text
Source authenticity != content truth
Interpretation != authoritative fact
Candidate != AdministrativeRequest
Decision != ApprovalSatisfaction
ApprovalSatisfaction != GovernanceBasis
GovernanceBasis != ExecutionAuthorization
ExecutionAuthorization != Runtime Authorization
AdministrativeObligation != Runtime Work
EffectRecord != external reality
Provider success != ConfirmedOutcome
OUTCOME_UNKNOWN != retry permission
Case completion != responsibility discharge
transport_accepted != delivery_confirmed
delivery_confirmed != human_read
Investigation != authority
ReframingProposal != reframe
Reopen != history deletion
```

These are product invariants, not naming conventions.

## World Runtime boundary

The production boundary is implemented by
`src/administrative_orchestrator/integrations/world_runtime.py`.

Administrative compiles a governed effect into:

```text
Responsibility
-> Work
-> Run
-> Decision
-> Mandate
-> Runtime Authorization
-> capability invocation
```

The Runtime records the provider attempt before crossing the provider boundary. A lost
acknowledgement therefore becomes reconciliation under the same durable identity rather than
permission to resend.

Administrative still performs independent authoritative read-back and owns the resulting
business Outcome.

Production provider registration is in `scripts/domains/administrative/production_world_runtime_stack.py`.
Runtime state backup/restore is in `scripts/domains/administrative/world_runtime_state_backup.py`.

## Supported slices

The current system covers:

- employee onboarding and offboarding;
- authoritative HRIS/IAM refresh and governed lifecycle effects;
- procurement, invoice/AP preparation, and expense reimbursement;
- meeting self-commitments and explicit responsibility discharge;
- governed internal communication;
- bounded investigation/reframing/reopen;
- Operations API;
- PostgreSQL/DBOS durability and Runtime-state DR.

It does not claim payment/settlement authority, proof of human read, delegated commitment
assignment, or unrestricted autonomous administration.

## Repository map

From the AIOS repository root:

```text
src/administrative_orchestrator/        domain source
tests/domains/administrative/           domain tests
scripts/domains/administrative/         operational helpers
docs/domains/administrative/            domain documentation
migrations/domains/administrative/      database migrations
config/domains/administrative/          runtime examples
```

## Stable identifiers

Persisted wire, policy, effect, and audit identifiers that participate in replay or external compatibility remain stable. Current acceptance is grounded in AIOS root checks, Runtime integration gates, and the production operations contract below.

## Development

```bash
python -m pip install -e '.[dev]'
ruff check src tests
pytest -q tests/domains/administrative
```

The component tests and scripts cover the World Runtime boundary, DBOS behavior, deployment fixtures, and production invariants. Repository-level static analysis and quality-gate status are owned by the AIOS monorepo root workflow.

Current architecture: `architecture.md`.
Canonical Administrative vocabulary: `contracts/domain-model.md`.
Production operations: `production-operations.md`.
