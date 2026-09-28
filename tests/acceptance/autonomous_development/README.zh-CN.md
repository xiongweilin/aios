# 隔离的 V1 acceptance profile

`target/` 目录是用于 acceptance 的一次性、可 Docker 化 target。独立 CI workflow 每次创建唯一 Compose project、隔离的 PostgreSQL/DBOS state、runtime state root、临时 target Git repository、Docker network 和 serving release。readiness 使用协议级 Codex stub，不调用真实模型 provider，也不会注册到 production。

当前 target 定义及其 immutable base-image/dependency 选择记录在 [target/README.md](target/README.md)。Acceptance evidence 与每次运行绑定：health/readiness、SBOM、vulnerability、failure injection 和 end-to-end result 必须从该次实际使用的 image 和 environment 收集。

运行输出不是 source code，不提交到 `acceptance/runs/`。CI 应把它们保留为 workflow artifact；本地 acceptance 在需要时应保留到 operator 控制的 evidence location。Git history 保存此前已经提交的 acceptance snapshot。

本地运行完整隔离生命周期：

```bash
python tests/acceptance/autonomous_development/run_acceptance.py \
  --evidence-path /path/to/acceptance-evidence.json
```

Runner 会把 target bootstrap 到临时 Autodev database，等待 runtime 和 target readiness，向 target reality 写入一个真实 task，重启 target container，通过 HTTP contract 和 container 文件系统分别读回 task，扫描 image，最后移除临时 target container、Compose project、images 和 state。
