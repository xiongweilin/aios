#Requires -Version 7.0
#Requires -RunAsAdministrator

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$deploymentDir = $PSScriptRoot
$launcher = Join-Path $deploymentDir 'Run-ControlPlane.ps1'
$taskNames = @('ControlPlane', 'ControlPlaneWatchdog')
$liveUrl = 'http://127.0.0.1:18083/live'
$pwsh = Join-Path $PSHOME 'pwsh.exe'

function Test-HttpOk {
    param([Parameter(Mandatory)][string]$Url)

    try {
        $response = Invoke-WebRequest -Uri $Url -Method Get -TimeoutSec 5 -SkipHttpErrorCheck
        return [int]$response.StatusCode -eq 200
    }
    catch {
        return $false
    }
}

foreach ($taskName in $taskNames) {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
    if ($task.State -eq 'Disabled') {
        Enable-ScheduledTask -TaskName $taskName -ErrorAction Stop | Out-Null
    }
}

if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
    throw "Control-plane launcher not found: $launcher"
}

# Use the same control-plane-owned launcher entry that the watchdog uses. It
# starts World Runtime only when 127.0.0.1:18086/healthz is not healthy.
& $pwsh -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass `
    -File $launcher -EnsureWorldRuntimeOnly 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw 'World Runtime did not become healthy at 127.0.0.1:18086/healthz.'
}

if (-not (Test-HttpOk -Url $liveUrl)) {
    $task = Get-ScheduledTask -TaskName 'ControlPlane' -ErrorAction Stop
    if ($task.State -ne 'Running') {
        Start-ScheduledTask -TaskName 'ControlPlane' -ErrorAction Stop
    }
}

$deadline = (Get-Date).AddSeconds(60)
while ((Get-Date) -lt $deadline) {
    if (Test-HttpOk -Url $liveUrl) {
        Write-Host 'ControlPlane and World Runtime are running.'
        exit 0
    }
    Start-Sleep -Seconds 1
}

throw 'ControlPlane did not become healthy at 127.0.0.1:18083/live.'
