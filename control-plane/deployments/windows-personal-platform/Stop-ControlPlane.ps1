#Requires -Version 7.0
#Requires -RunAsAdministrator

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$taskNames = @('ControlPlaneWatchdog', 'ControlPlane')
$taskErrors = [System.Collections.Generic.List[string]]::new()

foreach ($taskName in $taskNames) {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($null -eq $task) {
        $taskErrors.Add("$taskName scheduled task is not installed.")
        continue
    }

    try {
        Disable-ScheduledTask -TaskName $taskName -ErrorAction Stop | Out-Null
    }
    catch {
        $taskErrors.Add("disable $taskName failed: $($_.Exception.Message)")
    }

    try {
        $task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
        if ($task.State -eq 'Running') {
            Stop-ScheduledTask -TaskName $taskName -ErrorAction Stop
        }
    }
    catch {
        $taskErrors.Add("stop $taskName failed: $($_.Exception.Message)")
    }
}

$deploymentDir = $PSScriptRoot
$projectDir = Split-Path -Parent (Split-Path -Parent $deploymentDir)
$runScript = Join-Path $deploymentDir 'Run-ControlPlane.ps1'
$watchScript = Join-Path $deploymentDir 'Watch-ControlPlane.ps1'
$runVbs = Join-Path $deploymentDir 'Run-ControlPlaneHidden.vbs'
$watchVbs = Join-Path $deploymentDir 'Watch-ControlPlaneHidden.vbs'

function Get-ManagedProcesses {
    $allProcesses = @(Get-CimInstance Win32_Process -ErrorAction Stop)
    return @($allProcesses | Where-Object {
        $commandLine = [string]$_.CommandLine
        $executablePath = [string]$_.ExecutablePath
        $isSupervisor =
            ($commandLine -match [regex]::Escape($runScript)) -or
            ($commandLine -match [regex]::Escape($watchScript)) -or
            ($commandLine -match [regex]::Escape($runVbs)) -or
            ($commandLine -match [regex]::Escape($watchVbs))
        $isControlRuntime =
            ($executablePath -match '(?i)python\.exe$') -and
            ($commandLine -match '(?i)(^|\s)-m\s+control_plane(?:\s|$)')
        $isSupervisor -or $isControlRuntime
    })
}

$managedProcesses = @(Get-ManagedProcesses)
$orderedProcesses = @(
    $managedProcesses | Where-Object {
        $commandLine = [string]$_.CommandLine
        ($commandLine -match [regex]::Escape($runScript)) -or
        ($commandLine -match [regex]::Escape($watchScript)) -or
        ($commandLine -match [regex]::Escape($runVbs)) -or
        ($commandLine -match [regex]::Escape($watchVbs))
    }
    $managedProcesses | Where-Object {
        ([string]$_.ExecutablePath -match '(?i)python\.exe$') -and
        ([string]$_.CommandLine -match '(?i)(^|\s)-m\s+control_plane(?:\s|$)')
    }
)

$stoppedIds = [System.Collections.Generic.HashSet[int]]::new()
foreach ($process in $orderedProcesses) {
    $processId = [int]$process.ProcessId
    if (-not $stoppedIds.Add($processId)) {
        continue
    }

    try {
        Stop-Process -Id $processId -Force -ErrorAction Stop
        Write-Host "stopped control-plane PID $processId."
    }
    catch {
        if (Get-Process -Id $processId -ErrorAction SilentlyContinue) {
            $taskErrors.Add("stop PID $processId failed: $($_.Exception.Message)")
        }
    }
}

for ($attempt = 0; $attempt -lt 20; $attempt++) {
    $remainingProcesses = @(Get-ManagedProcesses)
    $remainingListeners = @(Get-NetTCPConnection -LocalPort 18083 -State Listen -ErrorAction SilentlyContinue)
    if ($remainingProcesses.Count -eq 0 -and $remainingListeners.Count -eq 0) {
        break
    }
    Start-Sleep -Milliseconds 500
}

$remainingProcesses = @(Get-ManagedProcesses)
if ($remainingProcesses.Count -gt 0) {
    $remainingIds = ($remainingProcesses | ForEach-Object { $_.ProcessId }) -join ', '
    $taskErrors.Add("managed service processes remain: $remainingIds")
}
$remainingListeners = @(Get-NetTCPConnection -LocalPort 18083 -State Listen -ErrorAction SilentlyContinue)
if ($remainingListeners.Count -gt 0) {
    $ports = ($remainingListeners | ForEach-Object { $_.LocalPort } | Sort-Object -Unique) -join ', '
    $taskErrors.Add("service listeners remain on port(s): $ports")
}

foreach ($taskName in $taskNames) {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($null -eq $task) {
        continue
    }
    if ($task.State -eq 'Running') {
        $taskErrors.Add("$taskName scheduled task is still running.")
    }
    if ($task.State -ne 'Disabled' -or $task.Settings.Enabled) {
        $taskErrors.Add("$taskName scheduled task is still $($task.State)")
    }
}

if ($taskErrors.Count -gt 0) {
    throw ('control-plane close incomplete: ' + ($taskErrors -join '; '))
}

Write-Host 'ControlPlane and both scheduled tasks are stopped; World Runtime is left untouched.'
exit 0
