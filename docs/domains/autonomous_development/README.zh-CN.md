# autonomous-development

> AIOS domain 组件。源码：`src/domains/autonomous_development/`。Runtime：根目录 `compose.yaml`。

面向容器的自主软件开发和产品演进 control plane。

> 一个 durable、evidence-driven lifecycle boundary，覆盖 requirement intake、verification、progressive delivery、feedback attribution、promotion 和 rollback。

## 当前 V1 snapshot

V1 lifecycle surface 和 provider-neutral operator API 属于本组件。Disposable acceptance target 使用 pinned Python 3.14 Alpine image、带 upstream fix 的 zlib package，并保持 `grype --fail-on high` security gate 不变。Disposable verification fixture 见 acceptance target record。

系统拥有完整闭环：

```text
requirement
  -> diagnose / plan
  -> build
  -> verify
  -> deploy candidate
  -> user traffic
  -> telemetry / feedback
  -> diagnose
  -> modify
  -> test / evaluate
  -> canary
  -> promote or rollback
  -> repeat
```

V1 刻意不把某个具体 coding agent 纳入 domain semantics。Engineering execution 是 provider boundary；concrete executor 是 deployment choice。本组件持有 selected executor 周围的 durable development lifecycle、evidence、quality gate、progressive delivery、feedback attribution、promotion 和 rollback decision。

## V1 design

- V1 architecture、semantics、lifecycle 和 acceptance criteria：`docs/v1-design.md`
- Human requirement/operator API contract：`docs/operator-contract.md`
- External research basis 与 adopted/rejected idea：`docs/v1-research-basis.md`

## V1 boundary

V1 是 standalone bounded context。Core package 不得 import 或 require：

- `agent-kernel`
- `meta-controller`
- `administrative-orchestrator`

这些项目可以启发 design decision，但不定义本组件的 domain semantics。

V1 现在有可选 HTTP-only `WorldRuntimeDevelopmentBridge`。Domain/application layer 只依赖一个小 port，不 import `world-runtime` Python package 或 Runtime internal。在 cutover mode 中，bridge 把一次 Development cycle 镜像为 generic standing Responsibility/Work/Run，并且只有本 domain 独立 promote release 后，才把 opaque evidence reference 报告给 Runtime 进行 assessment/Decision/discharge。

World Runtime **不**拥有 worktree、Git branch、Docker build、verification gate、canary stage、source promotion、rollback 或 `ReleasedVersion` semantics。

V1 一次面向一个 registered software/Agent product。Product goal 由 human 持有；goal 内的 implementation 和 iterative improvement 可以自主运行。Container runtime 是唯一 local execution substrate。Agent/model 和 monitoring dependency 通过 container-network service 或 external API 接入，而不是 host-local program。

Implementation 暴露 operator API 和 durable workflow boundary，不内置 user interface。Human requirement 进入 provider-neutral operator API，绝不会转换成 `UserFeedback`。

## World Runtime reality boundary

设置 `AUTODEV_WORLD_RUNTIME_MODE=cutover` 后，Runtime Protocol 4.0 要求 `AUTODEV_WORLD_RUNTIME_BEARER_TOKEN`。Deployment、traffic mutation、source promotion 和 source restore 仍是 Development-owned provider semantics，但它们改变现实的 dispatch 在 configured deployment、traffic-state 或 Git mutation 发生前必须通过 `domain-effect-execution-v3`。Read-only observation、candidate worktree、implementation、build 和 verification 继续留在 Development 本地。

## Container runtime

Autonomous Development 只作为根 AIOS Compose topology 中的 `autonomous-development` service 运行。Workspace 通过 `/workspace` 提供，并使用 mounted Docker socket 构建、检查和管理 sibling target container。Target container 加入 `AUTODEV_DOCKER_NETWORK`，使 readiness、performance check 和 product traffic 使用 container DNS。只有 deterministic `autodev-<deployment-id>` HTTP name 和 loopback URL 可以作为 local deployment target；其单独 publish 的 port 仍绑定 host loopback。不支持 native Autodev service 或 host Python process 作为 runtime path。
