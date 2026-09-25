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
docker compose up -d personal-world world-runtime
docker compose --profile domains up -d
```

Agent implementations, LLM providers, Prometheus and other external systems are integrations, not semantic owners.

## Development

```bash
python -m pip install -e '.[dev]'
pytest
ruff check src tests
```

Component-specific semantics and contracts live under the corresponding `docs/` and `contracts/` paths.
