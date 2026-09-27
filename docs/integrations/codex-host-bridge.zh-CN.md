# Windows Codex CLI bridge

AIOS 拥有 durable work、release 和 recovery state。Windows Codex CLI 只是 external turn executor；其本地 account/configuration 和 thread store 不是 AIOS source of truth。

## 拓扑

```text
AIOS Linux containers -> authenticated JSON-RPC/WebSocket -> host.docker.internal:18786
                                                          -> Codex Desktop bundled CLI App Server
                                                          -> LLM Gateway Agent entry (4101)
```

LLM Gateway 为 Windows Codex process 提供 model API routing，不是 CLI execution endpoint。Host start script 读取 Gateway 的 `config/gateway.json`，把 Agent entry URL 作为 process-local Codex override；不会改变 Desktop user 的 Codex configuration。AIOS container 通过 App Server 执行，不依赖 Gateway 持有 AIOS work state。

## 启停

```powershell
pwsh -NoProfile -File .\scripts\windows\prepare-autodev-operator-secret.ps1
pwsh -NoProfile -File .\scripts\windows\start-codex-app-server.ps1
docker compose --env-file .env.example up -d --build
```

脚本在 ignored `.aios-data/codex-bridge` 下创建专用 transport capability token 和 read-only host path map，然后启动 Codex Desktop 自带 `codex.exe`，只绑定 Windows loopback。默认读取 `D:\agent\llm-gateway\config\gateway.json`；权威配置位于别处时传 `-GatewayConfigPath`。脚本绝不打印或复制 Codex login credential。Docker Desktop 通过 `host.docker.internal` 访问 listener；不创建 LAN listener 或 firewall rule。

Operator HMAC key 单独生成并持久化在 ignored `.aios-data/secrets`。Prometheus 作为 Compose-managed service 运行；AIOS 通过 private Compose network 访问。

只停止已记录 listener：

```powershell
pwsh -NoProfile -File .\scripts\windows\stop-codex-app-server.ps1
```

默认 path map 限制在 AIOS workspace 和 Autodev/Control Plane state mount。如果 bind root 不同，启动脚本传入匹配的 `-WorkspaceRoot`、`-AutodevStateRoot`、`-ControlPlaneStateRoot`，Compose 使用相同 root。

## Identity、timeout 与 recovery

每个 client 标识为 `autonomous-development` 或 `control-plane`，并声明 `aios-codex-bridge/1`。WebSocket authentication 使用独立 capability token，而不是 Windows Codex login。

AIOS 在自己的 state volume 中 journal 每个 request ID、prompt digest、thread/turn ID、dispatch phase、server version 和 result digest。只有对应 turn 到达 terminal `completed` status 后才接受 result。

| State | Retry behavior |
| --- | --- |
| `prepared` | 尚未发送 turn；同一个 request ID 可以继续。 |
| `dispatching` / `running` | 根据 stored thread reconcile matching request marker；绝不能 duplicate dispatch。 |
| `completed` | 返回 recovered result 前验证 thread、turn、status 和 result digest。 |
| `unknown` | AIOS operation 保持 unknown；不要 blind replay。检查后或明确使用新 request ID。 |
| `failed` | 保留 failure；有意 retry 使用新 request ID。 |

CLI 停止后，AIOS 仍保留 responsibility 和 recovery state；中断 turn 可以保持 `unknown`，绝不会静默变成 successful release。

## Compatibility

Remote Codex App Server WebSocket transport 是 experimental。当前设置只适用于所请求的 same-machine Docker Desktop development topology。Listener 必须 loopback-only 且经过 authentication；production 使用前替换成 production-supported bridge。
