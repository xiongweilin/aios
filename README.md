# AIOS

AIOS is one headless, container-native system.

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
  aios/                         product composition
  semantic_language/            cross-domain semantics
  personal_world/               kernel: personal continuity
  world_runtime/                kernel: agency continuity
  control_plane/                domain: operations
  administrative_orchestrator/  domain: administration
  autonomous_development/       domain: software development

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
config/
scripts/
deploy/
```

There is one Python project, one dependency graph, one source root and one test root.

## Runtime

AIOS has no UI. Services expose API/CLI boundaries and run as containers.

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

## Development

The product runtime remains container-only. Repository checks may run in CI or a disposable
development container; they are not product deployment paths.

```bash
docker build -t aios:local .
docker compose config --quiet
```

Component-specific semantics and contracts live under the corresponding `docs/` and `contracts/` paths.
