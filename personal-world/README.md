# personal-world

> Component of the [AIOS monorepo](../README.md) at `personal-world/`; this directory is not an independent GitHub repository.

![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white)
![License: MIT](https://img.shields.io/badge/license-MIT-green)
![Version](https://img.shields.io/badge/version-1.0.0-6f42c1)

`personal-world` is the durable, user-owned representation of one person's evolving world.
It preserves provenance, temporal lineage, qualification, privacy boundaries, and purpose-limited
context projection so models and agents can be replaced without losing personal continuity.

Current package: **1.0.0 durable personal-context baseline**.

## Permanent ownership boundary

`personal-world` owns long-lived personal context: facts, preferences, relationships, resource links,
provenance, revisions, freshness, privacy classification, and context projection.

It deliberately does **not** own Decisions, Authorizations, Mandates, Responsibilities, Work/Runs,
Effects, Outcomes, provider execution, domain lifecycles, agent routing, model routing, credentials,
or model-private memory. Those belong to World Runtime, Domain Controllers, agent-router,
LiteLLM/model infrastructure, secret stores, or ephemeral cognitive execution.

The central non-substitution rules are:

- Source != Observation != Claim != current personal state.
- Historical truth != current truth.
- Context Projection != canonical truth.
- Personal context != execution authority.
- Domain projection != domain ownership.
- Model inference != accepted personal preference or fact.

## Development

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
pytest
uvicorn personal_world.api.app:app --reload
```

By default the service uses `sqlite:///./personal-world.db`. Set `PERSONAL_WORLD_DATABASE_URL`
to a PostgreSQL SQLAlchemy URL for shared durable operation.

Every API caller must provide `X-Service-Identity` and `X-Purpose`; projection and search reads are
filtered by the caller's data-access profile and sensitivity ceiling.

See `docs/architecture.md`, `docs/contracts.md`, `docs/threat-model.md`, and
`docs/releases/v0.1-v0.9.md`.


## v1.0 closure

The four public record kinds remain frozen. v1.0 adds no fifth kind and no domain lifecycle semantics.
It closes the production boundary with one-root-subject isolation, short-lived signed workload identity,
PostgreSQL contention evidence, bitemporal tests, cross-surface erasure, and physical restore with
post-backup erasure replay before exposure.

Production deployments set `PERSONAL_WORLD_DEPLOYMENT_PROFILE=production`,
`PERSONAL_WORLD_ROOT_SUBJECT_ID`, and `PERSONAL_WORLD_AUTH_MODE=signed-hmac`.
The contract names remain `personal-world-contracts-v1` and `personal-world-conformance-v1`.
