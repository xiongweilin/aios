# autonomous-development

[![CI](https://github.com/xiongweilin/autonomous-development/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/xiongweilin/autonomous-development/actions/workflows/ci.yml)
[![Security](https://github.com/xiongweilin/autonomous-development/actions/workflows/security.yml/badge.svg?branch=main)](https://github.com/xiongweilin/autonomous-development/actions/workflows/security.yml)
[![Quality Gate](https://sonarcloud.io/api/project_badges/measure?project=metratio_autonomous-development&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=metratio_autonomous-development)
[![Coverage](https://sonarcloud.io/api/project_badges/measure?project=metratio_autonomous-development&metric=coverage)](https://sonarcloud.io/summary/new_code?id=metratio_autonomous-development)
![Python 3.12–3.14](https://img.shields.io/badge/python-3.12--3.14-3776AB?logo=python&logoColor=white)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

Local-first autonomous software development and product-evolution control plane.

> A durable, evidence-driven lifecycle boundary for requirement intake, verification,
> progressive delivery, feedback attribution, promotion and rollback.

## Current V1 snapshot

The V1 operator and dedicated Feishu integration are merged on `main`. The disposable
acceptance target uses a pinned Python 3.14 Alpine image, an upstream-fixed zlib package and
an unchanged `grype --fail-on high` security gate. See
[the acceptance target record](acceptance/target/README.md) and the
[local deployment runbook](docs/v1-local-deployment.md) for the current definition and
verification boundary.

The system owns the closed loop:

```text
requirement
  -> diagnose / plan
  -> build
  -> verify
  -> deploy candidate
  -> user traffic
  -> telemetry / feedback
  -> diagnose
  -> modify
  -> test / evaluate
  -> canary
  -> promote or rollback
  -> repeat
```

V1 deliberately does **not** implement a coding agent. Codex is the engineering executor. This repository owns the durable development lifecycle, evidence, quality gates, progressive delivery, feedback attribution, promotion and rollback decisions around Codex.

## V1 design

- Canonical V1 architecture, semantics, lifecycle and acceptance criteria: [docs/v1-design.md](docs/v1-design.md)
- Local runtime dependencies and deployment prerequisites: [docs/v1-runtime-dependencies.md](docs/v1-runtime-dependencies.md)
- Local bootstrap and operation procedure: [docs/v1-local-deployment.md](docs/v1-local-deployment.md)
- Human requirement/operator API contract: [docs/operator-contract.md](docs/operator-contract.md)
- Feishu integration runbook: [docs/feishu-integration-runbook.md](docs/feishu-integration-runbook.md)
- New Feishu app setup checkpoint: [docs/feishu-autodev-app-setup.md](docs/feishu-autodev-app-setup.md)
- External research basis and adopted/rejected ideas: [docs/v1-research-basis.md](docs/v1-research-basis.md)

## V1 boundary

V1 is a standalone bounded context. Its core package must not import or require:

- `agent-kernel`
- `meta-controller`
- `administrative-orchestrator`

Those projects may inspire design decisions, but they do not define this repository's domain semantics.

V1 now has an optional HTTP-only `WorldRuntimeDevelopmentBridge`. The domain/application layers
depend only on a small port; they do not import the `world-runtime` Python package or Runtime
internals. In cutover mode the bridge mirrors one Development cycle as a generic standing
Responsibility/Work/Run and, only after this domain has independently promoted a release, reports
opaque evidence references for Runtime assessment/Decision/discharge.

World Runtime does **not** own worktrees, Git branches, Docker builds, verification gates,
canary stages, source promotion, rollback, or `ReleasedVersion` semantics.

V1 targets one registered software/Agent product at a time on one local Windows workstation with Docker Desktop. The product goal is human-owned; implementation and iterative improvement inside that goal may run autonomously.

The V1 implementation is local-only. Bootstrap, readiness, autonomous iteration, canary routing,
feedback attribution, promotion/rollback, soak, and terminal cleanup are implemented behind the
single-target runtime boundary. Production acceptance still depends on the repository CI/security
gates and the local readiness/bootstrap checks documented above.
Human requirements from the dedicated Feishu operator profile enter the provider-neutral operator
API and are never converted into `UserFeedback`. Feishu is an operator UI; its outage does not
stop a durable DBOS workflow or discard the PostgreSQL-backed operator outbox.


## World Runtime reality boundary

With `AUTODEV_WORLD_RUNTIME_MODE=cutover`, Runtime Protocol 4.0 requires
`AUTODEV_WORLD_RUNTIME_BEARER_TOKEN`. Deployment, traffic mutation, source
promotion, and source restore remain Development-owned provider semantics, but
their reality-changing dispatches pass through `domain-effect-execution-v3`
before Docker, traffic-state, or Git mutation occurs. Read-only observation,
candidate worktrees, implementation, build, and verification remain local to
Development.
