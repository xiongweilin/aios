# control-plane

> AIOS domain 组件。权威英文原文：[README.md](README.md)。源码：`src/domains/control_plane/`；Runtime：根目录 `compose.yaml`。

这是 [world-runtime](../../kernel/world_runtime/README.md) 的 AIOS Domain Controller，负责 authenticated personal/platform operations、monitoring、bounded repair 和 narrowly scoped effects。它刻意不是第二个 World Runtime。

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

## 所有权边界

Control Plane 拥有 alert/manual-task ingress、domain-local controller state、local Work/Run projection、bounded repair policy、provider selection/concrete execution、environment facts/monitoring observation、local operational reconciliation、notification 和 local source/deployment integration。

World Runtime 继续是 persistent Responsibility、DomainAssignment lifecycle、durable Decision、responsibility assessment/discharge、typed evidence/outcome reference 的 canonical owner。

边界通过 protocol 建立，而不是 Python import。Production source 不得 import `world_runtime`；统一 `pyproject.toml` 也不得形成 Control Plane → World Runtime 的 package-level dependency。

## Runtime handshake

启动时必须精确匹配：

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

不匹配即 fail closed。

## Bounded incident repair

Firing alert 不会因为模型给出 diagnosis 就变成 authorized action。流程：

```text
monitoring signal
→ authenticated ingress
→ World Runtime Responsibility + DomainAssignment
→ PersonalController
→ RepairEpistemicProfile
→ bounded diagnosis
→ RepairClosure
→ DomainWork / DomainRun
→ bounded concrete provider
→ reality observation / verification
→ RepairRevision
→ close | reopen | wait
→ typed DomainReport
→ World Runtime assessment / Decision / discharge
```

不存在 model-to-effect shortcut。Diagnosis 不携带 authority；RepairClosure 是 domain planning object，不是 universal Runtime Decision；provider success 不是 target recovery。

## Local semantic scope

`PersonalController`、`RepairClosure`、`RepairRevision`、`DomainWork`、`DomainRun`、`DomainJournal` 都是 control-plane implementation semantics，不替代 universal `Responsibility`、`Decision`、`Authorization`、`Evidence`、`Outcome`、`Goal`。

Concrete provider 保持 Domain-local；effect provider 在行动前独立复查相关 project/state constraint。Model selection 不扩大 effect scope。

## Recovery 与禁止回归的结构

`DomainJournal` 只保存 local controller/work/run continuity。Restart 时可以把 stale local `running` 修成 `waiting`、把 run 标为 interrupted，但不能声称 completion。

Universal responsibility、assignment 和 decision 永远不在本地重建。

不得重新引入 embedded/copied World Runtime、in-process WorldRuntime、复制的 cognition/execution/ledger kernel、agent-kernel/meta-controller compatibility layer、generic authorization/evidence/responsibility owner 或 portable embedded Runtime。

## Service 与 reality effect boundary

Service 只提供 health/readiness/metrics、authenticated task/monitoring ingress、controller continuation 和 local operational-state inspection。

Control Plane 仅作为根 Compose topology 中的 `control-plane` service 运行。Runtime、agent/model、monitoring 都通过 container network 或 external API；host-local listener 不属于 runtime contract。

Runtime Protocol 4.0 下，属于 local/remote write 的 capability 必须先经 World Runtime admit stable Work、attest Decision/Mandate/Authorization、绑定 durable effect identity，并由 `domain-effect-execution-v3` 授予一次 dispatch 后才能执行。Read-only cognition 保持 Controller-local。
