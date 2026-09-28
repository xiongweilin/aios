# personal-world

> AIOS kernel 组件。源码：`src/kernel/personal_world/`。Runtime：根目录 `compose.yaml`。

## 永久所有权边界

`personal-world` 拥有长期个人上下文：事实、偏好、关系、资源链接、provenance、revision、freshness、privacy classification 和 context projection。

它刻意**不**拥有 Decision、Authorization、Mandate、Responsibility、Work/Run、Effect、Outcome、provider execution、domain lifecycle、agent routing、model routing、credential 或 model-private memory。这些分别属于 World Runtime、Domain Controller、agent-router、provider/model-routing infrastructure、secret store 或 ephemeral cognitive execution。

核心 non-substitution rule：

- Source != Observation != Claim != 当前已取得资格的个人记录状态。
- 历史资格状态 != 当前资格状态。
- Context Projection != Personal World 规范状态。
- Personal context != execution authority。
- Domain projection != domain ownership。
- Model inference != 当前已取得资格的个人偏好或事实。

## Runtime

Personal World 没有 native host deployment path。它作为根 AIOS Compose topology 中的 `personal-world` service 运行，durable state 挂载在 `/var/lib/aios`。

API contract 继续要求 `X-Service-Identity` 和 `X-Purpose`；projection 和 search read 继续受 caller data-access 与 sensitivity rule 约束。

## v1.0 closure

四种 public record kind 保持冻结。v1.0 不新增第五种，也不新增 domain lifecycle semantics。它通过 single-root-subject isolation、short-lived signed workload identity、PostgreSQL contention evidence、bitemporal test、cross-surface erasure，以及 exposure 前 replay post-backup erasure 的 physical restore，关闭 production boundary。

Production deployment 设置 `PERSONAL_WORLD_DEPLOYMENT_PROFILE=production`、`PERSONAL_WORLD_ROOT_SUBJECT_ID` 和 `PERSONAL_WORLD_AUTH_MODE=signed-hmac`。Contract name 保持 `personal-world-contracts-v1` 和 `personal-world-conformance-v1`。
