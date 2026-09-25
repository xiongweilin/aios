# Windows Codex CLI bridge

AIOS owns durable work, release, and recovery state. The Windows Codex CLI is an
external turn executor only; its local account/configuration and thread store
are not AIOS's source of truth.

## Topology

```text
AIOS Linux containers -> authenticated JSON-RPC/WebSocket -> host.docker.internal:18786
                                                          -> Windows Codex App Server
                                                          -> LLM Gateway endpoint from Windows Codex configuration
```

The LLM Gateway provides model API routing for the Windows Codex process. It is
not a CLI execution endpoint. Its configured model API endpoint is read by the
Windows Codex process; the AIOS container reaches the App Server for execution
and does not depend on the Gateway to own AIOS work state.

## Start and stop

```powershell
pwsh -NoProfile -File .\scripts\windows\prepare-autodev-operator-secret.ps1
pwsh -NoProfile -File .\scripts\windows\start-codex-app-server.ps1
docker compose --env-file .env.example up -d --build
```

The script creates a dedicated transport capability token and read-only host
path maps under the ignored `.aios-data/codex-bridge` directory, then starts
the installed Codex CLI bound to Windows loopback only. It never prints or
copies the Codex login credential. Docker Desktop reaches the listener through
`host.docker.internal`; no LAN listener or firewall rule is created.
The Operator HMAC key is separately generated and persisted under the ignored
`.aios-data/secrets` directory. Prometheus runs as a Compose-managed service;
AIOS reaches it through the private Compose network.

Stop only that recorded listener with:

```powershell
pwsh -NoProfile -File .\scripts\windows\stop-codex-app-server.ps1
```

The default path maps are restricted to the AIOS workspace and its
Autodev/Control Plane state mounts. If the bind roots differ, pass matching
`-WorkspaceRoot`, `-AutodevStateRoot`, and `-ControlPlaneStateRoot` values to
the start script and use the same roots in Compose.

## Identity, timeout, and recovery

Each client identifies as `autonomous-development` or `control-plane` and
advertises `aios-codex-bridge/1`. WebSocket authentication uses a separate
capability token, not the Windows Codex login.

AIOS journals each request ID, prompt digest, thread/turn IDs, dispatch phase,
server version, and result digest in its own state volume. A result is accepted
only after the matching turn reaches terminal `completed` status.

| State | Retry behavior |
| --- | --- |
| `prepared` | No turn was sent; the same request ID may continue. |
| `dispatching` or `running` | Reconcile the matching request marker with the stored thread; never dispatch a duplicate. |
| `completed` | Verify thread, turn, status, and result digest before returning the recovered result. |
| `unknown` | Keep the AIOS operation unknown; do not blindly replay. Inspect or deliberately issue a new request ID. |
| `failed` | Preserve the failure; an intentional retry uses a new request ID. |

If the CLI stops, AIOS still retains responsibility and recovery state; an
interrupted turn can remain `unknown`, never silently become a successful
release.

## Compatibility

Remote Codex App Server WebSocket transport is experimental. This setup is for
the requested same-machine Docker Desktop development topology only. Keep the
listener loopback-only and authenticated; replace this transport with a
production-supported bridge before production use.
