# Production operations

> 权威英文原文：[production-operations.md](production-operations.md)。本文件是 Administrative V1 + World Runtime 的 component deployment reference，不是整个 AIOS 的 deployment contract。

## 拓扑

```text
Administrative API / Operations API
           ↓
PostgreSQL + DBOS worker
           ↓
      World Runtime
           ↓
   bounded providers
           ↓
 Odoo / Keycloak / communication gateway
```

Administrative PostgreSQL 是 business/domain truth；DBOS 持有 durable scheduling/replay；World Runtime 持有 generic responsibility/authorization/provider-attempt/reconciliation；external system 持有 external reality。

## 必需 Runtime 配置

Production 使用：

```text
ADMIN_WORLD_RUNTIME_MODE=cutover
ADMIN_WORLD_RUNTIME_BASE_URL=http://world-runtime:8020
WORLD_RUNTIME_FACTORY=scripts.production_world_runtime_stack:build
WORLD_RUNTIME_ADMIN_PRODUCTION_STATE_PATH=/var/lib/world-runtime/world-runtime.db
```

World Runtime 源码现在属于同一 AIOS monorepo。Deployment identity 必须绑定 built artifact/image 和 AIOS commit；不能把 `pyproject.toml` 当作独立 Runtime repository locator。配置 inventory 以根 `.env.example` 为准，deployment-specific value 由 `.env` 或外部 secret/config owner 注入。

## Preflight

运行：

```bash
uv run python scripts/production_preflight.py
```

Production preflight 要求 production runtime profile、OIDC auth、PostgreSQL、World Runtime cutover、明确启用 external effect、隔离 writer/verifier credential、有效 Odoo/Keycloak endpoint 和 durable Runtime state path。

Administrative readiness 还检查运行中 Runtime 的 `/v1/capabilities`；缺少 required effect rule 时 fail closed。

## World Runtime

Production image 由 `Dockerfile.runtime` 构建。健康面：

```text
GET /healthz
GET /v1/contracts
GET /v1/capabilities
```

Database、Runtime 和 required provider route ready 之后才能启动 DBOS worker。

## Credential separation

Authority-sensitive external system 的 writer/verifier identity 必须分离。Odoo/Keycloak reader 负责 authoritative fact，Runtime writer 负责 bounded mutation，verifier 负责 independent postcondition read-back。Model gateway credential 只用于 bounded advisory inference。Raw credential 永远不是 business evidence。

## Ambiguous execution

`OUTCOME_UNKNOWN` 不是 resend permission。合法恢复路径：

```text
durable Runtime provider attempt
 -> exact historical provider reconciliation
 -> terminal provider result or remain unknown
 -> Administrative independent read-back
 -> domain Outcome / reopen decision
```

Started durable attempt 没有 committed result 时，禁止 blind redispatch。

## Backup/restore

使用 `scripts/world_runtime_state_backup.py` 进行 online backup、verify 和 restore。Restore 不能写入 live Runtime writer；应先 fence/stop Runtime、verify backup、restore durable state path、重新验证 `/healthz`/`contracts`/`capabilities`，再检查 unresolved provider attempt 并完成 reconciliation。

Administrative PostgreSQL、DBOS PostgreSQL、Runtime state 和 external system 是独立 durability domain；backup set 不是 distributed transaction snapshot。

## Incident 与 rollback

Runtime unavailable 时禁止绕过 Runtime 直接写 provider。Lost ACK 必须保留同一个 Administrative Effect identity 和 Runtime idempotency key，并先 Runtime reconciliation + independent read-back。

Rollback 不会授权 replay uncertain external mutation。回滚前记录 build identity、保留 database/Runtime state、识别所有 in-flight/ambiguous effect，并将其 reconciliation 完成或明确带入 restored deployment。

Acceptance 要求当前 revision 的 component verification、Runtime integration gate、AIOS repository checks，以及与实际 deployment 匹配的 production/read-back evidence。Local fixture 不得冒充 real-provider evidence。
