# Autonomous Development V1 acceptance target

这是一个刻意独立、很小的 FastAPI target，只用于本地 acceptance。它不是 `autonomous-development` repository，也不得注册到 production database。Acceptance runbook 会为该 target 创建独立 PostgreSQL database、DBOS system state、state root、Docker image 和 serving release。

Image 使用固定官方 Python 3.14.7 Alpine amd64 builder/runtime digest。Dependency 只在一次性 builder stage 中以 root 安装，然后复制到显式 non-root UID 65532 runtime image。这个仅 HTTP 的 target 使用普通 `uvicorn` 而不是 `uvicorn[standard]`。最终 runtime 用从 upstream zlib commit `df84af25dc1942490e1d1c899a07619152a46148` 本地构建的 package 替换 Alpine zlib package；该 commit 包含 CVE-2026-85091 的 upstream fix。

## 当前 image 定义

- Builder/runtime base：`python:3.14.7-alpine3.24@sha256:4677924bcc0e94505a3270e87cb1601c2af54cd92d021b8dc306618a14333bbe`。
- Direct runtime pin：`fastapi==0.141.1`、`uvicorn==0.53.0`、`anyio==4.15.1`、`h11==0.16.0`、`idna==3.20`。
- 替换的 Alpine package：`zlib-1.3.2.1-r0`，从 upstream commit `df84af25dc1942490e1d1c899a07619152a46148` 构建，并通过 Python zlib runtime 验证。
- Image 以 UID `65532` 运行，只在 port `8000` 暴露 HTTP contract。

固定 digest 和 package pin 是 target definition 的一部分。本地 image ID 只是一次 build 的 evidence，不是 production release identity；应把它与该次 acceptance evidence 一起记录，而不是替换 Dockerfile pin。

## Verification contract

每个 accepted build 必须为该目录构建的 image 证明：

1. `/health` 返回 `{"status":"ok"}`，`/ready` 返回 `{"status":"ready"}`；
2. `/answer?value=  Hello  ` 返回 normalized `hello` response；
3. Syft 记录固定 `zlib-1.3.2.1-r0` package 和 pinned Python dependencies；
4. `grype --fail-on high` 成功退出。Medium/low finding 继续可见，不转换成 security exception。
