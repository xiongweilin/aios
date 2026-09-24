# control-plane

> Component of the [AIOS monorepo](../README.md) at `control-plane/`; this directory is not an independent GitHub repository.

![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

An AIOS Domain Controller component for [world-runtime](../world-runtime/README.md), focused on authenticated personal/platform operations, monitoring, bounded repair, and narrowly scoped effects.

This component is intentionally not a second World Runtime.

```text
World Runtime
= universal durable semantics
  Responsibility / DomainAssignment / Decision / governance / audit

        HTTP protocol 4.0
        domain-assignment-v3
        domain-report-v3

control-plane
= bounded control-plane domain
  incident/manual lifecycle
  domain journal
  provider routing
  monitoring/integrations
  concrete local effects
```

## Ownership boundary

`control-plane` owns deployment- and domain-specific implementation:

- alert and manual-task ingress;
- control-plane-local controller state;
- control-plane-local Work/Run projections;
- bounded repair policy;
- provider selection and concrete provider execution;
- environment facts and monitoring observations;
- local operational reconciliation;
- notification and local source/deployment integrations.

World Runtime remains the canonical owner of cross-domain semantic objects such as:

- persistent Responsibility;
- DomainAssignment lifecycle;
- durable Decision records;
- responsibility assessment/discharge;
- typed evidence/outcome references reported across the domain boundary.

The boundary is protocol-based, not Python-import-based.

Production source must not import `world_runtime`, and `pyproject.toml` / `uv.lock` must not depend on the `world-runtime` Python package. CI enforces both constraints.

## Runtime handshake

Startup fails closed unless the external Runtime exposes the exact supported contract surface:

```text
runtime_protocol = 4.0
semantic_language = 0.2.0

request_authentication = request-authentication-v2
transition_authority = transition-authority-v1
read_authorization = read-authorization-v1
persistent_responsibility = persistent-responsibility-v3
responsibility_assessment = responsibility-assessment-v3
responsibility_discharge = responsibility-discharge-v3
decision_record = decision-record-v4
domain_assignment = domain-assignment-v3
domain_report = domain-report-v3
```

The Runtime endpoint is configured through the `[runtime]` section of `control_plane.toml`. Runtime Protocol 4.0 authenticates the Controller credential separately from an optional bounded delegation to the configured owner principal.

## Example: bounded incident repair

A firing alert does not become authorized action because a model produced a diagnosis.

The control-plane domain loop is:

```text
monitoring signal
      |
      v
authenticated ingress
      |
      v
World Runtime Responsibility + DomainAssignment
      |
      v
control-plane PersonalController
      |
      v
RepairEpistemicProfile
      |
      v
bounded diagnosis
      |
      v
RepairClosure
      |
      v
local work proposal / DomainWork / DomainRun
      |
      v
bounded concrete provider
      |
      v
reality observation / verification
      |
      v
RepairRevision
  /       |       \
close   reopen    wait
      |
      v
typed DomainReport
      |
      v
World Runtime assessment / Decision / discharge
```

There is no model-to-effect shortcut. Diagnosis is non-authority-bearing. A closure is a domain planning object, not a universal Runtime Decision. Provider success is not target recovery. Completion is reported back to World Runtime with typed evidence/outcome references before universal responsibility is assessed and discharged.

## Local semantic scope

The local controller deliberately uses domain-specific names:

```text
PersonalController
RepairClosure
RepairRevision
DomainWork
DomainRun
DomainJournal
```

These are control-plane implementation semantics. They do not replace or duplicate universal World Runtime owners such as `Responsibility`, `Decision`, `Authorization`, `Evidence`, `Outcome`, or `Goal`.

This distinction is the reason a local controller is allowed while a copied Runtime kernel is not.

## Provider boundary

Concrete providers are local to this Domain Controller. Examples include:

- Codex reasoning/execution;
- monitoring verification;
- Git synchronization;
- Docker/maintenance operations;

The local provider protocol is an implementation boundary for control-plane. It does not mint universal authority.

Effect providers independently re-check relevant project and state constraints before acting. Model selection does not widen effect scope.

## Recovery

The local `DomainJournal` preserves control-plane-only controller/work/run continuity across process restarts.

Recovery may repair local execution claims such as:

```text
running -> waiting
running run -> interrupted
```

without claiming completion.

Universal responsibility, assignment and decision state is never reconstructed locally; it remains in World Runtime.

## Deliberately absent

The following must not return:

```text
src/world_runtime/
world-runtime Python dependency
in-process WorldRuntime construction
copied World Runtime cognition/execution/ledger kernel
agent-kernel compatibility layer
meta-controller compatibility layer
generic authorization owner
generic evidence/truth owner
generic responsibility/decision owner
portable-local embedded Runtime
```

A rich domain controller is expected. A second universal Runtime is not.

## Public service surface

The service exposes a narrow operational API for:

- health/liveness/readiness and metrics;
- authenticated task submission and continuation;
- authenticated monitoring ingress;
- controller continuation;
- local operational-state inspection.

Transport integrations do not mint authority or decide that a universal objective is complete.

## Setup

```powershell
uv sync --extra dev
uv run control-plane
```

Example configuration is `control_plane.toml.example`. Copy it to the ignored local `control_plane.toml` and set the external World Runtime endpoint plus machine-owned paths.

## Verification

```powershell
uv sync --frozen --extra dev
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -q
```

CI additionally proves:

- no production `world_runtime` imports;
- no `world-runtime` package dependency;
- predecessor runtime code is absent;
- exact Runtime protocol mismatch fails closed;
- SonarCloud Quality Gate passes.


## Reality effect boundary

Runtime Protocol 4.0 keeps Control Plane providers Domain-owned. Capabilities
classified by `CAPABILITY_POLICIES` as local or remote writes may execute only
after World Runtime admits the stable Work, attests Decision/Mandate/Authorization,
binds the durable effect identity, and grants a single dispatch through
`domain-effect-execution-v3`. Read-only cognition remains Controller-local.
