# autonomous-development

> Component of the [AIOS monorepo](../README.md) at `autonomous-development/`; this directory is not an independent GitHub repository.

![Python 3.12–3.14](https://img.shields.io/badge/python-3.12--3.14-3776AB?logo=python&logoColor=white)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

Local-first autonomous software development and product-evolution control plane.

> A durable, evidence-driven lifecycle boundary for requirement intake, verification,
> progressive delivery, feedback attribution, promotion and rollback.

## Current V1 snapshot

The V1 lifecycle surface and provider-neutral operator API are part of this component. The disposable
acceptance target uses a pinned Python 3.14 Alpine image, an upstream-fixed zlib package and
an unchanged `grype --fail-on high` security gate. See [the acceptance target record](acceptance/target/README.md) for the disposable verification fixture.

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

V1 deliberately does **not** make a specific coding agent part of its domain semantics. Engineering execution is a provider boundary; concrete executors are deployment choices. This component owns the durable development lifecycle, evidence, quality gates, progressive delivery, feedback attribution, promotion and rollback decisions around the selected executor.

## V1 design

- Canonical V1 architecture, semantics, lifecycle and acceptance criteria: [docs/v1-design.md](docs/v1-design.md)
- Human requirement/operator API contract: [docs/operator-contract.md](docs/operator-contract.md)
- External research basis and adopted/rejected ideas: [docs/v1-research-basis.md](docs/v1-research-basis.md)

## V1 boundary

V1 is a standalone bounded context. Its core package must not import or require:

- `agent-kernel`
- `meta-controller`
- `administrative-orchestrator`

Those projects may inspire design decisions, but they do not define this component's domain semantics.

V1 now has an optional HTTP-only `WorldRuntimeDevelopmentBridge`. The domain/application layers
depend only on a small port; they do not import the `world-runtime` Python package or Runtime
internals. In cutover mode the bridge mirrors one Development cycle as a generic standing
Responsibility/Work/Run and, only after this domain has independently promoted a release, reports
opaque evidence references for Runtime assessment/Decision/discharge.

World Runtime does **not** own worktrees, Git branches, Docker builds, verification gates,
canary stages, source promotion, rollback, or `ReleasedVersion` semantics.

V1 targets one registered software/Agent product at a time. The product goal is human-owned; implementation and iterative improvement inside that goal may run autonomously. Host OS, model gateway, container runtime, and monitoring are deployment/provider choices, not lifecycle semantics.

The implementation exposes an operator API and durable workflow boundary without a bundled user
interface. Human requirements enter the provider-neutral operator API and are never converted into
`UserFeedback`.


## World Runtime reality boundary

With `AUTODEV_WORLD_RUNTIME_MODE=cutover`, Runtime Protocol 4.0 requires
`AUTODEV_WORLD_RUNTIME_BEARER_TOKEN`. Deployment, traffic mutation, source
promotion, and source restore remain Development-owned provider semantics, but
their reality-changing dispatches pass through `domain-effect-execution-v3`
before configured deployment, traffic-state, or Git mutation occurs. Read-only observation,
candidate worktrees, implementation, build, and verification remain local to
Development.
