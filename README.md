# AIOS

[![CI](https://github.com/xiongweilin/aios/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/xiongweilin/aios/actions/workflows/ci.yml)
[![SonarCloud Quality Gate](https://sonarcloud.io/api/project_badges/measure?project=metratio_aios&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=metratio_aios)

AIOS is one headless, container-only runtime.

```text
semantic
  semantic_language

kernel
  personal_world
  world_runtime

domains
  control_plane
  administrative_orchestrator
  autonomous_development
```

The names above are internal semantic owners, not separate products or repositories.

## Repository layout

```text
src/
  aios/                         runtime composition
  semantic/
    semantic_language/          cross-domain semantics
  kernel/
    personal_world/             personal continuity
    world_runtime/              agency continuity
  domains/
    control_plane/              operations
    administrative_orchestrator/
    autonomous_development/

tests/
  semantic/
  kernel/
  domains/
  acceptance/

docs/
  semantic/
  kernel/
  domains/

contracts/
migrations/
scripts/
```

There is one Python project, one dependency graph, one source root and one test root. Semantic, kernel and domain ownership are physical source groups inside that single project.

## Runtime

AIOS has no UI. Services expose API/CLI integration boundaries and run as containers.

```bash
docker compose up -d
```

All AIOS runtime components are containers. The host does not run Personal World, World Runtime,
Control Plane, Administrative, or Autonomous Development as native programs. The host only
provides the container runtime and bind-mounted resources such as an Autodev workspace or Docker
socket.

Agent implementations, LLM providers, Prometheus and other external dependencies are reached
through container-network endpoints or external APIs. AIOS runtime configuration must not depend
on a host-local program listener.

AIOS is designed for continuous, unattended operation, not as an interactive assistant product.
The user does not routinely operate the runtime directly. When inspection, explanation, or
maintenance is needed, the user may connect through an existing external Agent product for a
short-lived session. That Agent reads authoritative state, explains the condition, performs only
bounded authorized changes, verifies read-back and recovery, reports the result, and disconnects.
The Agent session is not a durable authority owner or a required runtime dependency; AIOS continues
operating after it ends. API/CLI boundaries are for system integration and maintenance, not a
primary user-management interface.

## Development

The AIOS runtime remains container-only. Repository checks may run in CI or a disposable
development container; they are not product deployment paths.

```bash
docker build -t aios:local .
docker compose config --quiet
```

Component-specific semantics and contracts live under the corresponding `docs/` and `contracts/` paths.
