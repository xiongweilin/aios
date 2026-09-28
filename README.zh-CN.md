# AIOS

[![CI](https://github.com/xiongweilin/aios/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/xiongweilin/aios/actions/workflows/ci.yml) [![SonarCloud Quality Gate](https://sonarcloud.io/api/project_badges/measure?project=metratio_aios&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=metratio_aios) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE) [![Docs: EN / 中文](https://img.shields.io/badge/docs-EN%20%7C%20%E4%B8%AD%E6%96%87-blue.svg)](README.zh-CN.md)

[English](README.md) | [简体中文](README.zh-CN.md)

AIOS 是一个 headless、仅容器运行的统一 runtime。

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

上面的名称都是内部语义所有者，不是彼此独立的产品或仓库。

## 仓库结构

```text
src/
  aios/                         runtime 组合
  semantic/
    semantic_language/          跨领域角色词汇与引用边界
  kernel/
    personal_world/             个人连续性
    world_runtime/              agency 连续性
  domains/
    control_plane/              运维
    administrative_orchestrator/
    autonomous_development/

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
scripts/
```

仓库只有一个 Python 项目、一张依赖图、一个源码根目录和一个测试根目录。Semantic、kernel 和 domain ownership 都是这个单一项目内部的物理源码分组。

## 运行时

AIOS 没有 UI。服务通过 API/CLI 暴露系统集成边界，并全部以容器方式运行。

```bash
docker compose up -d
```

所有 AIOS runtime 组件都是容器。Host 不会把 Personal World、World Runtime、Control Plane、Administrative 或 Autonomous Development 作为原生程序运行。Host 只提供容器 runtime 和 bind-mounted 资源，例如 Autodev workspace 或 Docker socket。

Agent 实现、LLM provider、Prometheus 以及其他外部依赖通过容器网络端点或外部 API 访问。AIOS runtime 配置不能依赖 host 本机程序 listener。

AIOS 面向持续、无人值守运行，而不是交互式助手产品。用户通常不直接操作 runtime。需要检查、解释或维护时，用户可以通过已有的外部 Agent 产品建立一次短期 session。该 Agent 读取权威状态、解释当前情况，只执行边界明确且已授权的变更，验证 read-back 和恢复状态，报告结果，然后断开连接。

Agent session 既不是持久权威所有者，也不是必须持续存在的 runtime 依赖；session 结束后 AIOS 继续运行。API/CLI 边界用于系统集成和维护，而不是主要的用户管理界面。

## 开发

AIOS runtime 始终保持仅容器运行。仓库检查可以在 CI 或一次性开发容器中执行，但这些都不是产品部署路径。

```bash
docker build -t aios:local .
docker compose config --quiet
```

各组件的具体语义和契约位于对应的 `docs/` 和 `contracts/` 路径中。
