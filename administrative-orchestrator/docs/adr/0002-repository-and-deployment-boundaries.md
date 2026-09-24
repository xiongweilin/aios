# ADR 0002 — Repository and deployment boundaries

Status: Accepted (runtime ownership superseded by ADR 0007)

Date: 2026-09-09

## Context

M4 established a real process/repository boundary between `administrative-orchestrator` and `agent-kernel`: Administrative owns business facts, policy, organizational authority, obligations, semantic verification, completion, and exception operations; Agent Kernel owns generic responsibility/Work, runtime authorization, the physical `RealityBoundary`, execution recovery, and reconciliation.

M5 adds more independently deployed processes and technologies inside the Administrative product:

- Administrative API;
- Operations API;
- DBOS worker;
- PostgreSQL/DBOS durability;
- Odoo/Keycloak authoritative readers and Kernel-facing writer/verifier integration code;
- TypeScript Operations Console;
- deployment, observability, backup/restore, and staging-acceptance assets.

These process boundaries create a natural question: should each service, UI, or connector become a separate repository?

Repository boundaries have costs that process boundaries do not: independent versioning, cross-repository API compatibility, coordinated release ordering, duplicated CI/security policy, ownership ambiguity, and a larger chance that semantic contracts drift. A repository split therefore needs a stronger reason than language, container, directory size, or deployment topology.

## Decision

Keep `agent-kernel` as a separate repository and keep the current Administrative product surfaces in the `administrative-orchestrator` repository.

The repository topology is:

```text
agent-kernel
    canonical generic responsibility / Work / runtime authority
    physical RealityBoundary
    generic execution evidence / recovery / reconciliation

administrative-orchestrator
    Administrative domain and business state
    policy / identity projection / authority / obligations / completion
    Administrative API
    Operations API
    DBOS orchestration worker
    Administrative authoritative-read integrations
    Administrative Kernel-facing provider/verifier integration profiles
    Operations Console (TypeScript)
    migrations / deployment / observability / DR / documentation
```

Deployment units remain free to separate where security, scaling, or availability requires it. Repository ownership is based on semantic/versioning ownership, not on process count.

## Why Agent Kernel remains separate

`agent-kernel` has a canonical contract and lifecycle that is not Administrative-specific. It can evolve generic Work/Run/Attempt, runtime authority, `RealityBoundary`, recovery, reconciliation, and responsibility semantics without owning Administrative business interpretation.

Administrative consumes the Kernel through versioned public contracts, a pinned supported production revision, and a current-`main` forward-compatibility canary. Direct source/package co-ownership is not required and would weaken the canonical ownership boundary established in ADR 0001.

## Why the Administrative surfaces remain one repository

The Administrative API, worker, Operations API, Console, integrations, migrations, and production assets currently share:

- one Administrative domain ontology;
- one database migration history;
- one business authority/policy/completion contract;
- one M5 production-trust acceptance lifecycle;
- one coordinated release compatibility requirement;
- one set of cross-layer invariants that must remain green on the same PR head.

The Operations Console is an Administrative exception-operations client, not a standalone authority owner. Its TypeScript implementation is a language boundary, not a repository boundary. Browser-side authorization is UX only; Administrative backend authority remains canonical.

The Odoo/Keycloak integration code is also not a generic connector SDK. It carries Administrative request identity, fact provenance, declared postconditions, writer/verifier separation, and execution-unknown/reconciliation semantics. Those semantics currently belong to the Administrative product/deployment contract even though physical writes cross the Kernel-owned `RealityBoundary`.

## Service boundary does not imply repository boundary

The following are valid independent deployment/process boundaries while remaining in the same repository:

```text
Administrative API
Operations API
DBOS worker
Operations Console
migration job
Agent Kernel service (built from the separate agent-kernel source contract)
```

Separate processes may have different credentials, network policies, scaling, and health checks. They can still share one repository when they have one coordinated semantic/versioning owner.

## Repository split triggers

A component becomes a serious repository-split candidate only when several of these conditions are true:

1. it has a stable contract consumed by two or more independently released products/domains;
2. it has an independent release cadence and can be upgraded without coordinated Administrative release changes;
3. it has a distinct owning team or governance authority;
4. it has an independent SLA, security/network/secret boundary that benefits from separately governed source/release controls;
5. its public interface needs independent semantic versioning and compatibility policy;
6. changes to it no longer need the same Administrative migration/domain/acceptance transaction;
7. cross-repository CI can prove compatibility without recreating the current monorepo acceptance cycle.

Code size, a different programming language, a separate Docker image, or a separately scalable process is not sufficient by itself.

## Connector split policy

Do not create generic `odoo-connector`, `keycloak-connector`, or `integrations` repositories merely to reduce directory size.

A connector may move to a separate repository/package when it has a genuinely reusable, domain-neutral port used by multiple products and the product-specific semantic mapping remains in the consuming domain. Until then:

```text
vendor transport mechanics
+ Administrative request identity
+ Administrative fact/postcondition mapping
+ Administrative acceptance tests
```

remain colocated so the authority/reality distinctions cannot drift silently.

## Consequences

Positive:

- semantic and migration changes can remain atomic across the Administrative product;
- M4/M5 invariants can be proven on one PR head;
- TypeScript/Python and service/process separation remain possible without repository proliferation;
- connector and Operations UI changes cannot silently outrun Administrative authority/completion contracts;
- Agent Kernel preserves a real independent canonical runtime boundary.

Trade-offs:

- the Administrative repository contains multiple languages and deployment assets;
- CI is broader because it validates a product system rather than one process;
- access-control/source-ownership rules may need path-level CODEOWNERS or CI policy later if team size grows;
- future extraction may require deliberate contract/version migration rather than a simple directory move.

These trade-offs are accepted for M5 because they preserve semantic coherence while the production model is still being validated.

## Revisit condition

Revisit this ADR after M5 real-staging acceptance and again when M6 introduces broader administrative slices or when a second independent product needs the same connector/operations component.

Until a split trigger is demonstrated by real ownership/versioning pressure, prefer internal modules, ports, separate processes, and separate credentials over new repositories.
