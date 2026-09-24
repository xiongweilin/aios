#Requires -Version 7.0

[CmdletBinding()]
param(
    [string]$TaskName = 'ControlPlane',
    [string]$LiveUrl = 'http://127.0.0.1:18083/live',
    [string]$WorldRuntimeHealthUrl = 'http://127.0.0.1:18086/healthz'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# 2026-09-21: World Runtime 是 control-plane 的硬依赖，但它是 control-plane
# 进程的兄弟进程而非子进程。这里复用 launcher 的 -EnsureWorldRuntimeOnly
# 路径确保依赖存在，不新增独立计划任务。
try {
    $runtimeProbe = Invoke-WebRequest -Uri $WorldRuntimeHealthUrl -Method Get -TimeoutSec 5 -SkipHttpErrorCheck
    $runtimeHealthy = ($runtimeProbe.StatusCode -eq 200)
}
catch {
    $runtimeHealthy = $false
}

if (-not $runtimeHealthy) {
    $launcher = Join-Path $PSScriptRoot 'Run-ControlPlane.ps1'
    if (Test-Path -LiteralPath $launcher -PathType Leaf) {
        try {
            & pwsh -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $launcher -EnsureWorldRuntimeOnly | Out-Null
        }
        catch {
            # Recovery of control-plane below still runs; runtime health is
            # re-observed on the next watchdog tick.
        }
    }
}

try {
    $response = Invoke-WebRequest -Uri $LiveUrl -Method Get -TimeoutSec 5 -SkipHttpErrorCheck
    if ($response.StatusCode -eq 200) {
        exit 0
    }
}
catch {
    # The task state below determines whether recovery is safe; response bodies are not logged.
}

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
switch ($task.State) {
    'Ready' {
        Start-ScheduledTask -TaskName $TaskName
        exit 0
    }
    'Running' {
        # Run-ControlPlane.ps1 owns hung-child detection and restart thresholds.
        exit 0
    }
    default {
        throw "$TaskName cannot be recovered from state $($task.State)"
    }
}
