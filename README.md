# AIOS

Windows service controller for the local Personal AIOS profile. The repository contains only the controller; project source stays in its owner repositories.

## Use

Run `dist/aios.exe` to open the compact selector. It separates dependency services from Domain services. The last checked profile is saved locally and restored the next time the window opens. Opening the window does not start or stop anything; choose an action explicitly.

- Dependencies: World Runtime, Personal World, LiteLLM Gateway.
- Domain services: Control Plane, Administrative Orchestrator, Autonomous Development.
- Agency Console BFF is a fixed default: every start starts or reuses it, and every stop stops it when AIOS owns its process.
- Feishu gateways remain outside this controller for now.

The controller starts selected services in dependency-first order and stops them in reverse order. Selecting Control Plane automatically starts its hard World Runtime dependency if it was not selected. It launches each project's executable entry point directly rather than depending on separate project start/stop launchers. Control Plane requests elevation through the normal Windows UAC prompt when needed. A service already reachable is not launched again. AIOS stops tracked processes by PID plus creation-time identity; it can also stop an existing service after its listening port and process command are verified against that project. An unverified port occupant is left untouched and reported. Administrative Orchestrator uses its project Compose file; stop is `docker compose stop`, preserving containers and volumes.

After a start action, the controller opens `https://aios.metratio.com`. Extension presence and installation guidance are determined by the page's Extension/Local Bridge handshake, never by the executable.

## Commands

```text
aios.exe start [service-id ...]
aios.exe stop [service-id ...]
aios.exe status [service-id ...]
aios.exe logs [service-id ...]
```

Use `start` or `stop` without IDs to apply the complete selectable profile. `status` reports the profile's services. `logs` opens the local AIOS log folder, or the selected service log when an ID is provided. The GUI always applies the remembered selection; Agency Console BFF remains the fixed default.

Local profile, process records, and logs live under `%LOCALAPPDATA%\Metratio\AIOS`; they are not committed to this repository.

## Workflow and ownership

Human authority is the explicit Start/Stop button plus the checked profile. The executable validates service IDs, applies idempotent running checks, launches the project's direct command, records process identities, and writes local operational logs. Each service owner remains authoritative for its service code and configuration. Running is a no-op on retry; failed/stopped services can be retried. Stop affects only selected services plus the fixed-default BFF; Compose stop preserves durable data. Invalid service IDs are rejected, and failures remain visible in the window/logs. Feishu services are outside this workflow.

## Build

Requires Go 1.22 or newer on Windows and the inbox Windows PowerShell 5.1 UI runtime.

```powershell
./build.ps1
```

The packaged executable is `dist/aios.exe`.
