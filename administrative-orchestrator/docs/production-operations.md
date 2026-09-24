# Production operations

This runbook describes the current Administrative V1 + World Runtime production topology.

## Topology

```text
Administrative API / Operations API
           |
           v
PostgreSQL + DBOS worker
           |
           v
      World Runtime
           |
   bounded providers
           |
 Odoo / Keycloak / communication gateway
```

Administrative PostgreSQL is business/domain truth.
DBOS owns durable scheduling and replay.
World Runtime owns generic responsibility/authorization/provider-attempt/reconciliation state.
External systems own external reality.

## Required Runtime configuration

Production uses:

```text
ADMIN_WORLD_RUNTIME_MODE=cutover
ADMIN_WORLD_RUNTIME_BASE_URL=http://world-runtime:8020
WORLD_RUNTIME_FACTORY=scripts.production_world_runtime_stack:build
WORLD_RUNTIME_ADMIN_PRODUCTION_STATE_PATH=/var/lib/world-runtime/world-runtime.db
```

`world-runtime` itself is pinned to an immutable Git SHA in `pyproject.toml`.
There is no mutable deployment-level Agent Kernel revision source.

Use `.env.production.example` as the configuration inventory.

## Preflight

Run:

```bash
uv run python scripts/production_preflight.py
```

Production preflight requires:

- production runtime profile;
- OIDC authentication;
- PostgreSQL for Administrative/worker/DBOS state;
- World Runtime cutover mode;
- external effects explicitly enabled;
- isolated writer/verifier credentials;
- valid Odoo/Keycloak production endpoints;
- durable World Runtime state path.

The Administrative readiness endpoint also checks the running Runtime
`/v1/capabilities` surface and fails closed if required effect rules are absent.

## Starting World Runtime

The production image is built from `Dockerfile.runtime`.

The configured app is:

```bash
WORLD_RUNTIME_FACTORY=scripts.production_world_runtime_stack:build \
WORLD_RUNTIME_ADMIN_PRODUCTION_STATE_PATH=/var/lib/world-runtime/world-runtime.db \
python -m uvicorn world_runtime.service:create_configured_app \
  --factory --host 0.0.0.0 --port 8020
```

Health:

```text
GET /healthz
GET /v1/contracts
GET /v1/capabilities
```

Start the DBOS worker only after databases, Runtime, and required provider routes are ready.

## Provider credential separation

Writer and verifier identities must be distinct for authority-sensitive external systems.

Typical roles:

| System | Identity | Permitted purpose |
| --- | --- | --- |
| Odoo | reader | authoritative Administrative facts |
| Odoo | Runtime writer | bounded HRIS/ERP mutations |
| Odoo | verifier | independent authoritative postcondition read-back |
| Keycloak | reader | authoritative identity/access facts |
| Keycloak | Runtime writer | bounded IAM mutation |
| Keycloak | verifier | independent postcondition read-back |
| model gateway | investigation credential | bounded advisory inference only |

Raw credentials are never business evidence.

## Ambiguous execution

`OUTCOME_UNKNOWN` is not resend permission.

The legal recovery path is:

```text
durable Runtime provider attempt
 -> exact historical provider reconciliation
 -> terminal provider result or remain unknown
 -> Administrative independent read-back
 -> domain Outcome / reopen decision
```

If Runtime has a started durable attempt without a committed result, it forbids blind redispatch.

## World Runtime state backup

Create an online SQLite backup:

```bash
uv run python scripts/world_runtime_state_backup.py backup \
  "$WORLD_RUNTIME_ADMIN_PRODUCTION_STATE_PATH" \
  /secure-backups/world-runtime-$(date -u +%Y%m%dT%H%M%SZ).db
```

Verify:

```bash
uv run python scripts/world_runtime_state_backup.py verify \
  /secure-backups/world-runtime-20260920T090000Z.db
```

## World Runtime restore

Do not restore into a live Runtime writer.

1. stop/fence the Runtime process;
2. verify the selected backup;
3. restore to the durable Runtime state path;
4. start Runtime and verify `/healthz`, `/v1/contracts`, and `/v1/capabilities`;
5. inspect unresolved durable provider attempts before resuming effect submission;
6. reconcile ambiguous attempts before considering any resend.

Restore:

```bash
uv run python scripts/world_runtime_state_backup.py restore \
  /secure-backups/world-runtime-approved.db \
  "$WORLD_RUNTIME_ADMIN_PRODUCTION_STATE_PATH" \
  --force
```

Administrative PostgreSQL, DBOS PostgreSQL, Runtime state, and external systems are independent
durability domains. A backup set is not a distributed transaction snapshot.

## Incident: Runtime unavailable

- stop new effect dispatch;
- preserve Administrative case/authorization state;
- preserve Runtime state volume;
- restore/restart Runtime;
- inspect provider attempts and reconciliation status;
- resume only after readiness and required capability contracts are healthy.

Do not bypass Runtime with direct provider writes.

## Incident: provider acknowledgement lost

- keep the same Administrative Effect identity;
- keep the same Runtime idempotency key;
- do not mint a new request merely to clear uncertainty;
- invoke Runtime reconciliation;
- perform independent domain read-back;
- only then qualify Outcome or governed correction.

## Deployment and rollback

Rollback never authorizes replay of an uncertain external mutation.

Before rolling back:

- record Administrative/Runtime build identities;
- preserve current databases and Runtime state;
- identify all in-flight/ambiguous effect identities;
- complete reconciliation or explicitly carry those identities into the restored deployment.

## Acceptance evidence

Current V1 acceptance is produced by CI, the Production Trust workflow, Runtime integration gates,
and fresh production/read-back evidence. Run-specific evidence belongs in CI artifacts or an
operator-controlled evidence store, not as staged milestone snapshots in the source tree.

Unit tests and local fixtures prove repository semantics; they are not relabeled as real-provider
evidence.
