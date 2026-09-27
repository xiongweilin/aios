# 隔离的 V1 acceptance profile

`target/` 目录是用于本地 acceptance 的一次性、可 Docker 化 target。它的 database、DBOS system state、runtime state root 和 Docker resource 必须与现有 registered target 分离。该 target 刻意不进入 production bootstrap manifest。

当前 target 定义及其 immutable base-image/dependency 选择记录在 [target/README.md](target/README.md)。Acceptance evidence 与每次运行绑定：health/readiness、SBOM、vulnerability、failure injection 和 end-to-end result 必须从该次实际使用的 image 和 environment 收集。

运行输出不是 source code，不提交到 `acceptance/runs/`。CI 应把它们保留为 workflow artifact；本地 acceptance 在需要时应保留到 operator 控制的 evidence location。Git history 保存此前已经提交的 acceptance snapshot。
