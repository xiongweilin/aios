# AIOS 仓库指令

AIOS 是一个产品、一个 Python 项目。

所有权：

- `semantic_language`：跨领域 semantic distinction。
- `personal_world` 和 `world_runtime`：kernel。
- `control_plane`、`administrative_orchestrator`、`autonomous_development`：domains。
- `aios`：只负责 composition 和 product runtime。

不要重新创建 component repository 或顶层 component project root。新的 Python source 放在统一 `src/` 树下，test 放在统一 `tests/` 树下。

AIOS runtime 是 headless 且仅容器运行。所有 AIOS service 都通过根 Compose topology 运行；native Windows service、scheduled task、systemd unit 或 host Python/Node process 都不是有效 runtime path。UI concern 不属于这里。Agent、model、monitoring 和其他外部系统必须保持可替换，通过 container-network endpoint 或 external API 接入。

保持 semantic boundary：evidence 不是 authority，authorization 不是 effect，provider success 不是 outcome，domain completion 继续由 domain owner 持有。
