# personal-world

> AIOS kernel component. Source: `src/kernel/personal_world/`. Runtime: root `compose.yaml`.


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

## Runtime

Personal World has no native host deployment path. It runs as the `personal-world` service in the
root AIOS Compose topology. Its durable state is mounted at `/var/lib/aios`.

The API contract still requires `X-Service-Identity` and `X-Purpose`; projection and search reads
remain constrained by caller data-access and sensitivity rules.

## v1.0 closure

The four public record kinds remain frozen. v1.0 adds no fifth kind and no domain lifecycle semantics.
It closes the production boundary with one-root-subject isolation, short-lived signed workload identity,
PostgreSQL contention evidence, bitemporal tests, cross-surface erasure, and physical restore with
post-backup erasure replay before exposure.

Production deployments set `PERSONAL_WORLD_DEPLOYMENT_PROFILE=production`,
`PERSONAL_WORLD_ROOT_SUBJECT_ID`, and `PERSONAL_WORLD_AUTH_MODE=signed-hmac`.
The contract names remain `personal-world-contracts-v1` and `personal-world-conformance-v1`.
